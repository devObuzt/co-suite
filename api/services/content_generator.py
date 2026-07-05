"""Multi-tenant content generation service.

Adapts connec-content-engine's idea_generator + image_generator to work
with any suite's brand data instead of the hardcoded Connec brand.json.
"""
import asyncio
import json
import logging
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.config import settings
from ..core.ai_client import call_claude_sync
from ..models.content import ContentPost, PostFormat, PostStatus
from ..models.suite import Suite
from .ai_router import (
    AiRoute,
    AiRouteDecision,
    PromptPolicyVersion,
    language_prompt_rules,
    media_backend_for_urls,
    public_url_ready,
    resolve_ai_route,
    text_rendering_mode_for_media,
)
from .content_rules import (
    apply_replace_rules,
    apply_replace_rules_to_item,
    brand_content_rules,
    format_content_rules_prompt,
)
from .media_storage import STATIC_DIR, store_post_media

log = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]

_PROMPTS_PATH = Path(__file__).parent.parent / "engine" / "config" / "prompts.json"
with open(_PROMPTS_PATH, "r", encoding="utf-8") as _f:
    _PROMPTS = json.load(_f)

DIVISION_META = {
    "design": {"name_en": "Design", "color_name": "yellow", "color": "#E5B833"},
    "marketing": {"name_en": "Marketing", "color_name": "pink", "color": "#E84A8A"},
    "development": {"name_en": "Development", "color_name": "cyan", "color": "#2CB8D9"},
    "media": {"name_en": "Media", "color_name": "teal", "color": "#1B7F78"},
    "academy": {"name_en": "Academy", "color_name": "green", "color": "#7CB342"},
}

NATIVE_TEXT_LANGUAGES = {"ar", "he", "en", "fr", "es", "tr", "ru", "zh"}


def _language_label(code: str) -> str:
    return {
        "ar": "Arabic",
        "he": "Hebrew",
        "en": "English",
        "fr": "French",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "zh": "Chinese",
    }.get((code or "").lower(), code or "the target language")


def _text_for_language(idea: dict, language: str, *candidates: str | None) -> str:
    """Pick visible text that is least likely to cross languages.

    Some legacy JSON fields are named *_ar, but they are only field names now;
    for non-Arabic output, prefer neutral fields such as visible_text/hook/topic.
    """
    for candidate in candidates:
        text = (candidate or "").strip()
        if language != "ar" and re.search(r"[\u0600-\u06FF]", text):
            continue
        if language != "he" and re.search(r"[\u0590-\u05FF]", text):
            continue
        if text:
            return text
    return (idea.get("hook") or idea.get("topic") or "").strip()


def _brand_colors(brand: dict) -> dict:
    colors = brand.get("colors") or {}
    return {
        "primary": colors.get("primary") or "#4f46e5",
        "secondary": colors.get("secondary") or "#111827",
        "accent": colors.get("accent") or "#f8fafc",
    }


def _brand_visual_context(brand: dict) -> str:
    colors = _brand_colors(brand)
    fonts = brand.get("font_suggestions") or brand.get("fonts") or []
    services = brand.get("services") or []
    return (
        f"Brand name: {brand.get('name') or 'Business'}\n"
        f"Industry: {brand.get('industry') or brand.get('niche') or ''}\n"
        f"Tone: {brand.get('tone') or 'professional, clear, trustworthy'}\n"
        f"Primary colors: {colors['primary']}, {colors['secondary']}, {colors['accent']}\n"
        f"Fonts/style hints: {', '.join(fonts[:4]) if fonts else 'clean modern typography'}\n"
        f"Services/products: {', '.join(services[:8]) if services else 'business services'}\n"
        f"Logo notes: {brand.get('logo_description') or ''}"
    )


def _native_text_allowed(idea: dict) -> bool:
    mode = (idea.get("text_rendering_mode") or "").strip()
    if mode in {"overlay", "text_free_background"}:
        return False
    if mode in {"native_text_design", "reference_based", "hybrid"}:
        return True
    return (idea.get("content_language") or "ar") in NATIVE_TEXT_LANGUAGES


