"""LLM shot list: turn a spoken transcript into literal visual beats.

Reference-video finding (the quality bar): winning montages change the
background roughly every 1.9 seconds — about every second while the speaker
enumerates services — and every spoken beat gets a LITERAL visual
("استشارة" → a laptop video-call scene, "تصوير ومونتاج" → an editing
timeline). A fast Anthropic model splits the transcript into such beats;
validation repairs the timeline so the beats exactly tile the spoken range.
Any failure degrades to the existing sentence-level scenes — a montage must
render even when the LLM is down.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.ai_client import call_claude
from ..core.config import settings
from ..core.observability import log_event
from ..models.suite import Suite

log = logging.getLogger(__name__)

BEAT_TYPES = {"enumeration", "narrative", "cta"}
BEAT_PREFERENCES = {"image", "video"}
# A scene shorter than this cannot register visually at 30fps with entrance
# and exit transitions eating ~0.8s of it.
MIN_BEAT_SECONDS = 0.5

SHOT_LIST_SYSTEM = """You are a video editor building a SHOT LIST for a short vertical marketing montage.
The input is a spoken-video transcript with timestamps. Split it into VISUAL BEATS:
each beat is one moment that gets its own background visual behind the speaker.

Beat rules:
- When the speaker enumerates services/features/items, create one beat PER ITEM,
  roughly 0.8-1.5 seconds each — fast rhythmic cuts (beat_type "enumeration").
- Narrative or explanatory speech gets one beat per idea, roughly 2-4 seconds
  (beat_type "narrative").
- A closing call-to-action gets beat_type "cta".
- Beats must EXACTLY tile the transcript time range: the first beat starts at the
  transcript start, every beat starts exactly where the previous one ends, and the
  last beat ends at the transcript end. Never leave gaps and never overlap. Keep
  every boundary inside the transcript's own start/end bounds.
- "text" is the exact spoken words of the beat, in the transcript's language.
- "visual_prompt" is ENGLISH: a LITERAL, concrete depiction of what the spoken
  words mean — a scene an image generator can draw (e.g. a consulting service →
  "open laptop on a desk showing a video call interface, warm office lighting";
  filming/editing → "video editing timeline on a large monitor in a dark studio").
  NOT abstract mood, shapes, or gradients. Absolutely no people, faces, hands,
  bodies, or human silhouettes; no readable text, logos, or UI screenshots.
- "keyword" is 1-2 words in the transcript's language naming the beat (used as an
  on-screen title behind the speaker).
- "prefer" is "video" only when continuous motion is essential to the meaning;
  otherwise "image".

