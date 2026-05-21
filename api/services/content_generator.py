"""Multi-tenant content generation service.

Adapts connec-content-engine's idea_generator + image_generator to work
with any suite's brand data instead of the hardcoded Connec brand.json.
"""
import json
import logging
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.config import settings
from ..core.ai_client import call_claude_sync
from ..models.content import ContentPost, PostFormat, PostStatus
from ..models.suite import Suite

log = logging.getLogger(__name__)

_PROMPTS_PATH = Path(__file__).parent.parent / "engine" / "config" / "prompts.json"
with open(_PROMPTS_PATH, "r", encoding="utf-8") as _f:
    _PROMPTS = json.load(_f)

STATIC_DIR = Path(__file__).parent.parent / "static" / "posts"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

DIVISION_META = {
    "design": {"name_en": "Design", "color_name": "yellow", "color": "#E5B833"},
    "marketing": {"name_en": "Marketing", "color_name": "pink", "color": "#E84A8A"},
    "development": {"name_en": "Development", "color_name": "cyan", "color": "#2CB8D9"},
    "media": {"name_en": "Media", "color_name": "teal", "color": "#1B7F78"},
    "academy": {"name_en": "Academy", "color_name": "green", "color": "#7CB342"},
}


def _build_brand_summary(brand: dict, strategy: Optional[dict] = None) -> str:
    """Build Claude-friendly brand summary from a suite's brand + strategy dicts."""
    name = brand.get("name") or brand.get("tagline", "Business")
    desc = brand.get("description") or brand.get("tagline", "")
    industry = brand.get("industry", "")
    tone = brand.get("tone", "professional and friendly")
    services = brand.get("services") or []
    audience = brand.get("target_audience", "general audience")
    colors = brand.get("colors") or {}
    primary_color = colors.get("primary", "#333333")

    services_str = ", ".join(services[:8]) if services else "general services"

    summary = (
        f"Business name: {name}\n"
        f"Industry: {industry}\n"
        f"Description: {desc}\n"
        f"Services: {services_str}\n"
        f"Brand tone: {tone}\n"
        f"Target audience: {audience}\n"
        f"Primary brand color: {primary_color}"
    )

    if strategy:
        plan = strategy.get("marketing_plan") or {}
        audience_data = plan.get("audience") or {}
        summary += (
            f"\n\nMARKETING STRATEGY CONTEXT:"
            f"\nMarketing message: {strategy.get('marketing_message', '')}"
            f"\nCore audience problem: {audience_data.get('problem', '')}"
            f"\nUSP: {brand.get('unique_value', '')}"
            f"\nESP: {brand.get('esp', '')}"
            f"\nContent themes: {', '.join(plan.get('content_themes') or [])}"
        )

    return summary


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _generate_ideas(brand: dict, count: int = 3, recent_topics: list[str] | None = None, strategy: Optional[dict] = None, language: str = "ar") -> list[dict]:
    """Call Claude to generate post ideas for a given brand."""
    video_count = 1 if count >= 3 else 0
    carousel_count = 1 if count >= 2 else 0
    image_count = max(1, count - video_count - carousel_count)

    recent_str = (
        "\n".join(f"- {t}" for t in (recent_topics or [])[:10])
        or "(no previous posts)"
    )

    system = _PROMPTS["idea_generator_system"].format(
        brand_summary=_build_brand_summary(brand, strategy)
    )
    # Append character directive so Claude writes correct video_prompt descriptions
    system += (
        "\n\n--- VIDEO CHARACTER RULE ---\n"
        "Whenever you write a video_prompt that includes people or human characters, "
        "they MUST look Levantine Arab — Lebanese, Jordanian, Syrian, or Palestinian appearance. "
        "Olive to light-tan skin, dark hair, dark eyes. Mediterranean-European (Italian/Greek/Spanish) "
        "is acceptable variation. NEVER East Asian, South Asian, or Nordic/Scandinavian."
    )
    lang_labels = {
        "ar": "Arabic (natural, professional — not heavy formal)",
        "he": "Hebrew",
        "en": "English",
        "fr": "French",
        "es": "Spanish",
        "tr": "Turkish",
    }
    lang_label = lang_labels.get(language, language)
    if language != "ar":
        system += (
            f"\n\n--- LANGUAGE RULE ---\n"
            f"Generate ALL captions, hooks, hashtags, and visible text in {lang_label}. "
            f"The language of every caption must be {lang_label} only. "
            f"Do NOT use Arabic unless the language is Arabic."
        )
    user = _PROMPTS["idea_generator_user"].format(
        count=count,
        image_count=image_count,
        carousel_count=carousel_count,
        video_count=video_count,
        recent_ideas=recent_str,
    )

    for attempt in range(3):
        try:
            raw = call_claude_sync(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            data = json.loads(_strip_json_fences(raw))
            return _normalize_ideas(data.get("posts", []))
        except json.JSONDecodeError as e:
            log.warning("Attempt %d: invalid JSON from Claude: %s", attempt + 1, e)
    return []


def _normalize_ideas(posts: list[dict]) -> list[dict]:
    """Apply connec-content-engine's format validation rules to generated ideas."""
    normalized = []
    for idea in posts:
        idea["division"] = _division_key(idea)
        fmt = idea.get("format", "image")
        if fmt not in ("image", "carousel", "video"):
            fmt = "image"
        idea["format"] = fmt

        if fmt == "carousel":
            slides = idea.get("carousel_slides") or []
            if not slides or len(slides) < 2:
                idea["format"] = "image"
                idea.setdefault("image_prompt", idea.get("topic", ""))
            else:
                idea["carousel_slides"] = slides[:6]
                idea["aspect_ratio"] = "1:1"
                for idx, slide in enumerate(idea["carousel_slides"], start=1):
                    slide.setdefault("slide", idx)
                    slide.setdefault("role", "hook" if idx == 1 else ("cta" if idx == len(slides) else "content"))
                    slide.setdefault("title_ar", idea.get("topic", f"Slide {idx}")[:40])
                    slide.setdefault("image_prompt", idea.get("image_prompt", idea.get("topic", "")))

        if idea["format"] == "image":
            idea.setdefault("image_prompt", idea.get("topic", ""))
            idea.setdefault("aspect_ratio", "1:1")
            idea.setdefault("image_title_ar", "")

        if idea["format"] == "video":
            idea.setdefault("video_prompt", idea.get("image_prompt", idea.get("topic", "")))
            idea.setdefault("aspect_ratio", "9:16")
            subtype = (idea.get("video_subtype") or "").strip()
            if subtype not in {"animation", "english_hook", "video_with_titles"}:
                subtype = "video_with_titles"
            idea["video_subtype"] = subtype
            if subtype == "video_with_titles":
                clean_segments = []
                for segment in idea.get("video_title_segments") or []:
                    if not isinstance(segment, dict):
                        continue
                    text = (segment.get("text") or "").strip()
                    try:
                        start = float(segment.get("start", 0))
                        end = float(segment.get("end", 0))
                    except (TypeError, ValueError):
                        continue
                    if text and end > start:
                        clean_segments.append({"start": start, "end": end, "text": text[:60]})
                idea["video_title_segments"] = clean_segments[:5]
                if not idea["video_title_segments"] and not idea.get("video_title_ar"):
                    idea["video_title_ar"] = idea.get("hook", idea.get("topic", ""))[:40]
            if subtype == "english_hook":
                idea.setdefault("video_hook_en", "Built different")
            idea.setdefault("use_voiceover", False)

        idea.setdefault("hashtags", [])
        idea.setdefault("include_logo", True)
        normalized.append(idea)
    return normalized


def _division_key(idea: dict) -> str:
    division = (idea.get("division") or "marketing").strip()
    return division if division in DIVISION_META else "marketing"


def _division_meta(idea: dict) -> dict:
    return DIVISION_META[_division_key(idea)]


def _image_prompt(idea: dict) -> str:
    div = _division_meta(idea)
    return _PROMPTS["image_enhancement"].format(
        division_name=div["name_en"],
        color_name=div["color_name"],
        color_hex=div["color"],
        topic=idea.get("topic", ""),
        aspect_ratio=idea.get("aspect_ratio", "1:1"),
        detailed_prompt=idea.get("image_prompt", ""),
    )


def _slide_prompt(idea: dict, slide: dict, total_slides: int) -> str:
    div = _division_meta(idea)
    return _PROMPTS["carousel_slide_enhancement"].format(
        slide_number=slide.get("slide", 1),
        total_slides=total_slides,
        division_name=div["name_en"],
        color_name=div["color_name"],
        color_hex=div["color"],
        topic=idea.get("topic", ""),
        slide_role=slide.get("role", "content"),
        detailed_prompt=slide.get("image_prompt", ""),
    )


def _generate_image(prompt: str, aspect_ratio: str = "1:1", extra_images: list | None = None) -> Optional[bytes]:
    """Generate a single image via Gemini image model (falls back to Imagen 4). Returns PNG bytes or None."""
    if not settings.google_api_key:
        return None

    # Primary: Gemini image generation (better multilingual instruction following)
    try:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=settings.google_api_key)
        contents = [prompt]
        if extra_images:
            contents.extend(extra_images)
        resp = client.models.generate_content(
            model=settings.google_image_model,
            contents=contents,
            config=gtypes.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        for candidate in (resp.candidates or []):
            for part in (candidate.content.parts or []):
                if hasattr(part, "inline_data") and part.inline_data:
                    return part.inline_data.data
    except Exception as e:
        log.warning("Gemini image generation failed (%s): %s", settings.google_image_model, e)

    # Fallback: Imagen 4
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes

        _client = _genai.Client(api_key=settings.google_api_key)
        _resp = _client.models.generate_images(
            model="imagen-4.0-fast-generate-001",
            prompt=prompt,
            config=_gtypes.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1" if aspect_ratio == "1:1" else "9:16",
                output_mime_type="image/png",
            ),
        )
        if _resp.generated_images:
            return _resp.generated_images[0].image.image_bytes
    except Exception as e2:
        log.warning("Imagen fallback also failed: %s", e2)

    return None