def _clean_native_visual_direction(text: str) -> str:
    cleaned = text or ""
    patterns = [
        r"avoid any text\.?",
        r"no text(?:s)?(?: inside the image)?\.?",
        r"without any text\.?",
        r"do not render any text\.?",
        r"تجنب أي نصوص\.?",
        r"بدون نصوص\.?",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _quick_reference_urls(idea: dict) -> list[str]:
    brief = ((idea.get("generation_request") or {}).get("creative_brief") or {})
    if not isinstance(brief, dict):
        return []
    urls: list[str] = []
    logo = brief.get("logo") or {}
    if isinstance(logo, dict) and logo.get("enabled") and logo.get("url"):
        urls.append(str(logo["url"]))
    for group in brief.get("reference_assets") or []:
        if isinstance(group, dict):
            urls.extend(str(url) for url in (group.get("urls") or []) if url)
    return urls


def _load_reference_images(brand: dict, extra_urls: list[str] | None = None, limit: int = 6) -> list:
    """Load uploaded/scraped brand and quick-brief images as PIL references for Gemini image models."""
    from PIL import Image

    urls: list[str] = []
    for key in ("logo_url",):
        if brand.get(key):
            urls.append(brand[key])
    for asset in brand.get("logo_assets") or []:
        if isinstance(asset, dict) and asset.get("url"):
            urls.append(asset["url"])
    urls.extend(extra_urls or [])
    loaded = []
    seen = set()
    for url in urls:
        if not url or url in seen or len(loaded) >= limit:
            continue
        seen.add(url)
        try:
            if url.startswith("/static/"):
                path = Path(__file__).parent.parent / url.lstrip("/")
                if path.exists():
                    loaded.append(Image.open(path))
            elif url.startswith("http"):
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"}:
                    continue
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    loaded.append(Image.open(BytesIO(resp.content)))
        except Exception as e:
            log.warning("Could not load brand reference image %s: %s", url, e)
    return loaded


def _build_brand_summary(brand: dict, strategy: Optional[dict] = None, use_brand: bool = True) -> str:
    """Build Claude-friendly brand summary from a suite's brand + strategy dicts."""
    if not use_brand:
        return (
            "Brand mode is off for this generation. Use only the user's prompt, "
            "the target audience language, and general social media best practices. "
            "Do not rely on saved brand colors, services, tone, or positioning."
        )

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

    rules_block = format_content_rules_prompt(brand_content_rules(brand))
    if rules_block:
        summary += f"\n\n{rules_block}"

    return summary


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _idea_format_counts(content_type: str | None, count: int) -> dict[str, int]:
    requested = max(1, min(int(count or 1), 3))
    clean_type = (content_type or "mixed").strip().lower()

    if clean_type == "video":
        return {"image_count": 0, "carousel_count": 0, "video_count": requested}
    if clean_type == "carousel":
        return {"image_count": 0, "carousel_count": requested, "video_count": 0}
    if clean_type == "image":
        return {"image_count": requested, "carousel_count": 0, "video_count": 0}
    if requested >= 3:
        return {"image_count": requested - 2, "carousel_count": 1, "video_count": 1}
    if requested == 2:
        return {"image_count": 1, "carousel_count": 1, "video_count": 0}
    return {"image_count": 1, "carousel_count": 0, "video_count": 0}


def _generate_ideas(
    brand: dict,
    count: int = 3,
    recent_topics: list[str] | None = None,
    strategy: Optional[dict] = None,
    language: str = "ar",
    options: Optional[dict] = None,
) -> list[dict]:
    """Call Claude to generate post ideas for a given brand."""
    options = options or {}
    content_type = (options.get("content_type") or "mixed").strip()
    format_counts = _idea_format_counts(content_type, count)
    image_count = format_counts["image_count"]
    carousel_count = format_counts["carousel_count"]
    video_count = format_counts["video_count"]

    recent_str = (
        "\n".join(f"- {t}" for t in (recent_topics or [])[:10])
        or "(no previous posts)"
    )

    system = _PROMPTS["idea_generator_system"].format(
        brand_summary=_build_brand_summary(brand, strategy, use_brand=options.get("use_brand", True))
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
    system += (
        f"\n\n--- SINGLE LANGUAGE RULE ---\n"
        f"The whole post must be in one language: {lang_label}. "
        f"Generate caption, hook, topic, hashtags, image visible text, carousel slide visible text, and CTA in {lang_label}. "
        "Do not mix languages inside one post. "
        "Legacy field names like image_title_ar, title_ar, and video_title_ar are only schema names; "
        f"their values must still be written in {lang_label}. "
        f"If the post image contains text, that text must be in the same language as the caption: {lang_label}."
    )
    system += "\n" + "\n".join(f"- {rule}" for rule in language_prompt_rules(language))
    system += (
        "\n\n--- MODERN IMAGE MODEL RULE ---\n"
        "The image model can now render designed text and can use reference images. "
        "For image and carousel ideas, decide a text_rendering_mode: "
        "'native_text_design' when the post benefits from built-in headline text, "
        "'text_free_background' only when the image must be pure background, "
        "or 'hybrid' when the model should render core text but leave room for later polish. "
        "Prefer native_text_design for ads, announcements, educational carousel hooks, and strong visual headlines. "
        "Use the visible_text field for the exact text that should appear in the image, in the requested language. "
        "For educational carousel posts, every slide must have short visible_text/title text rendered natively by the model. "
        "The visible text language must match the caption language exactly."
        "\n\n--- VIDEO TITLE RULE ---\n"
        "For video_with_titles, do not ask Veo to render Arabic, Hebrew, or any non-Latin visible text. "
        "If a video needs a visible title, provide video_title_en as a short English title for a post-production overlay. "
        "Keep the local-language message in the caption."
    )
    user = _PROMPTS["idea_generator_user"].format(
        count=count,
        image_count=image_count,
        carousel_count=carousel_count,
        video_count=video_count,
        recent_ideas=recent_str,
    )
    request_bits = []
    if options.get("prompt"):
        request_bits.append(f"USER REQUEST / CREATIVE BRIEF:\n{options['prompt']}")
    if options.get("mode"):
        request_bits.append(f"CREATE MODE: {options['mode']}")
    if content_type and content_type != "mixed":
        request_bits.append(f"FORCE CONTENT FORMAT: {content_type}")
    if options.get("aspect_ratio") and options["aspect_ratio"] != "Auto":
        request_bits.append(f"PREFERRED ASPECT RATIO: {options['aspect_ratio']}")
    if options.get("destination"):
        request_bits.append(f"DESTINATION: {options['destination']}")
    if options.get("model_tier"):
        request_bits.append(f"MODEL TIER: {options['model_tier']}")
    if options.get("creative_brief"):
        request_bits.append(
            "STRUCTURED QUICK POST / AD BRIEF:\n"
            + json.dumps(options["creative_brief"], ensure_ascii=False)[:3500]
            + "\n\nTreat these fields as high-priority production constraints. "
            "If product photos are referenced, preserve product identity and do not redesign or distort the product. "
            "If hook, short_description, or terms are present, use the exact language and respect the text limits: "
            "hook up to 30 characters and max 15% of image area; short description up to 60 characters and max 5%; "
            "terms up to 25 characters, max 5%, and tiny legal text no larger than 10px equivalent. "
            "If required_sizes is present, treat it as the requested production placements and aspect ratios. "
            "For all image sizes, plan compatible image variants for Instagram 4:5, Meta square 1:1, vertical 9:16, wide 16:9, and Google Ads. "
            "For Google Ads image sizes, plan responsive ad crops/assets across square, landscape, portrait, and vertical placements. "
            "For video sizes, obey the requested 9:16 story/reel or 16:9 wide format. "
            "If the brief alone is enough, generate from it even when the free prompt is short."
        )
    if options.get("regenerate_from"):
        request_bits.append(
            "REGENERATE / REPLACE THIS PREVIOUS IDEA:\n"
            + json.dumps(options["regenerate_from"], ensure_ascii=False)[:2500]
        )
    if options.get("feedback"):
        request_bits.append(
            "USER FEEDBACK TO FIX NOW AND LEARN FOR FUTURE:\n"
            + str(options["feedback"])
        )
    if request_bits:
        user += "\n\n" + "\n\n".join(request_bits)

    for attempt in range(3):
        try:
            decision = resolve_ai_route(
                AiRoute.idea_generation,
                tenant_context={"language": language},
                request_context={"language": language, "count": count},
            )
            raw = call_claude_sync(
                model=decision.model,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            data = json.loads(_strip_json_fences(raw))
            ideas = _normalize_ideas(data.get("posts", []), language=language, options=options)
            return _apply_content_rules_to_ideas(ideas, brand)
        except json.JSONDecodeError as e:
            log.warning("Attempt %d: invalid JSON from Claude: %s", attempt + 1, e)
    return []


_IDEA_RULE_FIELDS = ("topic", "caption", "hook", "cta", "visible_text", "image_title_ar", "video_title_ar")
_SLIDE_RULE_FIELDS = ("visible_text", "title_ar", "title", "text", "headline")


def _apply_content_rules_to_ideas(ideas: list[dict], brand: dict) -> list[dict]:
    """Enforce user replace-rules on every text field the audience can see."""
    rules = brand_content_rules(brand)
    if not rules:
        return ideas
    for idea in ideas:
        apply_replace_rules_to_item(idea, rules, _IDEA_RULE_FIELDS)
        for slide in idea.get("carousel_slides") or []:
            if isinstance(slide, dict):
                apply_replace_rules_to_item(slide, rules, _SLIDE_RULE_FIELDS)
        if isinstance(idea.get("hashtags"), list):
            idea["hashtags"] = [apply_replace_rules(tag, rules) for tag in idea["hashtags"]]
    return ideas


def _normalize_ideas(posts: list[dict], language: str = "ar", options: Optional[dict] = None) -> list[dict]:
    """Apply connec-content-engine's format validation rules to generated ideas."""
    options = options or {}
    forced_format = (options.get("content_type") or "").strip()
    if forced_format == "mixed":
        forced_format = ""
    normalized = []
    for idea in posts:
        idea["division"] = _division_key(idea)
        fmt = idea.get("format", "image")
        if fmt not in ("image", "carousel", "video"):
            fmt = "image"
        if forced_format in {"image", "carousel", "video"}:
            fmt = forced_format
        idea["format"] = fmt
        requested_aspect = options.get("aspect_ratio")
        if requested_aspect and requested_aspect != "Auto":
            idea["aspect_ratio"] = requested_aspect

        if fmt == "carousel":
            slides = idea.get("carousel_slides") or []
            if not slides or len(slides) < 2:
                idea["format"] = "image"
                idea.setdefault("image_prompt", idea.get("topic", ""))
            else:
                idea["carousel_slides"] = slides[:6]
                idea["aspect_ratio"] = "1:1"
                idea["text_language"] = language
                idea.setdefault("text_rendering_mode", "native_text_design")
                for idx, slide in enumerate(idea["carousel_slides"], start=1):
                    slide.setdefault("slide", idx)
                    slide.setdefault("role", "hook" if idx == 1 else ("cta" if idx == len(slides) else "content"))
                    fallback_title = idea.get("topic", f"Slide {idx}")[:40]
                    slide.setdefault("title_ar", fallback_title)
                    if language == "ar":
                        slide["visible_text"] = _text_for_language(idea, language, slide.get("visible_text"), slide.get("title_ar"), fallback_title)
                    else:
                        slide["visible_text"] = _text_for_language(
                            idea,
                            language,
                            slide.get("visible_text"),
                            slide.get("title"),
                            slide.get("text"),
                            slide.get("headline"),
                            idea.get("hook"),
                            fallback_title,
                        )
                    slide.setdefault("image_prompt", idea.get("image_prompt", idea.get("topic", "")))

        if idea["format"] == "image":
            idea.setdefault("image_prompt", idea.get("topic", ""))
            idea.setdefault("aspect_ratio", "1:1")
            idea.setdefault("image_title_ar", "")
            if language == "ar":
                idea["visible_text"] = _text_for_language(idea, language, idea.get("visible_text"), idea.get("image_title_ar"), idea.get("hook"))
            else:
                idea["visible_text"] = _text_for_language(idea, language, idea.get("visible_text"), idea.get("hook"), idea.get("topic"))
            idea["text_language"] = language
            idea.setdefault("text_rendering_mode", "native_text_design" if idea.get("visible_text") else "text_free_background")

        if idea["format"] == "video":
            idea.setdefault("video_prompt", idea.get("image_prompt", idea.get("topic", "")))
            idea.setdefault("aspect_ratio", "9:16")
            subtype = (idea.get("video_subtype") or "").strip()
            if subtype not in {"animation", "english_hook", "video_with_titles"}:
                subtype = "video_with_titles"
            idea["video_subtype"] = subtype
            if subtype == "video_with_titles":
                idea.setdefault("video_title_en", idea.get("video_hook_en") or "")
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
            if subtype == "video_with_titles" and not idea.get("video_title_en"):
                idea["video_title_en"] = "Built for growth"
            idea.setdefault("use_voiceover", False)

        idea.setdefault("hashtags", [])
        idea.setdefault("include_logo", True)
        idea["content_language"] = language
        idea["text_language"] = language
        idea.setdefault("generation_request", options)
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


def _native_image_prompt(idea: dict, brand: dict, visible_text: str) -> str:
    div = _division_meta(idea)
    lang = _language_label(idea.get("text_language") or idea.get("content_language") or "ar")
    return (
        "Create a finished, production-ready social media design.\n\n"
        f"BRAND CONTEXT:\n{_brand_visual_context(brand)}\n\n"
        f"CONTENT LANGUAGE: {lang}\n"
        f"EXACT VISIBLE TEXT TO RENDER: {visible_text}\n"
        f"TOPIC: {idea.get('topic', '')}\n"
        f"FORMAT: single post image\n"
        f"ASPECT RATIO: {idea.get('aspect_ratio', '1:1')}\n"
        f"VISUAL DIRECTION: {_clean_native_visual_direction(idea.get('image_prompt', ''))}\n\n"
        "Render the visible text natively inside the image as polished graphic design typography. "
        "Keep the text exactly as provided, readable, well-spaced, and not cropped. "
        + " ".join(language_prompt_rules(idea.get("text_language") or idea.get("content_language")))
        + " "
        "Use strong hierarchy: headline first, supporting visual second. "
        f"Use the {div['name_en']} accent feel if it fits, but prioritize the business brand colors. "
        "Use provided reference images only as brand/style/logo references, not as the whole composition. "
        "Do not add extra words, fake UI, fake phone numbers, fake URLs, or unreadable signage."
    )


def _native_slide_prompt(idea: dict, slide: dict, total_slides: int, brand: dict) -> str:
    div = _division_meta(idea)
    text = slide.get("visible_text") or slide.get("title_ar") or ""
    lang = _language_label(idea.get("text_language") or idea.get("content_language") or "ar")
    return (
        f"Create slide {slide.get('slide', 1)} of {total_slides} for a cohesive carousel.\n\n"
        f"BRAND CONTEXT:\n{_brand_visual_context(brand)}\n\n"
        f"CONTENT LANGUAGE: {lang}\n"
        f"EXACT VISIBLE TEXT TO RENDER ON THIS SLIDE: {text}\n"
        f"SLIDE ROLE: {slide.get('role', 'content')}\n"
        f"TOPIC: {idea.get('topic', '')}\n"
        f"VISUAL DIRECTION: {_clean_native_visual_direction(slide.get('image_prompt', ''))}\n\n"
        "Render the exact visible text natively inside the image. Make it large, readable, and polished. "
        + " ".join(language_prompt_rules(idea.get("text_language") or idea.get("content_language")))
        + " "
        "Keep the carousel style consistent across slides: same typography logic, spacing, colors, and visual rhythm. "
        f"The slide may use a subtle {div['color_name']} accent, but should primarily follow the business brand identity. "
        "Do not add extra text beyond the exact visible text unless it is purely decorative and unreadable."
    )


def _generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    extra_images: list | None = None,
    allow_imagen_fallback: bool = True,
    route: AiRoute = AiRoute.image_generation,
    language: str = "en",
    visible_text: str | None = None,
) -> Optional[bytes]:
    """Generate a single image via Gemini image model (falls back to Imagen 4). Returns PNG bytes or None."""
    if not settings.google_api_key:
        return None
    decision = resolve_ai_route(
        route,
        request_context={
            "language": language,
            "visible_text": bool(visible_text),
            "text_rendering_mode": "native_text_design" if visible_text else "text_free_background",
        },
    )

    # Primary: Gemini image generation (better multilingual instruction following)
    try:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=settings.google_api_key)
        contents = [prompt]
        if extra_images:
            contents.extend(extra_images)
        resp = client.models.generate_content(
            model=decision.model,
            contents=contents,
            config=gtypes.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=gtypes.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        for candidate in (resp.candidates or []):
            for part in (candidate.content.parts or []):
                if hasattr(part, "inline_data") and part.inline_data:
                    return part.inline_data.data
    except Exception as e:
        log.warning("Gemini image generation failed (%s): %s", settings.google_image_model, e)

    if not allow_imagen_fallback:
        log.warning(
            "Skipping Imagen fallback because this image requires native text rendering (%s, aspect=%s)",
            settings.google_image_model,
            aspect_ratio,
        )
        return None

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
                aspect_ratio=aspect_ratio,
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
    return store_post_media(post_id, filename, media_bytes, content_type).url


def _save_image(image_bytes: bytes, post_id: str, slide_idx: int = 0) -> str:
    return _save_media(image_bytes, post_id, f"{post_id}_{slide_idx}.png", "image/png")


def _save_image_variant(image_bytes: bytes, post_id: str, platform: str, slide_idx: int = 0) -> str:
    return _save_media(image_bytes, post_id, f"{post_id}_{platform}_{slide_idx}.png", "image/png")


def _save_video(video_bytes: bytes, post_id: str) -> str:
    return _save_media(video_bytes, post_id, f"{post_id}.mp4", "video/mp4")


def _output_ai_metadata(idea: dict, decision: AiRouteDecision, media_urls: list[str] | None = None) -> dict:
    metadata = dict(idea or {})
    language = metadata.get("content_language") or metadata.get("text_language") or decision.language_policy["target_language"]
    text_mode = decision.media_policy.get("text_rendering_mode") if decision.media_policy else "not_applicable"
    if decision.route in {AiRoute.image_generation.value, AiRoute.carousel_generation.value}:
        text_mode = text_rendering_mode_for_media(
            language,
            metadata.get("text_rendering_mode") or text_mode,
            has_visible_text=bool(metadata.get("visible_text") or metadata.get("image_title_ar")),
        )
    metadata.update(
        {
            "ai_route": decision.route,
            "provider": decision.provider,
            "model": decision.model,
            "model_version": decision.model_version,
            "prompt_policy_version": decision.prompt_policy_version or PromptPolicyVersion,
            "language": language,
            "text_rendering_mode": text_mode,
            "media_backend": media_backend_for_urls(media_urls),
            "public_url_ready": public_url_ready(media_urls),
            "fallback_chain_used": [],
            "cost_estimate": decision.cost_estimate,
            "usage_event_id": metadata.get("usage_event_id") or "usage_event_pending",
            "safety_status": metadata.get("safety_status") or "not_checked",
        }
    )
    return metadata


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


def _target_platforms(idea: dict) -> list[str]:
    request = idea.get("generation_request") or {}
    destination = str(request.get("destination") or "").lower()
    if request.get("platform_variants") is True or destination in {"ads", "both", "publish"}:
        return ["instagram", "facebook"]
    return ["instagram"]


def _quick_required_size_ids(idea: dict) -> set[str]:
    brief = ((idea.get("generation_request") or {}).get("creative_brief") or {})
    required_sizes = brief.get("required_sizes") if isinstance(brief, dict) else None
    ids = required_sizes.get("ids") if isinstance(required_sizes, dict) else []
    return {str(size_id) for size_id in ids or []}


def _add_variant_spec(specs: list[tuple[str, str, str]], key: str, aspect: str, label: str) -> None:
    if not any(existing_key == key for existing_key, _aspect, _label in specs):
        specs.append((key, aspect, label))


def _image_variant_specs(idea: dict) -> list[tuple[str, str, str]]:
    ids = _quick_required_size_ids(idea)
    specs: list[tuple[str, str, str]] = []
    if not ids:
        for platform in _target_platforms(idea):
            _add_variant_spec(
                specs,
                platform,
                "16:9" if platform == "facebook" else "4:5",
                f"{platform} social placement",
            )
        return specs

    if "image_all" in ids:
        _add_variant_spec(specs, "instagram", "4:5", "Instagram feed portrait 4:5")
        _add_variant_spec(specs, "meta_square_1_1", "1:1", "Meta square ad 1:1")
        _add_variant_spec(specs, "story_9_16", "9:16", "Vertical story placement 9:16")
        _add_variant_spec(specs, "facebook", "16:9", "Wide social/ad placement 16:9")
        _add_variant_spec(specs, "google_landscape_1_91_1", "16:9", "Google Ads landscape responsive image")
    if "instagram_post_4_5" in ids:
        _add_variant_spec(specs, "instagram", "4:5", "Instagram feed portrait 4:5")
    if "meta_square_1_1" in ids:
        _add_variant_spec(specs, "meta_square_1_1", "1:1", "Meta square ad 1:1")
    if "vertical_story_9_16" in ids:
        _add_variant_spec(specs, "story_9_16", "9:16", "Vertical story placement 9:16")
    if "wide_16_9" in ids:
        _add_variant_spec(specs, "facebook", "16:9", "Wide social/ad placement 16:9")
    if "google_ads_all" in ids:
        _add_variant_spec(specs, "google_square_1_1", "1:1", "Google Ads square responsive image")
        _add_variant_spec(specs, "google_landscape_1_91_1", "16:9", "Google Ads landscape responsive image")
        _add_variant_spec(specs, "google_portrait_4_5", "4:5", "Google Ads portrait responsive image")
        _add_variant_spec(specs, "google_vertical_9_16", "9:16", "Google Ads vertical responsive image")
        _add_variant_spec(specs, "google_wide_16_9", "16:9", "Google Ads wide responsive image")
    return specs or [("instagram", "4:5", "Instagram feed portrait 4:5")]


def _video_variant_specs(idea: dict) -> list[tuple[str, str, str]]:
    ids = _quick_required_size_ids(idea)
    specs: list[tuple[str, str, str]] = []
    if "video_story_reel_9_16" in ids or "vertical_story_9_16" in ids:
        _add_variant_spec(specs, "video_story_reel_9_16", "9:16", "Vertical story/reel video")
    if "video_wide_16_9" in ids or "wide_16_9" in ids:
        _add_variant_spec(specs, "video_wide_16_9", "16:9", "Wide landscape video")
    return specs or [("video_story_reel_9_16", "9:16", "Vertical story/reel video")]


def _primary_variant_urls(platform_urls: dict[str, list[str]]) -> list[str]:
    for key in ("instagram", "video_story_reel_9_16", "facebook", "meta_square_1_1", "story_9_16"):
        urls = platform_urls.get(key) or []
        if urls:
            return urls
    for urls in platform_urls.values():
        if urls:
            return urls
    return []


def _generate_single_image_media(idea: dict, brand: dict) -> dict[str, list[bytes]]:
    title_ar = (idea.get("image_title_ar") or "").strip()
    visible_text = (idea.get("visible_text") or title_ar or "").strip()
    native_text = bool(visible_text and _native_text_allowed(idea))
    references = _load_reference_images(brand, _quick_reference_urls(idea)) if idea.get("include_logo", True) else _load_reference_images({}, _quick_reference_urls(idea))
    variant_specs = _image_variant_specs(idea)
    out: dict[str, list[bytes]] = {key: [] for key, _aspect, _label in variant_specs}

    for platform, aspect, label in variant_specs:
        platform_idea = {**idea, "aspect_ratio": aspect, "variant_key": platform, "variant_label": label}
        if native_text:
            prompt = _native_image_prompt(platform_idea, brand, visible_text)
            prompt += f"\n\nTARGET PLACEMENT: {label}. Compose specifically for {aspect}."
        else:
            prompt = _image_prompt(platform_idea)
            prompt += f"\n\nTARGET PLACEMENT: {label}. Compose specifically for {aspect}."

        if title_ar and not native_text:
            prompt += (
                "\n\nIMPORTANT: This image is a clean visual background. "
                "DO NOT render any text in the image. Leave the bottom 25-30% "
                "relatively clean and uncluttered. We will add title text in post-processing."
            )
        image_bytes = _generate_image(
            prompt,
            aspect,
            extra_images=references,
            allow_imagen_fallback=not native_text,
            route=AiRoute.image_generation,
            language=idea.get("content_language") or idea.get("text_language") or "en",
            visible_text=visible_text if native_text else "",
        )
        if image_bytes and title_ar and not native_text:
            try:
                image_bytes = _overlay_image_title(image_bytes, platform_idea, title_ar)
            except Exception as e:
                log.warning("Image title overlay failed: %s", e)
        if image_bytes:
            out[platform].append(image_bytes)
    return out


def _generate_carousel_media(idea: dict, brand: dict) -> dict[str, list[bytes]]:
    from PIL import Image

    slides = idea.get("carousel_slides") or []
    references = _load_reference_images(brand, _quick_reference_urls(idea)) if idea.get("include_logo", True) else _load_reference_images({}, _quick_reference_urls(idea))
    native_text = _native_text_allowed(idea)
    variant_specs = _image_variant_specs(idea)
    out: dict[str, list[bytes]] = {key: [] for key, _aspect, _label in variant_specs}
    previous_by_variant: dict[str, object] = {}

    for idx, slide in enumerate(slides, start=1):
        title_ar = (slide.get("title_ar") or "").strip()
        for variant_key, base_aspect, label in variant_specs:
            aspect = "1:1" if variant_key == "facebook" and idx > 1 else base_aspect
            variant_idea = {**idea, "aspect_ratio": aspect, "variant_key": variant_key, "variant_label": label}
            if native_text:
                prompt = _native_slide_prompt(variant_idea, slide, len(slides), brand)
                prompt += f"\n\nTARGET PLACEMENT: {label}. Aspect ratio {aspect}."
            else:
                prompt = _slide_prompt(variant_idea, slide, len(slides))
                prompt += (
                    "\n\nIMPORTANT: This image is a clean visual background. "
                    "DO NOT render any text, letters, words, captions, or readable signs in the image. "
                    "Leave the bottom 25-30% of the composition relatively clean and uncluttered. "
                    "We will add title text in post-processing."
                    f"\n\nTARGET PLACEMENT: {label}. Aspect ratio {aspect}."
                )
            extras = list(references)
            previous = previous_by_variant.get(variant_key)
            if previous is not None:
                extras.append(previous)
                prompt += (
                    "\n\nThe previous slide for this placement is provided as a visual style reference. "
                    "Match its color grading, lighting, composition style, and overall aesthetic."
                )
            slide_bytes = _generate_image(
                prompt,
                aspect,
                extra_images=extras,
                allow_imagen_fallback=not native_text,
                route=AiRoute.carousel_generation,
                language=idea.get("content_language") or idea.get("text_language") or "en",
                visible_text=slide.get("visible_text") if native_text else "",
            )
            if slide_bytes and title_ar and not native_text:
                try:
                    slide_bytes = _overlay_image_title(
                        slide_bytes,
                        variant_idea,
                        title_ar,
                        slide_number=idx,
                        total_slides=len(slides),
                        role=slide.get("role", "content"),
                    )
                except Exception as e:
                    log.warning("Carousel title overlay failed for %s: %s", variant_key, e)
            if slide_bytes:
                out[variant_key].append(slide_bytes)
                try:
                    previous_by_variant[variant_key] = Image.open(BytesIO(slide_bytes))
                except Exception:
                    previous_by_variant[variant_key] = None
    return out


def _generate_video_media(idea: dict, brand: dict) -> Optional[bytes]:
    from ..engine.video_generator import generate_video

    out_dir = STATIC_DIR / f"video_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        video_path, _cost = generate_video(idea, out_dir, brand=brand)
        return Path(video_path).read_bytes()
    finally:
        for path in sorted(out_dir.glob("*"), reverse=True):
            path.unlink(missing_ok=True)
        out_dir.rmdir()


def _language_counts(languages: list[str], count: int) -> list[tuple[str, int]]:
    clean_languages = [lang for lang in languages if lang]
    if not clean_languages:
        clean_languages = ["ar"]
    count = max(1, count)
    selected = clean_languages[:count]
    if len(selected) >= count:
        return [(lang, 1) for lang in selected]
    base = count // len(selected)
    extra = count % len(selected)
    return [(lang, base + (1 if idx < extra else 0)) for idx, lang in enumerate(selected)]


def _emit_progress(callback: Optional[ProgressCallback], **event):
    if callback:
        callback(event)


async def _flush_progress() -> None:
    # The media providers are called through synchronous SDK paths in this worker.
    # Give the event loop a tick so queued progress writes reach the database
    # before the next long blocking generation call starts.
    await asyncio.sleep(0)


async def generate_content_for_suite(
    suite_id: str,
    db: AsyncSession,
    count: int = 3,
    options: Optional[dict] = None,
    progress: Optional[ProgressCallback] = None,
) -> list[str]:
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
    options = options or {}
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
        _emit_progress(progress, stage="blocked", message="Suite billing is frozen.", percent=100)
        return []
    await db.commit()

    mode = options.get("mode")
    content_type = (options.get("content_type") or "mixed").strip().lower()
    if mode == "quick" and content_type == "mixed":
        count = 3
    elif mode == "quick":
        count = max(1, count)
    elif mode == "set":
        count = max(count, 3)
    count = max(1, min(count, 3))

    log.info("Generating %d ideas for suite %s…", count, suite_id)
    _emit_progress(
        progress,
        status="running",
        stage="ideas",
        message=f"Generating {count} content idea{'s' if count != 1 else ''}.",
        progress=15,
    )
    await _flush_progress()
    audience_languages = brand.get("audience_languages") or ["ar"]
    if not audience_languages:
        audience_languages = ["ar"]
    if mode == "quick" and content_type == "mixed":
        audience_languages = audience_languages[:1]

    all_ideas = []
    lang_jobs = _language_counts(audience_languages, count)
    for lang_idx, (lang_code, lang_count) in enumerate(lang_jobs, start=1):
        _emit_progress(
            progress,
            status="running",
            stage="ideas",
            message=f"Writing ideas in {lang_code} ({lang_idx}/{len(lang_jobs)}).",
            progress=15 + int(20 * (lang_idx - 1) / max(1, len(lang_jobs))),
        )
        await _flush_progress()
        lang_ideas = _generate_ideas(
            brand,
            count=lang_count,
            recent_topics=recent_topics,
            strategy=strategy,
            language=lang_code,
            options=options,
        )
        for idea in lang_ideas:
            idea["content_language"] = lang_code
        all_ideas.extend(lang_ideas)
    ideas = all_ideas

    image_count = 0
    generated_video_count = 0
    total_ideas = max(1, len(ideas))
    for idx, idea in enumerate(ideas, start=1):
        fmt_str = idea.get("format", "image")
        fmt = PostFormat.carousel if fmt_str == "carousel" else (
            PostFormat.video if fmt_str == "video" else PostFormat.image
        )
        post_id = str(uuid.uuid4())
        media_urls: list[str] = []
        route = (
            AiRoute.carousel_generation
            if fmt == PostFormat.carousel
            else AiRoute.video_generation
            if fmt == PostFormat.video
            else AiRoute.image_generation
        )
        decision = resolve_ai_route(
            route,
            tenant_context={"language": idea.get("content_language")},
            request_context={
                "language": idea.get("content_language"),
                "visible_text": bool(idea.get("visible_text") or idea.get("image_title_ar")),
                "text_rendering_mode": idea.get("text_rendering_mode"),
                "slide_count": len(idea.get("carousel_slides") or []),
                "model_tier": (idea.get("generation_request") or {}).get("model_tier"),
            },
        )

        # Generate image(s) before opening a DB transaction. Image generation can
        # take a while; holding a DB connection here exhausts Railway's pool.
        try:
            _emit_progress(
                progress,
                status="running",
                stage="media",
                message=f"Generating media {idx}/{total_ideas}.",
                progress=40 + int(45 * (idx - 1) / total_ideas),
            )
            await _flush_progress()
            if fmt == PostFormat.image:
                variants = _generate_single_image_media(idea, brand)
                platform_urls: dict[str, list[str]] = {}
                for platform, images in variants.items():
                    platform_urls[platform] = [
                        _save_image_variant(img_bytes, post_id, platform, i)
                        for i, img_bytes in enumerate(images)
                    ]
                media_urls = _primary_variant_urls(platform_urls)
                idea["platform_media"] = platform_urls
                idea["media_variants"] = {key: {"urls": urls} for key, urls in platform_urls.items()}
                image_count += sum(len(images) for images in variants.values())

            elif fmt == PostFormat.carousel:
                variants = _generate_carousel_media(idea, brand)
                platform_urls = {}
                for platform, images in variants.items():
                    platform_urls[platform] = [
                        _save_image_variant(img_bytes, post_id, platform, i)
                        for i, img_bytes in enumerate(images)
                    ]
                media_urls = _primary_variant_urls(platform_urls)
                idea["platform_media"] = platform_urls
                idea["media_variants"] = {key: {"urls": urls} for key, urls in platform_urls.items()}
                image_count += sum(len(images) for images in variants.values())

            elif fmt == PostFormat.video:
                platform_urls = {}
                for variant_key, aspect, label in _video_variant_specs(idea):
                    video_idea = {**idea, "aspect_ratio": aspect, "variant_key": variant_key, "variant_label": label}
                    video_bytes = _generate_video_media(video_idea, brand)
                    if video_bytes:
                        platform_urls[variant_key] = [
                            _save_media(video_bytes, post_id, f"{post_id}_{variant_key}.mp4", "video/mp4")
                        ]
                        generated_video_count += 1
                media_urls = _primary_variant_urls(platform_urls)
                idea["platform_media"] = platform_urls
                idea["media_variants"] = {key: {"urls": urls} for key, urls in platform_urls.items()}
        except Exception as e:
            log.warning("Media generation for post %s failed: %s", post_id, e)
            idea["media_generation_failed"] = True
            idea["media_error"] = "media_generation_failed"

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
        post.ai_metadata = _output_ai_metadata(idea, decision, media_urls)
        db.add(post)
        post_ids.append(post.id)

    await db.commit()
    _emit_progress(
        progress,
        status="running",
        stage="saving",
        message="Saving generated content.",
        progress=90,
    )
    await _flush_progress()
    await record_usage(suite_id, "llm_idea_gen", COSTS["llm_idea_gen"] * count, db)
    if image_count:
        await record_usage(suite_id, "image_gen", COSTS["image_gen"] * image_count, db)
    if generated_video_count:
        await record_usage(suite_id, "video_gen_fast", COSTS["video_gen_fast"] * generated_video_count, db)
    log.info("Created %d posts for suite %s", len(post_ids), suite_id)
    return post_ids
