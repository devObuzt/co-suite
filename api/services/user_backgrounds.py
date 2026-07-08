"""User-uploaded montage backgrounds: normalization + one-time Gemini vision analysis.

Users upload their own images/videos which become montage scene backgrounds
with top matching priority. Each file is analyzed ONCE at upload time with a
single Gemini vision call that returns strict JSON (description, tags from a
fixed vocabulary, colors, people/text flags). English vocabulary tags are
merged with Arabic/Hebrew synonyms so tag-vs-transcript matching works for
Arabic and Hebrew scene text too.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from ..core.config import settings
from ..core.external_calls import external_call

log = logging.getLogger(__name__)

GEMINI_VISION_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANALYSIS_TIMEOUT_SECONDS = 60
VIDEO_ANALYSIS_FRAME_COUNT = 4

# Fixed background vocabulary. Every entry maps an English tag to small
# Arabic/Hebrew synonym sets; all of them are stored on the asset's tags list
# so `pick_asset` scene-text matching works across languages.
BACKGROUND_TAG_VOCAB: dict[str, dict[str, list[str]]] = {
    "product": {"ar": ["منتج", "منتجات"], "he": ["מוצר"]},
    "nature": {"ar": ["طبيعة"], "he": ["טבע"]},
    "office": {"ar": ["مكتب"], "he": ["משרד"]},
    "food": {"ar": ["طعام", "أكل", "اكل"], "he": ["אוכל"]},
    "coffee": {"ar": ["قهوة", "كافيه"], "he": ["קפה"]},
    "restaurant": {"ar": ["مطعم"], "he": ["מסעדה"]},
    "tech": {"ar": ["تقنية", "تكنولوجيا"], "he": ["טכנולוגיה"]},
    "fashion": {"ar": ["موضة", "أزياء", "ازياء"], "he": ["אופנה"]},
    "beauty": {"ar": ["جمال", "تجميل"], "he": ["יופי"]},
    "interior": {"ar": ["ديكور", "داخلي"], "he": ["עיצוב פנים"]},
    "outdoor": {"ar": ["خارجي"], "he": ["בחוץ"]},
    "city": {"ar": ["مدينة"], "he": ["עיר"]},
    "street": {"ar": ["شارع"], "he": ["רחוב"]},
    "beach": {"ar": ["شاطئ", "بحر"], "he": ["חוף"]},
    "mountain": {"ar": ["جبل"], "he": ["הר"]},
    "sky": {"ar": ["سماء"], "he": ["שמיים"]},
    "night": {"ar": ["ليل"], "he": ["לילה"]},
    "gym": {"ar": ["نادي رياضي", "جيم"], "he": ["חדר כושר"]},
    "sport": {"ar": ["رياضة"], "he": ["ספורט"]},
    "car": {"ar": ["سيارة", "سيارات"], "he": ["רכב"]},
    "travel": {"ar": ["سفر", "سياحة"], "he": ["נסיעה", "טיול"]},
    "hotel": {"ar": ["فندق"], "he": ["מלון"]},
    "shopping": {"ar": ["تسوق"], "he": ["קניות"]},
    "luxury": {"ar": ["فاخر", "فخم"], "he": ["יוקרה"]},
    "minimal": {"ar": ["بسيط"], "he": ["מינימלי"]},
    "colorful": {"ar": ["ملون", "ألوان"], "he": ["צבעוני"]},
    "dark": {"ar": ["داكن", "غامق"], "he": ["כהה"]},
    "bright": {"ar": ["مضيء", "فاتح"], "he": ["בהיר"]},
    "abstract": {"ar": ["تجريدي"], "he": ["מופשט"]},
    "texture": {"ar": ["خامة", "نقشة"], "he": ["טקסטורה"]},
    "water": {"ar": ["ماء", "مياه"], "he": ["מים"]},
    "plants": {"ar": ["نباتات", "زرع"], "he": ["צמחים"]},
    "animals": {"ar": ["حيوانات"], "he": ["חיות"]},
    "kids": {"ar": ["أطفال", "اطفال"], "he": ["ילדים"]},
    "education": {"ar": ["تعليم", "دراسة"], "he": ["חינוך", "לימודים"]},
    "medical": {"ar": ["طبي", "عيادة", "صحة"], "he": ["רפואי"]},
    "real_estate": {"ar": ["عقار", "عقارات"], "he": ["נדלן"]},
    "construction": {"ar": ["بناء", "إنشاءات"], "he": ["בנייה"]},
    "industrial": {"ar": ["صناعي", "مصنع"], "he": ["תעשייה"]},
    "art": {"ar": ["فن", "رسم"], "he": ["אמנות"]},
    "celebration": {"ar": ["احتفال", "حفلة"], "he": ["חגיגה"]},
    "business": {"ar": ["أعمال", "اعمال", "تجارة"], "he": ["עסקים"]},
    "money": {"ar": ["مال", "أرباح"], "he": ["כסף"]},
    "team": {"ar": ["فريق"], "he": ["צוות"]},
    "home": {"ar": ["منزل", "بيت"], "he": ["בית"]},
}


def vocabulary_tags() -> list[str]:
    return sorted(BACKGROUND_TAG_VOCAB.keys())


def normalize_analysis_tags(raw_tags: Any) -> list[str]:
    """Keep only known-vocabulary English tags (tolerates spacing/case noise)."""
    if not isinstance(raw_tags, (list, tuple)):
        return []
    normalized: list[str] = []
    for raw in raw_tags:
        tag = re.sub(r"[\s-]+", "_", str(raw or "").strip().lower())
        if tag in BACKGROUND_TAG_VOCAB and tag not in normalized:
            normalized.append(tag)
    return normalized


def merge_vocab_tags(english_tags: list[str]) -> list[str]:
    """English vocab tags + their Arabic/Hebrew synonyms, deduped, order stable."""
    merged: list[str] = []
    for tag in normalize_analysis_tags(english_tags):
        merged.append(tag)
        entry = BACKGROUND_TAG_VOCAB.get(tag) or {}
        for language in ("ar", "he"):
            for synonym in entry.get(language, []):
                if synonym not in merged:
                    merged.append(synonym)
    return merged


def parse_analysis_json(text: str) -> dict[str, Any] | None:
    """Parse the model's JSON reply (tolerates markdown fences / prose noise)."""
    candidate = str(text or "").strip()
    if not candidate:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_analysis_payload(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    """Coerce a raw model reply into the analysis contract we persist."""
    if not isinstance(parsed, dict):
        return None
    english_tags = normalize_analysis_tags(parsed.get("tags"))
    colors = parsed.get("dominant_colors")
    if not isinstance(colors, (list, tuple)):
        colors = []
    analysis: dict[str, Any] = {
        "description": str(parsed.get("description") or "").strip()[:600],
        "tags": english_tags,
        "dominant_colors": [str(color)[:32] for color in list(colors)[:6]],
        "has_people": bool(parsed.get("has_people")),
        "has_text": bool(parsed.get("has_text")),
    }
    motion = str(parsed.get("motion") or "").strip()
    if motion:
        analysis["motion"] = motion[:200]
    return analysis


def _analysis_prompt(*, is_video: bool) -> str:
    vocab = ", ".join(vocabulary_tags())
    lines = [
        "You analyze media that will be used as a background layer behind a talking person in short marketing videos.",
        (
            "You are given several evenly-spaced frames of ONE video. Analyze them together as one clip."
            if is_video
            else "You are given one image."
        ),
        "Reply with STRICT JSON only (no markdown, no commentary) with exactly these keys:",
        '{"description": "one short english sentence describing the content", '
        '"tags": ["3-8 tags chosen ONLY from the allowed vocabulary"], '
        '"dominant_colors": ["2-4 css hex colors"], '
        '"has_people": true/false, "has_text": true/false'
        + (', "motion": "one short english phrase describing the camera/subject motion"}' if is_video else "}"),
        f"Allowed tags vocabulary: {vocab}.",
    ]
    return "\n".join(lines)


def _gemini_vision_generate(parts: list[dict[str, Any]], *, operation: str, suite_id: str | None = None) -> str:
    url = GEMINI_VISION_URL.format(model=settings.google_vision_model)
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
    }
    with external_call("google", operation, model=settings.google_vision_model, suite_id=suite_id) as call:
        response = httpx.post(
            url,
            json=body,
            headers={"x-goog-api-key": settings.google_api_key},
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )
        call.note(status_code=response.status_code)
        response.raise_for_status()
        payload = response.json()
        for candidate in payload.get("candidates") or []:
            for part in ((candidate.get("content") or {}).get("parts") or []):
                text = part.get("text")
                if text:
                    return str(text)
        call.fail("Gemini vision returned no text part")
    return ""