def _save_media(media_bytes: bytes, post_id: str, filename: str, content_type: str) -> str:
    """Store media bytes and return a public URL.

    In production, prefer R2 so generated media survives Railway redeploys and
    Meta can fetch it over public HTTPS. Local /static paths are only a fallback.
    """
    if (
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket_name
        and settings.r2_public_url
    ):
        try:
            import boto3

            key = f"posts/{filename}"
            s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            s3.put_object(
                Bucket=settings.r2_bucket_name,
                Key=key,
                Body=media_bytes,
                ContentType=content_type,
            )
            return f"{settings.r2_public_url.rstrip('/')}/{key}"
        except Exception as e:
            log.warning("R2 media upload failed, falling back to local static file: %s", e)

    path = STATIC_DIR / filename
    path.write_bytes(media_bytes)
    return f"/static/posts/{filename}"


def _save_image(image_bytes: bytes, post_id: str, slide_idx: int = 0) -> str:
    return _save_media(image_bytes, post_id, f"{post_id}_{slide_idx}.png", "image/png")


def _save_video(video_bytes: bytes, post_id: str) -> str:
    return _save_media(video_bytes, post_id, f"{post_id}.mp4", "video/mp4")


def _overlay_image_title(image_bytes: bytes, idea: dict, title_ar: str, slide_number: int = 1, total_slides: int = 1, role: str = "hook") -> bytes:
    from ..engine.text_overlay import overlay_carousel_title

    tmp_path = STATIC_DIR / f"overlay_{uuid.uuid4().hex}.png"
    tmp_path.write_bytes(image_bytes)
    try:
        overlay_carousel_title(
            tmp_path,
            title_ar=title_ar,
            division_key=_division_key(idea),
            slide_number=slide_number,
            total_slides=total_slides,
            is_hook=(role == "hook"),
            is_cta=(role == "cta"),
        )
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _generate_single_image_media(idea: dict) -> Optional[bytes]:
    prompt = _image_prompt(idea)
    title_ar = (idea.get("image_title_ar") or "").strip()
    if title_ar:
        prompt += (
            "\n\nIMPORTANT: This image is a clean visual background. "
            "DO NOT render any text in the image. Leave the bottom 25-30% "
            "relatively clean and uncluttered. We will add title text in post-processing."
        )
    image_bytes = _generate_image(prompt, idea.get("aspect_ratio", "1:1"))
    if image_bytes and title_ar:
        try:
            image_bytes = _overlay_image_title(image_bytes, idea, title_ar)
        except Exception as e:
            log.warning("Image title overlay failed: %s", e)
    return image_bytes


