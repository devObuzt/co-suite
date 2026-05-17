"""AI-powered brand extraction from multiple sources."""
import json
import logging
import re
from typing import Optional

import anthropic

from ..core.config import settings
from .multi_scraper import gather_all_sources

log = logging.getLogger(__name__)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if present
    if "```" in raw:
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        raw = raw.strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fallback: extract first JSON object from mixed text
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            log.warning("_parse_json: could not parse JSON from model output: %.200s", raw)
    else:
        log.warning("_parse_json: no JSON found in model output: %.200s", raw)
    return {}


def _build_sources_context(intel: dict) -> str:
    """Format the gathered intelligence into a readable block for Claude."""
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
) -> dict:
    """Main entry point: gather from all URLs + search, then extract with Claude."""
    intel = await gather_all_sources(urls, business_name)
    context = _build_sources_context(intel)

    if not context.strip():
        return await suggest_brand_identity(business_name or "Unknown Business", "", "")

    prompt = EXTRACTION_PROMPT.format(
        context=context,
        name_hint=business_name or "(derive from the data)",
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    return _parse_json(raw)


# Keep for backward compat (single URL path still works)
async def extract_brand_from_url(url: str, business_name: Optional[str] = None) -> dict:
    return await extract_brand_from_sources([url], business_name)


async def suggest_brand_identity(business_name: str, industry: str, description: str) -> dict:
    """When no URLs are provided, AI suggests brand identity from scratch."""
    prompt = f"""You are a brand strategist. Suggest a complete brand identity for this business.

Business name: {business_name}
Industry: {industry}
Description: {description}

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

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(message.content[0].text)
