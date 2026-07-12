"""Social IDEAS generator (not finished content).

Milestone-2 of the idea-selection redesign. Given a suite + a period (e.g.
"2026-08"), it runs the research phase (occasions + market, cached), then asks
an LLM for 2×target IDEAS — each with a title, short description, an illustrative
client story, and a set of "how to apply" digital assets with a balanced
recommended ("middle") subset preselected. It keeps the objective-type concept
(attraction/trust/sales) and never raises: on failure it returns templated
fallback ideas so the gallery always has content.

Kept intentionally separate from the existing `generate_social_content_work_plan`
so the live marketing-plan flow is untouched while the new experience is built.
"""
import json
import logging

from ..core.llm_client import call_text_ai
from .marketing_plan_generator import (
    _dict,
    _social_content_plan_context,
    infer_plan_language,
    suite_research_payload,
)
from .market_research import get_market_research
from .occasion_match import relevant_occasions
from .occasions_service import get_occasions
from .research_cache import normalize_country, normalize_language

log = logging.getLogger(__name__)

OBJECTIVE_TYPES = ("attraction", "trust", "sales")
APPLY_ASSET_TYPES = (
    "ugc", "talking_head", "image", "banner", "carousel", "ai_video",
    "landing_page", "webinar", "website", "app", "digital_asset_other",
)
DEFAULT_TARGET = 12
IDEAS_MAX_TOKENS = 4000
IDEAS_TIMEOUT_SECONDS = 150


def _extract_json(raw: str) -> dict:
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    return {}
    return {}