def _inline_image_part(data: bytes, mime_type: str) -> dict[str, Any]:
    return {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode("ascii")}}


def analyze_image_background(data: bytes, mime_type: str, *, suite_id: str | None = None) -> dict[str, Any] | None:
    """One Gemini vision call for an uploaded background image. None on failure."""
    if not settings.google_api_key:
        return None
    try:
        text = _gemini_vision_generate(
            [{"text": _analysis_prompt(is_video=False)}, _inline_image_part(data, mime_type)],
            operation="background_image_analysis",
            suite_id=suite_id,
        )
    except Exception as exc:
        log.warning("Background image analysis failed: %s", exc)
        return None
    return normalize_analysis_payload(parse_analysis_json(text))


def analyze_video_background(frames: list[bytes], *, suite_id: str | None = None) -> dict[str, Any] | None:
    """One Gemini vision call over N extracted frames of an uploaded video."""
    if not settings.google_api_key or not frames:
        return None
    parts: list[dict[str, Any]] = [{"text": _analysis_prompt(is_video=True)}]
    parts.extend(_inline_image_part(frame, "image/jpeg") for frame in frames)
    try:
        text = _gemini_vision_generate(parts, operation="background_video_analysis", suite_id=suite_id)
    except Exception as exc:
        log.warning("Background video analysis failed: %s", exc)
        return None
    return normalize_analysis_payload(parse_analysis_json(text))


