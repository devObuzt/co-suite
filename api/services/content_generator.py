"""Multi-tenant content generation service.

Adapts connec-content-engine's idea_generator + image_generator to work
with any suite's brand data instead of the hardcoded Connec brand.json.
"""
import json
import logging
import re
import uuid
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
    image_count = max(1, count - 1)
    carousel_count = min(1, count - image_count)
    video_count = 0  # skip video for now (expensive)

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
            return data.get("posts", [])
        except json.JSONDecodeError as e:
            log.warning("Attempt %d: invalid JSON from Claude: %s", attempt + 1, e)
    return []


def _generate_image(prompt: str, aspect_ratio: str = "1:1") -> Optional[bytes]:
    """Generate a single image via Gemini image model (falls back to Imagen 4). Returns PNG bytes or None."""
    if not settings.google_api_key:
        return None

    # Primary: Gemini image generation (better multilingual instruction following)
    try:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=settings.google_api_key)
        resp = client.models.generate_content(
            model=settings.google_image_model,
            contents=prompt,
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


def _save_image(image_bytes: bytes, post_id: str, slide_idx: int = 0) -> str:
    """Save image bytes to static dir. Returns relative URL."""
    filename = f"{post_id}_{slide_idx}.png"
    path = STATIC_DIR / filename
    path.write_bytes(image_bytes)
    return f"/static/posts/{filename}"


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

    # Record LLM cost
    await record_usage(suite_id, "llm_idea_gen", COSTS["llm_idea_gen"] * count, db)

    for idea in ideas:
        fmt_str = idea.get("format", "image")
        fmt = PostFormat.carousel if fmt_str == "carousel" else (
            PostFormat.video if fmt_str == "video" else PostFormat.image
        )

        post = ContentPost(
            id=str(uuid.uuid4()),
            suite_id=suite_id,
            format=fmt,
            status=PostStatus.pending,
            topic=idea.get("topic"),
            caption=idea.get("caption"),
            hashtags=idea.get("hashtags", []),
            ai_metadata=idea,
            media_urls=[],
        )
        db.add(post)
        await db.flush()
        post_ids.append(post.id)

        # Generate image(s)
        try:
            if fmt == PostFormat.image:
                img_prompt = idea.get("image_prompt", "")
                if img_prompt:
                    img_bytes = _generate_image(img_prompt, idea.get("aspect_ratio", "1:1"))
                    if img_bytes:
                        url = _save_image(img_bytes, post.id, 0)
                        post.media_urls = [url]
                        await record_usage(suite_id, "image_gen", COSTS["image_gen"], db)

            elif fmt == PostFormat.carousel:
                slides = idea.get("carousel_slides", [])
                urls = []
                for i, slide in enumerate(slides):
                    slide_prompt = slide.get("image_prompt", "")
                    if slide_prompt:
                        img_bytes = _generate_image(slide_prompt, "1:1")
                        if img_bytes:
                            urls.append(_save_image(img_bytes, post.id, i))
                            await record_usage(suite_id, "image_gen", COSTS["image_gen"], db)
                if urls:
                    post.media_urls = urls
        except Exception as e:
            log.warning("Media generation for post %s failed: %s", post.id, e)

    await db.commit()
    log.info("Created %d posts for suite %s", len(post_ids), suite_id)
    return post_ids
