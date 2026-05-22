"""Video generator using Veo 3.1 Fast (or other Veo variants).

Three video subtypes are supported (set by Claude in `idea['video_subtype']`):

  * `animation`        — 2D motion-graphics output. No overlay.
  * `english_hook`     — Veo 3 renders an English hook visible inside the video.
                         No overlay (Veo handles the text).
  * `video_with_titles` — clean live-action visual, optional English title
                         overlaid in post-production.

Audio: instrumental only (music + SFX from Veo 3). Voiceover is OFF by default
(`idea['use_voiceover']` to opt in). The TTS+mux pipeline is preserved for
when we want it.
"""
import logging
import time
from pathlib import Path

from google import genai
from google.genai import types as gtypes

from . import audio_mixer, tts, video_overlay
from .config import (
    GOOGLE_API_KEY,
    PROMPTS,
    VIDEO_MODEL,
)

log = logging.getLogger(__name__)
_client = genai.Client(api_key=GOOGLE_API_KEY)

# Pricing (Google AI Studio, May 2026 — adjust if pricing changes)
COST_PER_SECOND = {
    "veo-3.0-generate-001": 0.40,
    "veo-3.0-fast-generate-001": 0.15,
    "veo-3.1-generate-preview": 0.40,
    "veo-3.1-fast-generate-preview": 0.15,
    "veo-3.1-lite-generate-preview": 0.075,
}

DEFAULT_DURATION_SEC = 8
POLL_INTERVAL_SEC = 15
MAX_WAIT_SEC = 600  # 10 min

VALID_SUBTYPES = {"animation", "english_hook", "video_with_titles"}


def _subtype(idea: dict) -> str:
    s = (idea.get("video_subtype") or "").strip()
    return s if s in VALID_SUBTYPES else "video_with_titles"


def _video_model_for_idea(idea: dict) -> str:
    request = idea.get("generation_request") or {}
    tier = (request.get("model_tier") or "auto").strip()
    if tier == "fast":
        return "veo-3.1-lite-generate-preview"
    if tier == "quality":
        return "veo-3.1-generate-preview"
    return VIDEO_MODEL


DEFAULT_DIVISIONS = {
    "design": {"name_en": "Design", "color_name": "yellow"},
    "marketing": {"name_en": "Marketing", "color_name": "pink"},
    "development": {"name_en": "Development", "color_name": "cyan"},
    "media": {"name_en": "Media", "color_name": "teal"},
    "academy": {"name_en": "Academy", "color_name": "green"},
}


def _brand_video_context(brand: dict | None) -> str:
    brand = brand or {}
    colors = brand.get("colors") or {}
    services = brand.get("services") or brand.get("products") or []
    return (
        f"Business name: {brand.get('name') or 'the business'}.\n"
        f"Industry/niche: {brand.get('industry') or brand.get('niche') or 'business services'}.\n"
        f"Tone: {brand.get('tone') or 'professional, credible, modern'}.\n"
        f"Colors: {colors.get('primary') or '#4f46e5'}, {colors.get('secondary') or '#111827'}, {colors.get('accent') or '#f8fafc'}.\n"
        f"Services/products: {', '.join(services[:8]) if services else 'the business offer'}.\n"
        f"Audience: {brand.get('target_audience') or 'relevant local customers'}."
    )


def _build_prompt(idea: dict, brand: dict | None = None) -> str:
    div = DEFAULT_DIVISIONS.get(idea["division"], DEFAULT_DIVISIONS["marketing"])
    template = PROMPTS["video_enhancement_base"]
    subtype = _subtype(idea)

    # Music
    music_style = (idea.get("music_style") or "").strip()
    if not music_style:
        defaults = {
            "design": "upbeat modern electronic instrumental, light and creative",
            "marketing": "energetic confident pop-electronic instrumental",
            "development": "lo-fi tech-house instrumental, focused vibe",
            "media": "cinematic ambient with soft percussion",
            "academy": "warm uplifting acoustic-electronic instrumental",
        }
        music_style = defaults.get(idea["division"], "modern uplifting instrumental")
    music_directive = (
        f"{music_style}. Matches the pacing of the visuals and ends naturally with the clip. "
        "Mixed at a level that leaves headroom in the mid-range so we can layer audio in post."
    )

    # SFX
    sfx_notes = (idea.get("sfx_notes") or "").strip()
    if not sfx_notes:
        sfx_notes = (
            "Subtle ambient room tone and diegetic SFX that match the on-screen action "
            "(footsteps, clicks, fabric movement, page turns, etc.)."
        )
    sfx_directive = f"{sfx_notes} Realistic, not exaggerated."

    # Subtype-specific block
    if subtype == "english_hook":
        english_hook = (idea.get("video_hook_en") or "").strip() or "Stop wasting it"
        subtype_directive = PROMPTS["video_subtype_english_hook"].format(
            english_hook=english_hook
        )
    elif subtype == "animation":
        subtype_directive = PROMPTS["video_subtype_animation"].format(
            color_name=div["color_name"]
        )
    else:  # video_with_titles
        subtype_directive = PROMPTS["video_subtype_video_with_titles"]

    return template.format(
        division_name=div["name_en"],
        color_name=div["color_name"],
        topic=idea.get("topic", ""),
        aspect_ratio=idea.get("aspect_ratio", "9:16"),
        detailed_prompt=(
            f"BRAND CONTEXT:\n{_brand_video_context(brand)}\n\n"
            f"SCENE:\n{idea.get('video_prompt') or idea.get('image_prompt', '')}"
        ),
        music_directive=music_directive,
        sfx_directive=sfx_directive,
        subtype_directive=subtype_directive,
    )