def _generate_carousel_media(idea: dict) -> list[bytes]:
    from PIL import Image

    slides = idea.get("carousel_slides") or []
    out: list[bytes] = []
    previous = None
    for idx, slide in enumerate(slides, start=1):
        prompt = _slide_prompt(idea, slide, len(slides))
        prompt += (
            "\n\nIMPORTANT: This image is a clean visual background. "
            "DO NOT render any text, letters, words, captions, or readable signs in the image. "
            "Leave the bottom 25-30% of the composition relatively clean and uncluttered. "
            "We will add title text in post-processing."
        )
        extras = []
        if previous is not None:
            extras.append(previous)
            prompt += (
                "\n\nThe previous image is provided as a visual style reference. "
                "Match its color grading, lighting, composition style, and overall aesthetic."
            )
        image_bytes = _generate_image(prompt, "1:1", extra_images=extras)
        if not image_bytes:
            continue
        title_ar = (slide.get("title_ar") or "").strip()
        if title_ar:
            try:
                image_bytes = _overlay_image_title(
                    image_bytes,
                    idea,
                    title_ar,
                    slide_number=idx,
                    total_slides=len(slides),
                    role=slide.get("role", "content"),
                )
            except Exception as e:
                log.warning("Carousel title overlay failed: %s", e)
        out.append(image_bytes)
        try:
            previous = Image.open(BytesIO(image_bytes))
        except Exception:
            previous = None
    return out