Return STRICT JSON only, no prose, no markdown fences:
{"beats": [{"start": <seconds>, "end": <seconds>, "text": "...",
  "beat_type": "enumeration"|"narrative"|"cta",
  "visual_prompt": "...", "keyword": "...", "prefer": "image"|"video"}]}"""


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


def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def validate_shot_list_beats(
    raw_beats: Any,
    *,
    range_start: float,
    range_end: float,
    max_beats: int,
) -> list[dict[str, Any]] | None:
    """Sanitize LLM beats and repair the timeline so they exactly tile the range.

    Pure function — unit-testable with faked LLM output. Returns None when the
    beats are unusable (the caller then falls back to sentence scenes).
    """
    if not isinstance(raw_beats, list) or max_beats < 2:
        return None
    if range_end - range_start < 2 * MIN_BEAT_SECONDS:
        return None

    beats: list[dict[str, Any]] = []
    for item in raw_beats:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        text = _clean_text(item.get("text"), 500)
        visual_prompt = _clean_text(item.get("visual_prompt"), 500)
        if not text or not visual_prompt:
            continue
        beat_type = str(item.get("beat_type") or "narrative").strip().lower()
        if beat_type not in BEAT_TYPES:
            beat_type = "narrative"
        prefer = str(item.get("prefer") or "image").strip().lower()
        if prefer not in BEAT_PREFERENCES:
            prefer = "image"
        keyword = " ".join(_clean_text(item.get("keyword"), 80).split()[:2])
        beats.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "beat_type": beat_type,
                "visual_prompt": visual_prompt,
                "keyword": keyword,
                "prefer": prefer,
            }
        )
    if len(beats) < 2:
        return None
    beats.sort(key=lambda beat: (beat["start"], beat["end"]))

    # Never drop the tail: beats beyond the cap merge into the last kept beat.
    if len(beats) > max_beats:
        tail = beats[max_beats - 1 :]
        merged = dict(tail[0])
        merged["end"] = tail[-1]["end"]
        merged["text"] = " ".join(beat["text"] for beat in tail)[:500]
        merged["beat_type"] = "narrative"
        beats = beats[: max_beats - 1] + [merged]

    # Repair tiling: contiguous windows clamped to [range_start, range_end].
    # Degenerate windows fold their text into the neighbouring beat instead of
    # leaving a hole in the montage timeline.
    tiled: list[dict[str, Any]] = []
    cursor = range_start
    pending_text: list[str] = []
    for index, beat in enumerate(beats):
        is_last = index == len(beats) - 1
        end = range_end if is_last else min(max(float(beat["end"]), cursor), range_end)
        if end - cursor < MIN_BEAT_SECONDS:
            if is_last and tiled:
                tiled[-1]["end"] = round(range_end, 3)
                tiled[-1]["text"] = _clean_text(f"{tiled[-1]['text']} {beat['text']}", 500)
            else:
                pending_text.append(beat["text"])
            continue
        item = dict(beat)
        item["start"] = round(cursor, 3)
        item["end"] = round(end, 3)
        if pending_text:
            item["text"] = _clean_text(" ".join(pending_text + [item["text"]]), 500)
            pending_text = []
        tiled.append(item)
        cursor = end
    if len(tiled) < 2:
        return None
    tiled[-1]["end"] = round(range_end, 3)
    return tiled


async def generate_shot_list(
    transcript_segments: list[dict[str, Any]],
    *,
    suite: Suite,
    notes: str = "",
    max_beats: int = 24,
) -> list[dict[str, Any]] | None:
    """Transcript → validated visual beats, or None when the LLM path failed.

    Never raises: a montage must render (with sentence scenes) even when the
    shot-list model is down or returns garbage.
    """
    segments = [
        {
            "start": round(float(segment.get("start") or 0), 2),
            "end": round(float(segment.get("end") or 0), 2),
            "text": _clean_text(segment.get("text"), 500),
        }
        for segment in transcript_segments or []
        if float(segment.get("end") or 0) > float(segment.get("start") or 0)
        and _clean_text(segment.get("text"), 500)
    ]

    def _fail(reason: str, level: int = logging.WARNING) -> None:
        log_event(
            log,
            level,
            "Montage shot list unavailable; falling back to sentence scenes.",
            event="montage_shot_list",
            suite_id=suite.id,
            ok=False,
            reason=reason,
        )

    if not segments:
        _fail("no_transcript")
        return None
    range_start = min(segment["start"] for segment in segments)
    range_end = max(segment["end"] for segment in segments)
    if range_end - range_start < 2 * MIN_BEAT_SECONDS:
        _fail("transcript_too_short")
        return None
    if not settings.anthropic_api_key:
        _fail("missing_api_key")
        return None

    brand = suite.brand if isinstance(suite.brand, dict) else {}
    payload = {
        "business_name": suite.name,
        "industry": brand.get("industry"),
        "customer_notes": _clean_text(notes, 500) or None,
        "max_beats": max_beats,
        "transcript_range": {"start": range_start, "end": range_end},
        "transcript": segments[:64],
    }
    try:
        text = await call_claude(
            model=settings.anthropic_fast_model,
            max_tokens=4000,
            system=SHOT_LIST_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Build the shot list (at most {max_beats} beats) for this transcript:\n"
                        f"{json.dumps(payload, ensure_ascii=False)}"
                    ),
                }
            ],
            timeout=90,
        )
    except Exception:
        log.exception("Montage shot-list LLM call failed; falling back to sentence scenes.")
        _fail("llm_call_failed")
        return None

    parsed = _extract_json(text)
    if parsed is None:
        _fail("unparseable_response")
        return None
    beats = validate_shot_list_beats(
        parsed.get("beats"),
        range_start=range_start,
        range_end=range_end,
        max_beats=max_beats,
    )
    if not beats:
        _fail("invalid_beats")
        return None

    type_counts: dict[str, int] = {}
    for beat in beats:
        type_counts[beat["beat_type"]] = type_counts.get(beat["beat_type"], 0) + 1
    durations = [beat["end"] - beat["start"] for beat in beats]
    log_event(
        log,
        logging.INFO,
        "Montage shot list generated.",
        event="montage_shot_list",
        suite_id=suite.id,
        ok=True,
        beat_count=len(beats),
        beat_types=type_counts,
        prefer_video=sum(1 for beat in beats if beat["prefer"] == "video"),
        avg_beat_seconds=round(sum(durations) / len(durations), 2),
        range_seconds=round(range_end - range_start, 2),
    )
    return beats
