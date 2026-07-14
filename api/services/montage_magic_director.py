"""OneShare Magic director: per-scene art direction on top of the shot list.

The "oneshare_magic" montage template treats every scene as its own edit:
a fast Anthropic model looks at each shot-list beat and decides how to stage
it — split layout (background media on the top half blending into a solid
brand-color stage behind the speaker), a huge 3D shadowed title, an optional
converging subtitle, literal emoji icons, one emphasized word (brand name if
spoken), a camera move (zoom in / zoom out / double punch-in) and a scene
sound effect. Any failure degrades to deterministic heuristics per beat type
— a Magic render must still look Magic when the director model is down.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from ..core.ai_client import call_claude
from ..core.config import settings
from ..core.observability import log_event
from ..models.suite import Suite

log = logging.getLogger(__name__)

MAGIC_TEMPLATE = "oneshare_magic"
MONTAGE_TEMPLATES = {"default", MAGIC_TEMPLATE}

MAGIC_LAYOUTS = {"split", "full"}
MAGIC_BACKGROUNDS = {"solid", "video", "image"}
MAGIC_CAMERAS = {"zoom_in", "zoom_out", "punch_in", "none"}
# Keys map onto the tag vocabulary of the built-in sfx library
# (api/static/creative_assets/library/manifest.json).
MAGIC_SFX_QUERIES = {
    "camera": "camera shutter",
    "whoosh": "whoosh swoosh transition",
    "pop": "pop energy",
    "impact": "impact hit boom",
    "riser": "riser build energy",
    "ding": "ding notification",
    "click": "click tick",
}

MAGIC_DIRECTOR_SYSTEM = """You are the ART DIRECTOR for "OneShare Magic", a premium vertical
talking-head montage template. The input is a list of visual beats (already cut from the
transcript) plus brand info. For EACH beat, decide how to stage that single scene.

Per-beat direction fields:
- "layout": "split" — background media fills the TOP HALF and blends down into a SOLID
  brand-color stage behind the speaker (use for the hook/opening statement and bold
  claims where the typography carries the scene); "full" — background media fills the
  whole frame behind the speaker (use for enumerated services/features and rich visuals).
- "background": "video" when motion embodies the spoken meaning (services, actions,
  anything dynamic — e.g. the word "marketing" gets a related moving background),
  "image" for calm narrative moments, "solid" when the 3D title IS the visual
  (punchy one-liners, CTA). Use "video" generously on enumeration beats.
- "title": the beat's headline in the transcript's language, 1-4 words, rendered as a
  huge 3D block title with a hard shadow. For the hook, use the core promise
  (e.g. "محل واحد"). Never punctuation, never a full sentence.
- "subtitle": optional short complement (max 6 words) shown at the opposite edge with a
  converging 3D perspective (top and bottom text lean toward a far vanishing point).
  "" when the scene needs none.
- "icons": 0-3 emoji that LITERALLY depict the spoken idea (e.g. branding → 🎨,
  photography → 📸). [] when none fit naturally.
- "emphasis": the single most important spoken word — the BRAND NAME whenever it is
  spoken — else "".
- "camera": "zoom_in" for the hook/opening, "punch_in" (two quick zoom steps) for
  fast enumeration items, "zoom_out" for the closing/CTA, "none" for calm narration.
- "sfx": one of "camera","whoosh","pop","impact","riser","ding","click" or null —
  "camera" when photography/filming is mentioned, "riser" on the opening build,
  "pop" on list items, "impact" on bold claims, null when silence serves the scene.

Return STRICT JSON only, no prose, no markdown fences:
{"directions": [{"index": <beat index>, "layout": "...", "background": "...",
  "title": "...", "subtitle": "...", "icons": ["..."], "emphasis": "...",
  "camera": "...", "sfx": "..."|null}]}
