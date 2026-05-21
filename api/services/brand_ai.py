"""AI-powered brand extraction from multiple sources."""
import json
import logging
import re
from typing import Optional

from ..core.config import settings
from ..core.llm_client import call_text_ai
from .multi_scraper import gather_all_sources

log = logging.getLogger(__name__)

ONBOARDING_AI_PROVIDER = "openai"

LANGUAGE_NAMES = {
    "ar": "Arabic, natural Palestinian/local business Arabic",
    "he": "Hebrew",
    "en": "English",
    "ru": "Russian",
    "fr": "French",
    "es": "Spanish",
    "tr": "Turkish",
    "zh": "Chinese",
}


def _extract_json_object(text: str) -> str | None:
    """Extract the first complete JSON object using brace-balanced matching."""
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escape = 0, False, False
    for i, c in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if present
    if "```" in raw:
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        raw = raw.strip()
    # Try direct parse first (clean JSON response)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fallback: extract first balanced JSON object from mixed text
    candidate = _extract_json_object(raw)
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            log.warning("_parse_json: could not parse JSON from model output: %.200s", raw)
    else:
        log.warning("_parse_json: no JSON found in model output: %.200s", raw)
    return {}


def _build_sources_context(intel: dict) -> str:
    """Format the gathered intelligence into a readable block for onboarding AI."""
    lines = []

    for src in intel.get("sources", []):
        kind = src.get("type", "unknown")
        lines.append(f"\n=== Source: {kind.upper()} ===")

        if kind == "website":
            lines.append(f"URL: {src.get('url', '')}")
            lines.append(f"Title: {src.get('title', '')}")
            lines.append(f"Description: {src.get('description', '')}")
            lines.append(f"Keywords: {src.get('keywords', '')}")
            colors = src.get("colors", [])
            if colors:
                lines.append(f"Colors found in CSS: {', '.join(colors[:6])}")
            theme = src.get("theme_color")
            if theme:
                lines.append(f"Theme color (meta tag): {theme}")
            og_img = src.get("og_image")
            if og_img:
                lines.append(f"OG image URL: {og_img}")
            jsonld = src.get("jsonld", "")
            if jsonld.strip():
                lines.append(f"Structured data (JSON-LD): {jsonld[:800]}")
            body = src.get("body_text", "")
            if body:
                lines.append(f"Page text: {body[:1500]}")

        elif kind == "instagram":
            lines.append(f"Handle: @{src.get('handle', '')}")
            if src.get("full_name"):
                lines.append(f"Full name: {src['full_name']}")
            if src.get("bio"):
                lines.append(f"Bio: {src['bio']}")
            if src.get("followers"):
                lines.append(f"Followers: {src['followers']:,}")
            if src.get("following"):
                lines.append(f"Following: {src['following']:,}")
            if src.get("posts_count"):
                lines.append(f"Total posts: {src['posts_count']}")
            if src.get("website"):
                lines.append(f"Website in bio: {src['website']}")
            if src.get("is_business"):
                lines.append(f"Business account: yes")
            if src.get("business_category"):
                lines.append(f"Business category: {src['business_category']}")
            if src.get("business_email"):
                lines.append(f"Business email: {src['business_email']}")
            if src.get("business_phone"):
                lines.append(f"Business phone: {src['business_phone']}")
            if src.get("og_description"):
                lines.append(f"IG description: {src['og_description']}")
            # Hashtags reveal brand positioning and content themes
            tags = src.get("top_hashtags", [])
            if tags:
                lines.append(f"Most used hashtags ({len(tags)}): #{' #'.join(tags[:15])}")
            # Captions reveal tone, products, services, and audience
            captions = src.get("captions_sample", "")
            if captions:
                lines.append(f"\nRecent post captions (use these to understand tone, services, and content themes):\n{captions}")
            # Summarize post types
            posts = src.get("recent_posts", [])
            if posts:
                avg_likes = sum(p.get("likes", 0) for p in posts) / len(posts)
                avg_comments = sum(p.get("comments", 0) for p in posts) / len(posts)
                lines.append(f"\nPost performance: {len(posts)} recent posts, avg {avg_likes:.0f} likes, {avg_comments:.0f} comments")

        elif kind in ("facebook", "linkedin"):
            lines.append(f"URL: {src.get('url', '')}")
            if src.get("og_title"):
                lines.append(f"Title: {src['og_title']}")
            if src.get("og_description"):
                lines.append(f"Description: {src['og_description']}")
            if src.get("text"):
                lines.append(f"Page text: {src['text'][:800]}")

    snippets = intel.get("search_snippets", "")
    if snippets:
        lines.append("\n=== WEB SEARCH RESULTS ===")
        lines.append(snippets[:1500])

    return "\n".join(lines)