def extract_video_frames(path: Path, count: int = VIDEO_ANALYSIS_FRAME_COUNT) -> list[bytes]:
    """Extract `count` evenly-spaced JPEG frames with ffmpeg."""
    from .video_montage import probe_duration_seconds, run_command

    duration = probe_duration_seconds(path)
    if duration <= 0:
        return []
    frames: list[bytes] = []
    for index in range(count):
        timestamp = duration * (index + 0.5) / count
        target = path.parent / f"{path.stem}-analysis-frame-{index}.jpg"
        try:
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=w=768:h=768:force_original_aspect_ratio=decrease",
                    "-q:v",
                    "4",
                    str(target),
                ]
            )
            if target.exists() and target.stat().st_size > 0:
                frames.append(target.read_bytes())
        except Exception:
            log.warning("Could not extract analysis frame %s from %s", index, path.name)
        finally:
            target.unlink(missing_ok=True)
    return frames


def normalize_image_orientation(data: bytes, content_type: str | None) -> tuple[bytes, str]:
    """Bake EXIF orientation into the pixels so backgrounds never render sideways."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            oriented = ImageOps.exif_transpose(image)
            output = io.BytesIO()
            if (image.format or "").upper() == "PNG":
                oriented.save(output, format="PNG")
                return output.getvalue(), "image/png"
            if oriented.mode not in ("RGB", "L"):
                oriented = oriented.convert("RGB")
            oriented.save(output, format="JPEG", quality=90)
            return output.getvalue(), "image/jpeg"
    except Exception:
        log.warning("Could not normalize image orientation; keeping original bytes", exc_info=True)
        return data, content_type or "image/jpeg"