def _generate_video_media(idea: dict) -> Optional[bytes]:
    from ..engine.video_generator import generate_video

    out_dir = STATIC_DIR / f"video_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        video_path, _cost = generate_video(idea, out_dir)
        return Path(video_path).read_bytes()
    finally:
        for path in sorted(out_dir.glob("*"), reverse=True):
            path.unlink(missing_ok=True)
        out_dir.rmdir()


async def generate_content_for_suite(suite_id: str, db: AsyncSession, count: int = 3) -> list[str]:
    """
    Main entry point — generates `count` posts for a suite.
    Creates ContentPost rows in DB, triggers image generation, updates URLs.
    Returns list of created post IDs.
    """
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or not suite.brand:
        log.error("Suite %s not found or has no brand", suite_id)
        return []

    brand = suite.brand
    strategy = suite.strategy
    post_ids = []

    # Get recent topics to avoid repetition
    recent_result = await db.execute(
        select(ContentPost.ai_metadata)
        .where(ContentPost.suite_id == suite_id)
        .order_by(ContentPost.created_at.desc())
        .limit(10)
    )
    recent_topics = []
    for (meta,) in recent_result:
        if meta and meta.get("topic"):
            recent_topics.append(meta["topic"])

    # Check suite isn't frozen before generating
    from .billing import is_frozen, record_usage, COSTS
    if await is_frozen(suite_id, db):
        log.warning("Suite %s is frozen — skipping generation", suite_id)
        return []
    await db.commit()

    log.info("Generating %d ideas for suite %s…", count, suite_id)
    audience_languages = brand.get("audience_languages") or ["ar"]
    if not audience_languages:
        audience_languages = ["ar"]

    all_ideas = []
    for lang_code in audience_languages:
        lang_ideas = _generate_ideas(brand, count=count, recent_topics=recent_topics, strategy=strategy, language=lang_code)
        for idea in lang_ideas:
            idea["content_language"] = lang_code
        all_ideas.extend(lang_ideas)
    ideas = all_ideas

    image_count = 0
    generated_video_count = 0
    for idea in ideas:
        fmt_str = idea.get("format", "image")
        fmt = PostFormat.carousel if fmt_str == "carousel" else (
            PostFormat.video if fmt_str == "video" else PostFormat.image
        )
        post_id = str(uuid.uuid4())
        media_urls: list[str] = []

        # Generate image(s) before opening a DB transaction. Image generation can
        # take a while; holding a DB connection here exhausts Railway's pool.
        try:
            if fmt == PostFormat.image:
                img_bytes = _generate_single_image_media(idea)
                if img_bytes:
                    media_urls = [_save_image(img_bytes, post_id, 0)]
                    image_count += 1

            elif fmt == PostFormat.carousel:
                for i, img_bytes in enumerate(_generate_carousel_media(idea)):
                    media_urls.append(_save_image(img_bytes, post_id, i))
                    image_count += 1

            elif fmt == PostFormat.video:
                video_bytes = _generate_video_media(idea)
                if video_bytes:
                    media_urls = [_save_video(video_bytes, post_id)]
                    generated_video_count += 1
        except Exception as e:
            log.warning("Media generation for post %s failed: %s", post_id, e)

        post = ContentPost(
            id=post_id,
            suite_id=suite_id,
            format=fmt,
            status=PostStatus.pending,
            topic=idea.get("topic"),
            caption=idea.get("caption"),
            hashtags=idea.get("hashtags", []),
            ai_metadata=idea,
            media_urls=media_urls,
        )
        db.add(post)
        post_ids.append(post.id)

    await db.commit()
    await record_usage(suite_id, "llm_idea_gen", COSTS["llm_idea_gen"] * count, db)
    if image_count:
        await record_usage(suite_id, "image_gen", COSTS["image_gen"] * image_count, db)
    if generated_video_count:
        await record_usage(suite_id, "video_gen_fast", COSTS["video_gen_fast"] * generated_video_count, db)
    log.info("Created %d posts for suite %s", len(post_ids), suite_id)
    return post_ids
