"""LLM analysis of free-text montage notes into actionable directives.

The customer types Arabic (or any language) notes like "بدون موسيقى نهائيا".
A fast Anthropic model maps every request in the notes to one of the montage
capabilities we actually support, so user text can override the toggles, and
anything we cannot do is reported back honestly as "unsupported" instead of
being silently ignored.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.ai_client import call_claude
from ..core.config import settings
from ..core.observability import log_event

log = logging.getLogger(__name__)

MONTAGE_OPTION_IDS = {"captions", "dead_spaces", "background", "titles", "music", "voice_cleanup"}

CAPABILITY_CATALOG = """You analyze a customer's free-text notes for an automatic short-video montage.
Map every distinct request in the notes to one supported action, or mark it unsupported.

Supported actions (the ONLY things the renderer can do):
- {"type": "set_option", "option": "<id>", "enabled": true|false}
  option ids: captions (on-screen subtitles), dead_spaces (cut silent gaps),
  background (remove/replace the video background), titles (big 3D titles behind the person),
  music (background music AND transition sound effects), voice_cleanup (voice EQ/denoise/loudness).
- {"type": "set_zoom", "value": <number 1.0-3.0>}  zoom on the person, anchored at the face.
- {"type": "set_offset", "x": <number -40..40>, "y": <number -40..40>}  move the person, percent of canvas.
- {"type": "music_mood", "mood": "<short keyword(s)>"}  bias which library music track is picked (e.g. "هادئة", "حماسية").
- {"type": "caption_style", "style": "large"|"small"}  make captions bigger or smaller.
- {"type": "none"}  for anything else (specific fonts, colors, exact cut points, adding clips/images, emojis, speed changes, ...).

Return STRICT JSON only, no prose, no markdown fences:
{"directives": [{"request": "<the user's request, short, in the notes' language>",
  "supported": true|false,
  "action": {...one of the actions above...},
  "detail": "<one short Arabic sentence describing what will (or cannot) be done>"}]}

Rules:
- One directive per distinct request in the notes. Ignore filler text that requests nothing.
- supported=false must use action {"type": "none"}.
- "بدون موسيقى" / "no music" => set_option music enabled=false. Requests about quiet/calm music => music_mood.
- detail must ALWAYS be in Arabic."""


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def analyze_montage_notes(notes: str) -> list[dict[str, Any]] | None:
    """Return the directives list for the notes, or None when analysis failed.

    Never raises: a montage must render even when the LLM is down.
    """
    clean = str(notes or "").strip()
    if not clean:
        return []
    if not settings.anthropic_api_key:
        log.warning("Skipping montage notes analysis: ANTHROPIC_API_KEY is missing.")
        return None
    try:
        text = await call_claude(
            model=settings.anthropic_fast_model,
            max_tokens=1200,
            system=CAPABILITY_CATALOG,
            messages=[{"role": "user", "content": f"Customer montage notes:\n{clean[:3000]}"}],
            timeout=60,
        )
    except Exception:
        log.exception("Montage notes analysis LLM call failed; rendering without directives.")
        return None
    parsed = _extract_json(text)
    if parsed is None:
        log.warning("Montage notes analysis returned unparseable output; rendering without directives.")
        return None
    directives = parsed.get("directives")
    if not isinstance(directives, list):
        log.warning("Montage notes analysis returned no directives list; rendering without directives.")
        return None
    return [item for item in directives if isinstance(item, dict)][:12]


def _clamp(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback


def apply_notes_directives(
    input_data: dict[str, Any],
    directives: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply supported directives to a copy of the job input (user text wins).

    Returns (effective_input, notes_analysis) where notes_analysis is
    {"honored": [...], "unsupported": [...]} with Arabic display strings.
    Pure function — unit-testable with a faked LLM response.
    """
    effective = dict(input_data)
    options = effective.get("options")
    option_set = {str(item) for item in options} if isinstance(options, list) else set()
    honored: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []

    for directive in directives:
        request = re.sub(r"\s+", " ", str(directive.get("request") or "")).strip()[:200]
        detail = re.sub(r"\s+", " ", str(directive.get("detail") or "")).strip()[:300]
        if not request:
            continue
        entry = {"request": request, "detail": detail}
        action = directive.get("action") if isinstance(directive.get("action"), dict) else {}
        action_type = str(action.get("type") or "none")
        if not directive.get("supported") or action_type == "none":
            unsupported.append(entry)
            continue

        if action_type == "set_option":
            option = str(action.get("option") or "")
            if option not in MONTAGE_OPTION_IDS:
                unsupported.append(entry)
                continue
            if action.get("enabled", True):
                option_set.add(option)
            else:
                option_set.discard(option)
            honored.append(entry)
        elif action_type == "set_zoom":
            effective["zoom"] = round(_clamp(action.get("value"), 1.0, 3.0, 1.0), 2)
            honored.append(entry)
        elif action_type == "set_offset":
            if action.get("x") is not None:
                effective["subject_offset_x"] = round(_clamp(action.get("x"), -40.0, 40.0, 0.0), 1)
            if action.get("y") is not None:
                effective["subject_offset_y"] = round(_clamp(action.get("y"), -40.0, 40.0, 0.0), 1)
            honored.append(entry)
        elif action_type == "music_mood":
            mood = re.sub(r"\s+", " ", str(action.get("mood") or "")).strip()[:80]
            if not mood:
                unsupported.append(entry)
                continue
            effective["music_mood"] = mood
            honored.append(entry)
        elif action_type == "caption_style":
            style = str(action.get("style") or "").strip().lower()
            if style not in {"large", "small"}:
                unsupported.append(entry)
                continue
            effective["caption_style"] = style
            honored.append(entry)
        else:
            unsupported.append(entry)

    effective["options"] = sorted(option_set)
    return effective, {"honored": honored, "unsupported": unsupported}


async def analyze_and_apply_montage_notes(
    *,
    job_id: str,
    suite_id: str,
    input_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Full notes flow: analyze, apply, log. Returns (effective_input, notes_analysis).

    On any analysis failure the original input is returned untouched and
    notes_analysis is None — the render must never fail because of notes.
    """
    notes = str(input_data.get("notes") or "").strip()
    if not notes:
        return input_data, None
    directives = await analyze_montage_notes(notes)
    if directives is None:
        log_event(
            log,
            logging.WARNING,
            "Montage notes analysis failed; rendering with the toggles as-is.",
            event="montage_notes_analysis",
            job_id=job_id,
            suite_id=suite_id,
            ok=False,
        )
        return input_data, None
    effective, notes_analysis = apply_notes_directives(input_data, directives)
    log_event(
        log,
        logging.INFO,
        "Montage notes analyzed and applied.",
        event="montage_notes_analysis",
        job_id=job_id,
        suite_id=suite_id,
        ok=True,
        directives=len(directives),
        honored=len(notes_analysis["honored"]),
        unsupported=len(notes_analysis["unsupported"]),
        effective_options=effective.get("options"),
    )
    return effective, notes_analysis