def generate_video(idea: dict, out_dir: Path, brand: dict | None = None) -> tuple[Path, float]:
    """Generate a Veo 3 video, then optionally overlay an Arabic title and/or
    mux a separate voiceover. Returns (final_path, total_cost_usd).
    """
    subtype = _subtype(idea)
    prompt = _build_prompt(idea, brand)
    aspect = idea.get("aspect_ratio", "9:16")
    model = _video_model_for_idea(idea)

    log.info(
        "Submitting Veo 3 job for post %s (subtype=%s, %s)…",
        idea.get("id", "?"), subtype, idea.get("topic", ""),
    )

    operation = _client.models.generate_videos(
        model=model,
        prompt=prompt,
        config=gtypes.GenerateVideosConfig(aspect_ratio=aspect),
    )

    waited = 0
    while not operation.done:
        if waited >= MAX_WAIT_SEC:
            raise TimeoutError(f"Veo 3 generation timed out after {MAX_WAIT_SEC}s")
        time.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC
        operation = _client.operations.get(operation)
        log.info("…still generating (waited %ds)", waited)

    if not operation.response or not operation.response.generated_videos:
        raise RuntimeError(f"Veo 3 returned no video. Operation: {operation}")

    generated = operation.response.generated_videos[0]
    raw_video_path = out_dir / "video_raw.mp4"
    _client.files.download(file=generated.video)
    generated.video.save(str(raw_video_path))

    veo_cost = COST_PER_SECOND.get(model, 0.40) * DEFAULT_DURATION_SEC
    log.info("Veo 3 raw video saved (cost ≈ $%.2f)", veo_cost)

    total_cost = veo_cost
    current_video = raw_video_path

    # ---- Stage 2: Title overlay (only for video_with_titles) ----
    # Prefer English overlay for video. Arabic/Hebrew glyphs are intentionally
    # kept out of Veo and video overlays for now; captions carry local-language
    # copy until we have a typography QA loop for video.
    if subtype == "video_with_titles":
        title_en = (idea.get("video_title_en") or idea.get("video_hook_en") or "").strip()
        overlaid = out_dir / "video_with_overlay.mp4"
        try:
            if title_en:
                video_overlay.overlay_english_title(
                    video_path=current_video,
                    title_en=title_en[:60],
                    output_path=overlaid,
                )
                current_video = overlaid
                log.info("English title overlaid: %s", title_en)
            else:
                log.info("No English title provided — keeping clean Veo video")
        except Exception as e:
            log.exception("Title overlay failed; keeping raw video: %s", e)

    # ---- Stage 3: Optional voiceover (opt-in via idea['use_voiceover']) ----
    use_vo = bool(idea.get("use_voiceover"))
    voiceover_text = (
        idea.get("voiceover_ar_tashkeel") or idea.get("voiceover_ar") or ""
    ).strip()

    if use_vo and voiceover_text:
        try:
            voice_path = out_dir / "voiceover.mp3"
            tts.synthesize(voiceover_text, voice_path)
            tts_cost = tts.estimate_cost(voiceover_text)
            total_cost += tts_cost

            muxed = out_dir / "video_muxed.mp4"
            audio_mixer.mux_voiceover(
                video_path=current_video,
                voiceover_path=voice_path,
                output_path=muxed,
            )
            current_video = muxed
            log.info("Voiceover muxed (TTS ≈ $%.3f, total ≈ $%.2f)", tts_cost, total_cost)
        except Exception as e:
            log.exception("TTS + mux failed; keeping video without voiceover: %s", e)

    # ---- Finalize: rename whatever the current pipeline produced to video.mp4 ----
    final_path = out_dir / "video.mp4"
    if current_video != final_path:
        if final_path.exists():
            final_path.unlink()
        current_video.rename(final_path)

    return final_path, total_cost