EXTRACTION_PROMPT = """You are a senior brand analyst and strategist. Your job is to extract a complete, accurate brand profile from the raw intelligence gathered from this business's online presence.

Be specific and factual — only state things that are actually supported by the data. Where data is missing, make a well-reasoned educated guess based on industry context, but mark it as "suggested".

OUTPUT LANGUAGE:
Write all user-facing values in {output_language}. This includes description, target_audience, tone, unique_value, how_they_help, esp, content_themes, competitors, missing_info, services, and products when translation is appropriate.
Keep brand names, URLs, handles, hashtags, and proper nouns in their original form.
Do not default to English unless the selected output language is English.
If the output language is Arabic, use natural local business Arabic, not stiff formal Arabic.
If the output language is Hebrew, use natural modern Hebrew suitable for business onboarding.

GATHERED INTELLIGENCE:
{context}

BUSINESS NAME HINT: {name_hint}

Extract and return ONLY a valid JSON object with this exact structure:

{{
  "name": "exact business name",
  "name_ar": "Arabic name if found, else null",
  "tagline": "their actual tagline, or a suggested one",
  "description": "2-4 sentence description of what they do, who they serve, and what makes them different",
  "industry": "specific industry (e.g. 'Digital Marketing Agency', 'Restaurant', 'Fashion Retail')",
  "location": "city, country if found",
  "founded": "year if found, else null",
  "services": ["list of actual services/offerings found"],
  "products": ["list of products if it's a product business"],
  "target_audience": "specific description of who they serve",
  "tone": "brand voice: professional / friendly / playful / luxury / bold / calm / etc.",
  "colors": {{
    "primary": "#hex — most dominant brand color found",
    "secondary": "#hex or null",
    "accent": "#hex or null",
    "source": "where these colors came from (css/meta/logo/inferred)"
  }},
  "logo_url": "direct URL to logo image if found, else null",
  "logo_description": "describe the logo if any info was found",
  "fonts": ["font names if found, else suggested fonts that fit the brand"],
  "social_links": {{
    "instagram": "full URL or null",
    "facebook": "full URL or null",
    "tiktok": "full URL or null",
    "linkedin": "full URL or null",
    "twitter": "full URL or null",
    "youtube": "full URL or null",
    "website": "main website URL or null"
  }},
  "competitors": ["2-4 known competitors in the same market"],
  "unique_value": "what makes this business different from competitors",
  "how_they_help": "the specific outcome or problem this business solves for clients (1-2 sentences)",
  "esp": "the emotional benefit the client feels after working with this business (1 sentence, e.g. 'they feel confident and in control')",
  "marketing_channels": ["channels they're active on based on evidence"],
  "content_themes": ["3-5 themes/topics this brand should post about"],
  "contact": {{
    "phone": "if found",
    "email": "if found",
    "address": "if found"
  }},
  "top_hashtags": ["actual hashtags they use on Instagram, in order of frequency"],
  "dialect": "language/dialect detected in captions (e.g. 'Palestinian Arabic', 'Gulf Arabic', 'MSA', 'Hebrew', 'English') or null",
  "missing_info": ["list of important brand elements that couldn't be found and the user should provide"]
}}

Rules:
- Colors: prefer CSS/theme-color found on their actual website. If not found, suggest colors that fit the industry and tone.
- services/products: only list things actually mentioned in website text, captions, or bio. Don't invent.
- tone: derive from how they write captions — are they formal, casual, humorous, inspirational? Quote style if possible.
- content_themes: extract directly from what their posts are actually about (not generic). Use caption topics.
- target_audience: infer from the content, hashtags, language used in captions, and business category.
- top_hashtags: include the hashtags they actually use — these help with future content generation.
- missing_info: be honest — list things like "logo file", "brand colors", "product catalog" if they weren't found.
- If Instagram captions are in Arabic, extract language/dialect used (e.g. "Palestinian Arabic", "Gulf Arabic", "MSA").
- how_they_help: infer from website copy, service descriptions, and social captions — what problem does this solve?
- esp: the emotional feeling the client gets — infer from testimonials, tone, and brand voice.
- Return ONLY the JSON object, no explanation."""