Exactly one direction per beat, in the same order."""


def montage_template(input_data: dict[str, Any]) -> str:
    value = str((input_data or {}).get("template") or "").strip().lower()
    return value if value in MONTAGE_TEMPLATES else "default"


def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clean_title(value: Any, fallback: str = "") -> str:
    # Big 3D titles carry no punctuation and at most 4 words.
    text = re.sub(r"[.,،؛؟;:!?…'\"()\[\]{}]", " ", str(value or ""))
    words = _clean_text(text, 60).split()
    return " ".join(words[:4]) or fallback


def _clean_icons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    icons: list[str] = []
    for item in value:
        token = str(item or "").strip()
        # Emoji only: any alphanumeric token would render as stray text.
        if not token or len(token) > 8:
            continue
        if any(unicodedata.category(ch).startswith(("L", "N")) for ch in token):
            continue
        icons.append(token)
        if len(icons) == 3:
            break
    return icons


def _beat_title_fallback(beat: dict[str, Any]) -> str:
    keyword = _clean_text((beat or {}).get("keyword"), 40)
    if keyword:
        return keyword
    return " ".join(_clean_text((beat or {}).get("text"), 120).split()[:3])


def heuristic_magic_direction(*, index: int, beat: dict[str, Any] | None, scene_count: int) -> dict[str, Any]:
    """Deterministic staging when the director model is unavailable.

    Mirrors the reference-video grammar: split hook with a riser, punchy
    full-bleed video per enumerated item, solid typographic close.
    """
    beat = beat if isinstance(beat, dict) else {}
    beat_type = str(beat.get("beat_type") or "narrative")
    title = _beat_title_fallback(beat)
    if index == 0:
        return {
            "layout": "split",
            "background": "video",
            "title": title,
            "subtitle": "",
            "icons": [],
            "emphasis": "",
            "camera": "zoom_in",
            "sfx": "riser",
        }
    if beat_type == "cta" or index == scene_count - 1:
        return {
            "layout": "split",
            "background": "solid",
            "title": title,
            "subtitle": "",
            "icons": [],
            "emphasis": "",
            "camera": "zoom_out",
            "sfx": "impact",
        }
    if beat_type == "enumeration":
        return {
            "layout": "full",
            "background": "video",
            "title": title,
            "subtitle": "",
            "icons": [],
            "emphasis": "",
            "camera": "punch_in",
            "sfx": "pop",
        }
    return {
        "layout": "full",
        "background": "image",
        "title": title,
        "subtitle": "",
        "icons": [],
        "emphasis": "",
        "camera": "none",
        "sfx": None,
    }


def validate_magic_directions(
    raw_directions: Any,
    beats: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Sanitize LLM directions into exactly one valid direction per beat.

    Pure function — unit-testable with faked LLM output. Beats the model
    skipped or mangled get the heuristic; returns (directions, llm_count).
    """
    by_index: dict[int, dict[str, Any]] = {}
    if isinstance(raw_directions, list):
        for position, item in enumerate(raw_directions):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", position))
            except (TypeError, ValueError):
                index = position
            if 0 <= index < len(beats) and index not in by_index:
                by_index[index] = item

    directions: list[dict[str, Any]] = []
    llm_count = 0
    for index, beat in enumerate(beats):
        fallback = heuristic_magic_direction(index=index, beat=beat, scene_count=len(beats))
        item = by_index.get(index)
        if not isinstance(item, dict):
            directions.append(fallback)
            continue
        layout = str(item.get("layout") or "").strip().lower()
        background = str(item.get("background") or "").strip().lower()
        camera = str(item.get("camera") or "").strip().lower()
        sfx_raw = item.get("sfx")
        sfx = str(sfx_raw).strip().lower() if sfx_raw else None
        directions.append(
            {
                "layout": layout if layout in MAGIC_LAYOUTS else fallback["layout"],
                "background": background if background in MAGIC_BACKGROUNDS else fallback["background"],
                "title": _clean_title(item.get("title"), fallback["title"]),
                "subtitle": _clean_text(item.get("subtitle"), 80),
                "icons": _clean_icons(item.get("icons")),
                "emphasis": _clean_text(item.get("emphasis"), 30),
                "camera": camera if camera in MAGIC_CAMERAS else fallback["camera"],
                "sfx": sfx if sfx in MAGIC_SFX_QUERIES else None,
            }
        )
        llm_count += 1
    return directions, llm_count


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


async def apply_magic_directions(
    beats: list[dict[str, Any]],
    *,
    suite: Suite,
    notes: str = "",
) -> str:
    """Attach a "magic" direction to every beat in place; returns the source.

    Never raises: any failure stamps heuristic directions so the Magic
    template still renders with its own grammar when the LLM is down.
    """
    if not beats:
        return "no_beats"

    def _fallback(reason: str) -> str:
        for index, beat in enumerate(beats):
            beat["magic"] = heuristic_magic_direction(index=index, beat=beat, scene_count=len(beats))
        log_event(
            log,
            logging.WARNING,
            "Magic director unavailable; using heuristic scene directions.",
            event="montage_magic_director",
            suite_id=suite.id,
            ok=False,
            reason=reason,
            beat_count=len(beats),
        )
        return "heuristic"

    if not settings.anthropic_api_key:
        return _fallback("missing_api_key")

    brand = suite.brand if isinstance(suite.brand, dict) else {}
    payload = {
        "business_name": suite.name,
        "industry": brand.get("industry"),
        "customer_notes": _clean_text(notes, 500) or None,
        "beats": [
            {
                "index": index,
                "start": beat.get("start"),
                "end": beat.get("end"),
                "text": _clean_text(beat.get("text"), 300),
                "beat_type": beat.get("beat_type"),
                "keyword": beat.get("keyword"),
                "visual_prompt": _clean_text(beat.get("visual_prompt"), 300),
            }
            for index, beat in enumerate(beats)
        ],
    }
    try:
        text = await call_claude(
            model=settings.anthropic_fast_model,
            max_tokens=4000,
            system=MAGIC_DIRECTOR_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Stage every beat of this montage:\n"
                        f"{json.dumps(payload, ensure_ascii=False)}"
                    ),
                }
            ],
            timeout=90,
        )
    except Exception:
        log.exception("Magic director LLM call failed; using heuristic scene directions.")
        return _fallback("llm_call_failed")

    parsed = _extract_json(text)
    if parsed is None:
        return _fallback("unparseable_response")
    directions, llm_count = validate_magic_directions(parsed.get("directions"), beats)
    for beat, direction in zip(beats, directions):
        beat["magic"] = direction
    log_event(
        log,
        logging.INFO,
        "Magic director staged the montage scenes.",
        event="montage_magic_director",
        suite_id=suite.id,
        ok=True,
        beat_count=len(beats),
        llm_directed=llm_count,
        heuristic_filled=len(beats) - llm_count,
        layouts={
            layout: sum(1 for d in directions if d["layout"] == layout)
            for layout in sorted({d["layout"] for d in directions})
        },
    )
    return "llm" if llm_count else "heuristic"