def normalize_idea(raw, index: int = 0):
    """Coerce one raw LLM idea into the stored idea shape, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    objective = raw.get("objective_type")
    if objective not in OBJECTIVE_TYPES:
        objective = "attraction"

    assets = []
    seen = set()
    for a in (raw.get("apply_assets") or []):
        if isinstance(a, dict):
            asset_type, recommended = a.get("asset_type"), bool(a.get("recommended"))
        elif isinstance(a, str):
            asset_type, recommended = a, False
        else:
            continue
        if asset_type in APPLY_ASSET_TYPES and asset_type not in seen:
            seen.add(asset_type)
            assets.append({"asset_type": asset_type, "recommended": recommended})
    if not assets:
        assets = [{"asset_type": "image", "recommended": True}]
    if not any(a["recommended"] for a in assets):
        assets[0]["recommended"] = True  # guarantee a "middle" default exists

    story = raw.get("client_story")
    if isinstance(story, str):
        story = {"text": story, "example": ""}
    elif not isinstance(story, dict):
        story = {}
    client_story = {
        "text": str(story.get("text") or "").strip(),
        "example": str(story.get("example") or "").strip(),
        "is_illustrative": True,
    }

    occ = raw.get("occasion_ref")
    occasion_ref = None
    if isinstance(occ, dict) and occ.get("title"):
        occasion_ref = {"title": str(occ["title"]), "date_or_window": str(occ.get("date_or_window") or "")}
    elif isinstance(occ, str) and occ.strip():
        occasion_ref = {"title": occ.strip(), "date_or_window": ""}

    return {
        "id": str(raw.get("id") or f"idea-{index}"),
        "objective_type": objective,
        "title": title[:160],
        "short_description": str(raw.get("short_description") or raw.get("description") or "").strip()[:400],
        "occasion_ref": occasion_ref,
        "client_story": client_story,
        "apply_assets": assets,
        "user_notes": "",
        "selected": False,
    }


def parse_ideas(raw_text: str) -> list[dict]:
    data = _extract_json(raw_text)
    out = []
    for i, item in enumerate(data.get("ideas") or []):
        idea = normalize_idea(item, i)
        if idea:
            out.append(idea)
    return out


def fallback_ideas(target_count: int, occasions: list[dict], language: str) -> list[dict]:
    """Templated ideas so the gallery is never empty when the LLM fails."""
    ideas = []
    for i in range(max(1, target_count)):
        occ = occasions[i] if i < len(occasions) else None
        objective = OBJECTIVE_TYPES[i % 3]
        ideas.append(normalize_idea({
            "id": f"fallback-{i}",
            "objective_type": objective,
            "title": (occ.get("title") if occ else f"فكرة محتوى #{i + 1}"),
            "short_description": "فكرة مقترحة — عدّلها أو استبدلها.",
            "occasion_ref": ({"title": occ.get("title"), "date_or_window": occ.get("date_or_window", "")} if occ else None),
            "client_story": {"text": "قصة نجاح توضيحية.", "example": "مثال توضيحي — عدّله لاحقاً."},
            "apply_assets": [{"asset_type": "talking_head", "recommended": True},
                             {"asset_type": "image", "recommended": True},
                             {"asset_type": "carousel", "recommended": False}],
        }, i))
    return ideas


def build_ideas_prompt(context: dict, occasions: list[dict], market: dict, target_count: int, period: str, language: str) -> str:
    occ_lines = "\n".join(
        f"- {o.get('title')} ({o.get('type')}, {o.get('date_or_window', '')})" for o in occasions
    ) or "(none — use evergreen ideas)"
    asset_list = ", ".join(APPLY_ASSET_TYPES)
    over = target_count * 2
    return (
        f"You are a senior social media strategist for a marketing agency. Generate exactly {over} social media "
        f"CONTENT IDEAS (NOT finished posts/captions) for the brand below, for the period {period}. "
        f"Output language: {context.get('audience_language')} (dialect: {context.get('dialect') or 'natural'}).\n\n"
        f"BRAND: {json.dumps({k: context.get(k) for k in ('name','products_services','target_audience','marketing_offer','marketing_message')}, ensure_ascii=False)[:2500]}\n\n"
        f"RELEVANT OCCASIONS this period (tie some ideas to these; the rest evergreen):\n{occ_lines}\n\n"
        f"MARKET CONTEXT: {json.dumps(market, ensure_ascii=False)[:800]}\n\n"
        f"RULES:\n"
        f"- Each item is an IDEA + how to apply it, NOT a ready caption or script.\n"
        f"- Keep the objective mix ~70% attraction, ~20% trust, ~10% sales across the {over} ideas.\n"
        f"- Tie strongly-relevant occasions to at least one idea each (set occasion_ref); the rest evergreen.\n"
        f"- For each idea recommend a BALANCED 'middle' set of assets (mark recommended=true) — not the cheapest single asset, not everything. Choose asset_type ONLY from: {asset_list}.\n"
        f"- client_story is an ILLUSTRATIVE example (no fabricated real metrics presented as fact).\n\n"
        f'Return ONLY JSON: {{"ideas":[{{"objective_type":"attraction|trust|sales","title":"...",'
        f'"short_description":"1-2 sentences","occasion_ref":{{"title":"...","date_or_window":"..."}}|null,'
        f'"client_story":{{"text":"...","example":"..."}},'
        f'"apply_assets":[{{"asset_type":"one of the allowed types","recommended":true|false}}]}}]}}'
    )


async def generate_social_ideas(db, suite, *, period: str, target_count: int | None = None, requested_language: str | None = None) -> dict:
    """Research + generate the idea candidates for one period. Never raises."""
    warnings: list[str] = []
    language = infer_plan_language(suite, requested_language)
    target = int(target_count or DEFAULT_TARGET)
    try:
        payload = suite_research_payload(suite)
        context = _social_content_plan_context(payload, language)
        brand = _dict(payload.get("brand"))
        country = context.get("target_audience", {}).get("location") or brand.get("location") or "global"

        occasions = await get_occasions(db, country=country, language=language, period=period)
        if not occasions:
            warnings.append("occasions_unavailable")
        relevant = relevant_occasions(occasions, brand)
        market = await get_market_research(db, country=country, language=language, brand=brand)

        raw = await call_text_ai(
            max_tokens=IDEAS_MAX_TOKENS,
            messages=[{"role": "user", "content": build_ideas_prompt(context, relevant, market, target, period, language)}],
            system="You are a senior social media strategist. Return valid JSON only.",
            timeout=IDEAS_TIMEOUT_SECONDS,
        )
        candidates = parse_ideas(raw)
        if len(candidates) < target:
            warnings.append("ideas_underfilled")
            candidates = candidates + fallback_ideas(target * 2 - len(candidates), relevant, language)
    except Exception:
        log.exception("social ideas generation failed for suite %s", getattr(suite, "id", "?"))
        warnings.append("generation_failed")
        relevant = []
        candidates = fallback_ideas(target * 2, [], language)

    return {
        "version": "social_ideas_v1",
        "language": language,
        "period": period,
        "target_count": target,
        "occasions": relevant,
        "candidates": candidates,
        "selected_ids": [],
        "warnings": warnings,
    }