async def extract_brand_from_sources(
    urls: list[str],
    business_name: Optional[str] = None,
    user_language: str = "en",
    ai_provider: Optional[str] = None,
) -> dict:
    """Main entry point: gather from all URLs + search, then extract with OpenAI."""
    intel = await gather_all_sources(urls, business_name)
    context = _build_sources_context(intel)

    if not context.strip():
        return await suggest_brand_identity(
            business_name or "Unknown Business",
            "",
            "",
            user_language=user_language,
            ai_provider=ai_provider,
        )

    prompt = EXTRACTION_PROMPT.format(
        context=context,
        name_hint=business_name or "(derive from the data)",
        output_language=LANGUAGE_NAMES.get(user_language, user_language or "English"),
    )

    provider = ONBOARDING_AI_PROVIDER
    raw = await call_text_ai(
        provider=provider,
        model=settings.openai_text_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(raw)


# Keep for backward compat (single URL path still works)
async def extract_brand_from_url(url: str, business_name: Optional[str] = None) -> dict:
    return await extract_brand_from_sources([url], business_name)


async def suggest_brand_identity(
    business_name: str,
    industry: str,
    description: str,
    user_language: str = "en",
    ai_provider: Optional[str] = None,
) -> dict:
    """When no URLs are provided, AI suggests brand identity from scratch."""
    prompt = f"""You are a brand strategist. Suggest a complete brand identity for this business.

Business name: {business_name}
Industry: {industry}
Description: {description}
Output language for all user-facing values: {LANGUAGE_NAMES.get(user_language, user_language or "English")}

Return ONLY a valid JSON object matching this structure exactly:
{{
  "name": "{business_name}",
  "tagline": "suggested tagline",
  "description": "suggested brand description",
  "industry": "{industry}",
  "services": [],
  "products": [],
  "target_audience": "suggested target audience",
  "tone": "suggested brand voice",
  "colors": {{
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "source": "suggested"
  }},
  "logo_description": "logo concept suggestion",
  "fonts": ["Font 1", "Font 2"],
  "competitors": [],
  "unique_value": "",
  "content_themes": [],
  "social_links": {{"instagram": null, "facebook": null, "website": null}},
  "missing_info": ["logo", "brand colors", "actual services list"]
}}"""

    provider = ONBOARDING_AI_PROVIDER
    raw = await call_text_ai(
        provider=provider,
        model=settings.openai_text_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(raw)


async def suggest_brand_assets(brand: dict, generate: list[str], user_language: str = "en") -> dict:
    """Generate missing brand elements (colors, fonts, logo) using AI."""
    result = {}

    if "colors" in generate:
        prompt = (
            f"Brand: {brand.get('name', 'Unknown')}, "
            f"Industry: {brand.get('industry', '')}, "
            f"Tone: {brand.get('tone', 'professional')}.\n"
            "Suggest a professional color palette. "
            "Return ONLY valid JSON: "
            '{"primary":"#hex","secondary":"#hex","accent":"#hex","reasoning":"one sentence"}'
        )
        try:
            raw = await call_text_ai(
                provider=ONBOARDING_AI_PROVIDER,
                model=settings.openai_fast_model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            palette = _parse_json(raw)
            if palette.get("primary"):
                result["color_palette"] = palette
                result["colors"] = {
                    "primary": palette.get("primary"),
                    "secondary": palette.get("secondary"),
                    "accent": palette.get("accent"),
                    "source": "ai-generated",
                }
        except Exception as e:
            log.warning("Color generation failed: %s", e)

    if "fonts" in generate:
        lang_note = ""
        if user_language == "ar":
            lang_note = "IMPORTANT: Suggest Arabic-compatible Google Fonts (e.g. Cairo, Tajawal, Noto Kufi Arabic, Almarai). "
        elif user_language == "he":
            lang_note = "IMPORTANT: Suggest Hebrew-compatible Google Fonts (e.g. Rubik, Assistant, Heebo, Frank Ruhl Libre). "
        prompt = (
            f"Brand: {brand.get('name', 'Unknown')}, "
            f"Tone: {brand.get('tone', 'professional')}.\n"
            f"{lang_note}"
            "Suggest 2 Google Font names that fit this brand. "
            'Return ONLY valid JSON: {"fonts":["FontName1","FontName2"]}'
        )
        try:
            raw = await call_text_ai(
                provider=ONBOARDING_AI_PROVIDER,
                model=settings.openai_fast_model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _parse_json(raw)
            if data.get("fonts"):
                result["font_suggestions"] = data["fonts"]
                result["fonts"] = data["fonts"]
        except Exception as e:
            log.warning("Font generation failed: %s", e)

    if "logo" in generate:
        try:
            from .content_generator import _generate_image
            from ..core.config import settings as _settings
            import boto3 as _boto3
            import uuid as _uuid
            from pathlib import Path as _Path
            from PIL import Image as _PILImage, ImageDraw as _ImageDraw, ImageFont as _IFont
            import io as _io

            _FONTS_DIR = _Path(__file__).parent.parent / "fonts"
            _FONT_FOR_LANG = {
                "ar": "Cairo-Regular.ttf",
                "he": "NotoSansHebrew-Regular.ttf",
            }
            _DEFAULT_FONT = "Inter-Regular.ttf"

            logo_style = brand.get("logo_style", "icon_only")
            biz_name = brand.get("name", "")
            industry = brand.get("industry", "")
            tone = brand.get("tone", "professional")
            primary_color = (brand.get("colors") or {}).get("primary", "#4f46e5")

            # Always ask Imagen for a pure abstract icon — never ask it to render text.
            # Describe positively what we want (style, mood, shape) so Imagen stays
            # focused on iconography and doesn't drift towards letterforms.
            icon_prompt = (
                f"Minimalist flat vector icon mark for a {industry} brand. "
                f"Pure abstract geometric symbol, completely text-free iconographic mark. "
                f"Style: {tone}, modern, clean, professional. "
                f"Dominant color: {primary_color}. Solid white background. "
                f"In the style of Airbnb, Spotify, Dropbox or Apple — a single clean abstract icon, "
                f"no letterforms, no typography, no words, no characters of any kind anywhere."
            )
            png_bytes = _generate_image(icon_prompt, "1:1")

            if not png_bytes:
                log.warning("Imagen returned no bytes for logo")
            else:
                # For with_name / initials: overlay text using Pillow + bundled fonts.
                # This guarantees correct rendering for Arabic, Hebrew, and any script —
                # Imagen cannot reliably render non-Latin text.
                if logo_style in ("with_name", "initials") and biz_name:
                    user_lang = brand.get("user_language", "en")
                    font_file = _FONT_FOR_LANG.get(user_lang, _DEFAULT_FONT)
                    font_path = _FONTS_DIR / font_file

                    if logo_style == "initials":
                        words = biz_name.split()
                        text = "".join(w[0] for w in words[:2]) if len(words) > 1 else biz_name[:2]
                    else:
                        text = biz_name

                    if font_path.exists() and text:
                        img = _PILImage.open(_io.BytesIO(png_bytes)).convert("RGBA")
                        w, h = img.size

                        # Expand canvas downward to hold the text
                        text_zone_h = int(h * 0.28)
                        canvas = _PILImage.new("RGBA", (w, h + text_zone_h), (255, 255, 255, 255))
                        canvas.paste(img, (0, 0))
                        draw = _ImageDraw.Draw(canvas)

                        # Auto-size font to fit within 85% of icon width
                        font_size = 56
                        for _ in range(12):
                            font = _IFont.truetype(str(font_path), font_size)
                            bbox = draw.textbbox((0, 0), text, font=font)
                            if (bbox[2] - bbox[0]) <= w * 0.85:
                                break
                            font_size = int(font_size * 0.82)

                        font = _IFont.truetype(str(font_path), font_size)
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_w = bbox[2] - bbox[0]
                        text_h = bbox[3] - bbox[1]
                        x = (w - text_w) // 2
                        y = h + (text_zone_h - text_h) // 2

                        try:
                            r = int(primary_color[1:3], 16)
                            g = int(primary_color[3:5], 16)
                            b = int(primary_color[5:7], 16)
                        except Exception:
                            r, g, b = 79, 70, 229

                        draw.text((x, y), text, font=font, fill=(r, g, b, 255))
                        out = _io.BytesIO()
                        canvas.convert("RGB").save(out, format="PNG")
                        png_bytes = out.getvalue()
                    else:
                        log.warning("Font %s not found — skipping text overlay", font_path)

                if _settings.r2_account_id and _settings.r2_bucket_name:
                    s3 = _boto3.client(
                        "s3",
                        endpoint_url=f"https://{_settings.r2_account_id}.r2.cloudflarestorage.com",
                        aws_access_key_id=_settings.r2_access_key_id,
                        aws_secret_access_key=_settings.r2_secret_access_key,
                    )
                    key = f"logos/{_uuid.uuid4()}.png"
                    s3.put_object(Bucket=_settings.r2_bucket_name, Key=key, Body=png_bytes, ContentType="image/png")
                    logo_url = f"{_settings.r2_public_url}/{key}"
                    result["logo_url"] = logo_url
                    result["logo_source"] = "ai-generated"
                    result["brand_generated"] = {"logo_url": logo_url, "logo_style": logo_style}
        except Exception as e:
            log.warning("Logo generation failed: %s", e)

    return result
