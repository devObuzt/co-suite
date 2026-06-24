"""Marketing plan deck API."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
import json
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.llm_client import call_text_ai
from ..core.security import get_current_user, hash_password, verify_password
from ..models.generation_job import GenerationJob, GenerationJobType
from ..models.suite import Suite
from ..models.user import User
from ..services.generation_jobs import ACTIVE_STATUSES, create_job, serialize_job
from ..services.marketing_plan_generator import (
    infer_plan_language,
    normalize_marketing_action_plan,
    normalize_marketing_intelligence,
    suite_research_payload,
)

router = APIRouter(tags=["marketing-plans"])

GENERATED_MARKETING_PLAN_KEYS = (
    "marketing_plan_deck",
    "marketing_intelligence",
    "marketing_action_plan",
)


class GenerateMarketingPlanRequest(BaseModel):
    language: str | None = None
    near_term_focus: str | None = Field(default=None, max_length=2000)
    upcoming_campaigns: list[str] = Field(default_factory=list, max_length=12)
    planning_notes: str | None = Field(default=None, max_length=2000)


class MarketingStageRequest(GenerateMarketingPlanRequest):
    existing_ids: list[str] = Field(default_factory=list, max_length=200)
    existing_values: list[str] = Field(default_factory=list, max_length=200)


class CompetitorClassificationRequest(BaseModel):
    classification_tags: list[str] = Field(default_factory=list, max_length=8)


class MarketingPlanShareRequest(BaseModel):
    enabled: bool = True
    password: str | None = Field(default=None, max_length=120)


class MarketingPlanUnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=120)


async def get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    result = await db.execute(select(Suite).where(Suite.id == suite_id, Suite.owner_id == user.id))
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


def _strategy(suite: Suite) -> dict[str, Any]:
    return suite.strategy if isinstance(suite.strategy, dict) else {}


def _deck(suite: Suite) -> dict[str, Any] | None:
    deck = _strategy(suite).get("marketing_plan_deck")
    return deck if isinstance(deck, dict) else None


def _intelligence(suite: Suite) -> dict[str, Any]:
    strategy = _strategy(suite)
    language = infer_plan_language(suite)
    existing = strategy.get("marketing_intelligence")
    if isinstance(existing, dict):
        return normalize_marketing_intelligence(existing, suite_research_payload(suite), language)
    if not _deck(suite):
        return _empty_marketing_intelligence(language)
    return normalize_marketing_intelligence({}, suite_research_payload(suite), language)


def _action_plan(suite: Suite) -> dict[str, Any]:
    strategy = _strategy(suite)
    language = infer_plan_language(suite)
    existing = strategy.get("marketing_action_plan")
    if isinstance(existing, dict):
        return normalize_marketing_action_plan(existing, _deck(suite), language)
    return normalize_marketing_action_plan({}, _deck(suite), language)


def _share(deck: dict[str, Any]) -> dict[str, Any]:
    share = deck.get("share")
    return share if isinstance(share, dict) else {}


def _public_deck(deck: dict[str, Any]) -> dict[str, Any]:
    public = {k: v for k, v in deck.items() if k != "share"}
    share = _share(deck)
    public["share"] = {
        "enabled": bool(share.get("enabled")),
        "token": share.get("token"),
        "password_required": bool(share.get("password_hash")),
    }
    return public


async def _latest_marketing_plan_job(db: AsyncSession, suite_id: str) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.type == GenerationJobType.marketing_plan)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _active_marketing_plan_job(db: AsyncSession, suite_id: str) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.type == GenerationJobType.marketing_plan)
        .where(GenerationJob.status.in_(ACTIVE_STATUSES))
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _save_deck(suite: Suite, deck: dict[str, Any]) -> None:
    strategy = dict(_strategy(suite))
    strategy["marketing_plan_deck"] = deck
    suite.strategy = strategy


def _empty_marketing_intelligence(language: str) -> dict[str, Any]:
    return {
        "version": "marketing_intelligence_v1",
        "language": language,
        "status": "missing",
        "competitors": [],
        "demand_signals": [],
        "supply_signals": [],
        "opportunities": [],
        "source_links": [],
        "warnings": [],
    }


def _clear_marketing_plan_data(suite: Suite) -> list[str]:
    strategy = dict(_strategy(suite))
    removed = []
    for key in GENERATED_MARKETING_PLAN_KEYS:
        if key in strategy:
            removed.append(key)
            strategy.pop(key, None)
    suite.strategy = strategy
    return removed


def _save_marketing_intelligence(suite: Suite, intelligence: dict[str, Any]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    strategy["marketing_intelligence"] = intelligence
    suite.strategy = strategy
    return intelligence


def _unique_strings(values: Any, limit: int = 80) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    source = values if isinstance(values, list) else [values]
    for item in source:
        text = str(item or "").strip()
        if not text:
            continue
        marker = text.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        items.append(text)
    return items[:limit]


def _suite_services(suite: Suite) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    strategy = _strategy(suite)
    marketing_plan = strategy.get("marketing_plan") if isinstance(strategy.get("marketing_plan"), dict) else {}
    def values(key: str, source: dict[str, Any]) -> list[Any]:
        value = source.get(key)
        return value if isinstance(value, list) else ([value] if value else [])
    return _unique_strings(
        [
            *values("services", brand),
            *values("products", brand),
            *values("products_services", brand),
            *values("services", strategy),
            *values("products", strategy),
            *values("products_services", strategy),
            *values("services", marketing_plan),
            *values("products", marketing_plan),
            *values("products_services", marketing_plan),
        ],
        60,
    )


def _audience_keyword_languages(suite: Suite, fallback_language: str) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    def values(key: str) -> list[Any]:
        value = brand.get(key)
        return value if isinstance(value, list) else ([value] if value else [])
    candidates = _unique_strings(
        [
            *values("audience_language_names"),
            *values("audience_languages"),
            brand.get("primary_language"),
            fallback_language,
        ],
        4,
    )
    return candidates or [fallback_language]


def _brand_keyword_markers(brand_name: str) -> set[str]:
    normalized = " ".join(str(brand_name or "").casefold().split())
    if not normalized:
        return set()
    tokens = [token for token in re.split(r"\s+", normalized) if len(token) > 1]
    markers = {normalized}
    if len(tokens) >= 2:
        markers.add(" ".join(tokens[:2]))
    elif tokens:
        markers.add(tokens[0])
    return {marker for marker in markers if marker}


def _mentions_brand_keyword(text: str, brand_name: str) -> bool:
    normalized = " ".join(str(text or "").casefold().split())
    return bool(normalized and any(marker in normalized for marker in _brand_keyword_markers(brand_name)))


def _stable_slug(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:48] or fallback


def _keyword_candidates(suite: Suite, language: str, existing: list[str] | None = None, more: bool = False) -> list[dict[str, Any]]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    services = _suite_services(suite)
    category = str(brand.get("industry") or brand.get("category") or brand.get("niche") or suite.name or "").strip()
    brand_name = str(brand.get("name") or suite.name or "").strip()
    base_terms = _unique_strings([category, *services], 80)
    if not base_terms:
        base_terms = ["business services"]
    existing_markers = {item.casefold() for item in _unique_strings(existing or [])}
    languages = " ".join(_audience_keyword_languages(suite, language)).lower()
    wants_ar = str(language).startswith("ar") or "arabic" in languages or "العربية" in languages or "ar" in languages.split()
    wants_he = str(language).startswith("he") or "hebrew" in languages or "עברית" in languages or "he" in languages.split()
    if wants_ar:
        modifiers = ["", "أسعار", "عروض", "حجز", "خدمات"]
    elif wants_he:
        modifiers = ["", "מחירים", "מבצעים", "הזמנה", "שירותי"]
    else:
        modifiers = ["", "prices", "offers", "booking", "services"]
    if more:
        if wants_ar:
            modifiers = ["مقارنة", "احترافي", "محلي", "قريب", "استشارة", "مختص"]
        elif wants_he:
            modifiers = ["השוואה", "מקצועי", "מקומי", "קרוב", "ייעוץ", "מומחה"]
        else:
            modifiers = ["compare", "professional", "local", "nearby", "consultation", "specialist"]
    keywords: list[dict[str, Any]] = []
    for term in base_terms:
        term_words = term.split()
        trimmed_term = " ".join(term_words[:3])
        for modifier in modifiers:
            if not modifier:
                text = trimmed_term
            elif wants_he and modifier == "שירותי":
                text = " ".join([modifier, *term_words[:2]]).strip()
            else:
                text = " ".join([modifier, *term_words[:2]]).strip()
            words = text.split()
            if len(words) > 3:
                text = " ".join(words[:3])
            marker = text.casefold()
            if not text or marker in existing_markers or _mentions_brand_keyword(text, brand_name):
                continue
            keywords.append({
                "id": f"kw-{len(keywords) + 1}",
                "text": text,
                "intent": "commercial" if modifier else "core",
                "source": "fallback_more" if more else "fallback",
                "confidence": "starter",
            })
            existing_markers.add(marker)
            if len(keywords) >= 18:
                return keywords
    return keywords


async def _generate_keywords(suite: Suite, language: str, existing: list[str] | None = None, more: bool = False) -> list[dict[str, Any]]:
    fallback = _keyword_candidates(suite, language, existing, more)
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    services = _suite_services(suite)
    if not services and not brand:
        return fallback
    try:
        prompt = {
            "language": language,
            "audience_keyword_languages": _audience_keyword_languages(suite, language),
            "business": {
                "name": brand.get("name") or suite.name,
                "category": brand.get("industry") or brand.get("category") or brand.get("niche"),
                "services": services,
                "audience": brand.get("target_audience") or brand.get("audience_notes"),
                "location": brand.get("location") or brand.get("audience_location"),
            },
            "existing_keywords": existing or [],
            "mode": "generate_more" if more else "generate",
            "instructions": "Return JSON only: {\"keywords\":[{\"text\":\"...\",\"intent\":\"core|commercial|local|problem|comparison\",\"confidence\":\"medium\"}]}. Write every keyword in the target audience's native country language and selected audience language. Each keyword must be a short generic business-search term of 1 to 3 words. It should be useful as part of a search for a business like this Suite. Use the Suite name only as context to understand the business; do not return the brand/business name, partial brand-name keywords, or modifier phrases combined with the business name. Base keywords on the business category, services, products, audience needs, and location. Do not return English keywords unless English is one of the audience languages.",
        }
        raw = await call_text_ai(
            max_tokens=1200,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            system="You generate practical marketing keywords. Return strict JSON only.",
            timeout=50,
        )
        parsed = json.loads(raw)
        incoming = parsed.get("keywords") if isinstance(parsed, dict) else []
        existing_markers = {item.casefold() for item in _unique_strings(existing or [])}
        generated: list[dict[str, Any]] = []
        for item in incoming or []:
            if isinstance(item, str):
                text = item.strip()
                intent = "general"
                confidence = "medium"
            elif isinstance(item, dict):
                text = str(item.get("text") or item.get("keyword") or "").strip()
                intent = str(item.get("intent") or "general").strip()
                confidence = str(item.get("confidence") or "medium").strip()
            else:
                continue
            if not text or text.casefold() in existing_markers or _mentions_brand_keyword(text, str(brand.get("name") or suite.name or "")):
                continue
            generated.append({
                "id": f"kw-{len(generated) + 1}",
                "text": text,
                "intent": intent,
                "source": "ai_more" if more else "ai",
                "confidence": confidence,
            })
            existing_markers.add(text.casefold())
            if len(generated) >= 24:
                break
        return generated or fallback
    except Exception:
        return fallback


def _mock_competitors(suite: Suite, language: str, existing_urls: list[str] | None = None, offset: int = 0) -> list[dict[str, Any]]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    services = _suite_services(suite) or [brand.get("industry") or brand.get("category") or suite.name]
    service = str(services[offset % len(services)] or suite.name).strip()
    location = str(brand.get("location") or "").strip()
    source_types = [
        ("google_organic", "Google organic", "google", "https://www.google.com/search?q="),
        ("sponsored", "Google sponsored", "google", "https://www.google.com/search?q="),
        ("instagram", "Instagram", "instagram", "https://www.google.com/search?q=site%3Ainstagram.com+"),
        ("maps", "Google Maps", "maps", "https://www.google.com/maps/search/"),
        ("facebook", "Facebook", "facebook", "https://www.google.com/search?q=site%3Afacebook.com+"),
        ("tiktok", "TikTok", "tiktok", "https://www.google.com/search?q=site%3Atiktok.com+"),
    ]
    existing = {url for url in (existing_urls or []) if url}
    cards: list[dict[str, Any]] = []
    for index, (result_type, label, platform, base_url) in enumerate(source_types[offset % len(source_types):] + source_types[:offset % len(source_types)], start=1):
        modifier = "" if offset == 0 else f" alternative {offset + index}"
        query = "+".join(part for part in [service, location, f"competitors{modifier}"] if part).replace(" ", "+")
        url = f"{base_url}{query}"
        if url in existing:
            continue
        title_prefix = "نتيجة منافس" if str(language).startswith("ar") else "Competitor result"
        snippet = (
            f"نتيجة تجريبية من {label} مبنية على {service}. سيتم استبدالها بنتيجة SerpAPI فعلية."
            if str(language).startswith("ar")
            else f"Mock {label} result for {service}. This will be replaced by a real SerpAPI result."
        )
        cards.append({
            "id": f"mock-{result_type}-{offset + index}",
            "name": f"{title_prefix}: {service}",
            "title": f"{title_prefix}: {service}",
            "platform": platform,
            "result_type": result_type,
            "url": url,
            "reason": snippet,
            "offer": label,
            "evidence": service,
            "snippet": snippet,
            "opportunity": "استخدم هذه النتيجة لتقييم الرسائل والعروض." if str(language).startswith("ar") else "Use this result to assess messaging and offers.",
            "confidence": "mock",
            "classification_tags": [],
            "research_lead": True,
        })
        existing.add(url)
        if len(cards) >= 6:
            break
    return cards


SERPAPI_SOURCE_SPECS = (
    {"result_type": "google_organic", "platform": "google", "engine": "google", "site": "", "label": "Google organic"},
    {"result_type": "maps", "platform": "maps", "engine": "google_maps", "site": "", "label": "Google Maps"},
    {"result_type": "instagram", "platform": "instagram", "engine": "google", "site": "site:instagram.com", "label": "Instagram"},
    {"result_type": "facebook", "platform": "facebook", "engine": "google", "site": "site:facebook.com", "label": "Facebook"},
    {"result_type": "tiktok", "platform": "tiktok", "engine": "google", "site": "site:tiktok.com", "label": "TikTok"},
)


def _competitor_search_terms(suite: Suite, language: str, offset: int = 0) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    category = str(brand.get("industry") or brand.get("category") or brand.get("niche") or "").strip()
    location = str(brand.get("location") or brand.get("audience_location") or "").strip()
    services = _suite_services(suite)
    seeds = _unique_strings([category, *services], 10) or [suite.name]
    rotated = seeds[offset % len(seeds):] + seeds[:offset % len(seeds)]
    terms = []
    for seed in rotated[:4]:
        term = " ".join(part for part in [seed, location] if part).strip()
        if term:
            terms.append(term)
    return terms or [suite.name]


def _serpapi_competitors_from_payload(payload: dict[str, Any], result_type: str, limit: int = 5) -> list[dict[str, Any]]:
    if result_type == "maps":
        local_results = payload.get("local_results")
        if isinstance(local_results, dict):
            raw_items = local_results.get("places") or local_results.get("results") or []
        else:
            raw_items = local_results if isinstance(local_results, list) else []
    elif result_type == "google_sponsored":
        raw_items = payload.get("ads_results") or []
    else:
        raw_items = payload.get("organic_results") or []
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        url = str(raw.get("link") or raw.get("website") or raw.get("url") or raw.get("place_id_search") or "").strip()
        snippet = str(raw.get("snippet") or raw.get("description") or raw.get("address") or raw.get("type") or "").strip()
        if not title and not url:
            continue
        item = {
            "id": f"serpapi-{result_type}-{_stable_slug(title or url, str(index))}",
            "name": title or url,
            "title": title or url,
            "platform": "google" if result_type.startswith("google") else result_type,
            "result_type": result_type,
            "url": url,
            "reason": snippet,
            "offer": str(raw.get("displayed_link") or raw.get("type") or "").strip(),
            "evidence": snippet,
            "snippet": snippet,
            "opportunity": "",
            "confidence": "serpapi",
            "classification_tags": [],
            "research_lead": False,
        }
        if result_type == "maps":
            item["platform"] = "maps"
            if not item["url"] and raw.get("gps_coordinates"):
                coordinates = raw.get("gps_coordinates") or {}
                lat = coordinates.get("latitude")
                lon = coordinates.get("longitude")
                if lat and lon:
                    item["url"] = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        items.append(item)
        if len(items) >= limit:
            break
    return items


async def _fetch_serpapi_source(
    client: httpx.AsyncClient,
    suite: Suite,
    language: str,
    spec: dict[str, str],
    existing_urls: set[str],
    offset: int = 0,
) -> list[dict[str, Any]]:
    api_key = settings.serpapi_api_key.strip()
    if not api_key:
        return []
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    terms = _competitor_search_terms(suite, language, offset)
    query = terms[0]
    if spec.get("site"):
        query = f"{spec['site']} {query}"
    params: dict[str, Any] = {
        "api_key": api_key,
        "engine": spec["engine"],
        "q": query,
        "hl": "ar" if str(language).startswith("ar") else "he" if str(language).startswith("he") else "en",
        "num": 10,
    }
    location = str(brand.get("location") or brand.get("audience_location") or "").strip()
    if location:
        params["location"] = location
    response = await client.get("https://serpapi.com/search.json", params=params)
    response.raise_for_status()
    payload = response.json()
    candidates = _serpapi_competitors_from_payload(payload, str(spec["result_type"]), 5)
    unique: list[dict[str, Any]] = []
    for item in candidates:
        url = str(item.get("url") or "")
        marker = url or str(item.get("title") or "").casefold()
        if marker in existing_urls:
            continue
        existing_urls.add(marker)
        unique.append(item)
        if len(unique) >= 5:
            break
    return unique


async def _serpapi_competitors(suite: Suite, language: str, existing_urls: list[str] | None = None, offset: int = 0) -> list[dict[str, Any]]:
    if not settings.serpapi_api_key.strip():
        return []
    existing = {url for url in (existing_urls or []) if url}
    competitors: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=18) as client:
        for source_index, spec in enumerate(SERPAPI_SOURCE_SPECS):
            try:
                source_items = await _fetch_serpapi_source(client, suite, language, spec, existing, offset + source_index)
                competitors.extend(source_items[:5])
            except Exception:
                continue
    return competitors


def _save_competitor_scratch(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    intelligence = normalize_marketing_intelligence({"phase": "competitors"}, suite_research_payload(suite), output_language)
    intelligence["competitors"] = _mock_competitors(suite, output_language)
    intelligence["status"] = "competitors_ready"
    return _save_marketing_intelligence(suite, intelligence)


async def _save_competitor_scratch_from_search(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    intelligence = normalize_marketing_intelligence({"phase": "competitors"}, suite_research_payload(suite), output_language)
    competitors = await _serpapi_competitors(suite, output_language)
    if competitors:
        intelligence["competitors"] = competitors
    else:
        intelligence["competitors"] = _mock_competitors(suite, output_language)
        intelligence["warnings"] = ["SerpAPI did not return usable competitor results; showing starter source leads."]
    intelligence["status"] = "competitors_ready"
    return _save_marketing_intelligence(suite, intelligence)


def _append_competitor_scratch(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    existing = _strategy(suite).get("marketing_intelligence")
    base = normalize_marketing_intelligence(existing if isinstance(existing, dict) else {"phase": "competitors"}, suite_research_payload(suite), output_language)
    current = list(base.get("competitors") or [])
    existing_urls = [str(item.get("url") or "") for item in current if isinstance(item, dict)]
    current.extend(_mock_competitors(suite, output_language, existing_urls, offset=len(current)))
    base["competitors"] = current[:36]
    base["status"] = "competitors_ready"
    return _save_marketing_intelligence(suite, base)


async def _append_competitor_scratch_from_search(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    existing = _strategy(suite).get("marketing_intelligence")
    base = normalize_marketing_intelligence(existing if isinstance(existing, dict) else {"phase": "competitors"}, suite_research_payload(suite), output_language)
    current = list(base.get("competitors") or [])
    existing_urls = [str(item.get("url") or item.get("title") or "") for item in current if isinstance(item, dict)]
    more = await _serpapi_competitors(suite, output_language, existing_urls, offset=len(current))
    if not more:
        more = _mock_competitors(suite, output_language, existing_urls, offset=len(current))
    current.extend(more)
    base["competitors"] = current[:60]
    base["status"] = "competitors_ready"
    return _save_marketing_intelligence(suite, base)


def _save_demand_supply_scratch(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    existing = _strategy(suite).get("marketing_intelligence")
    base = existing if isinstance(existing, dict) else {"phase": "competitors"}
    base = normalize_marketing_intelligence(base, suite_research_payload(suite), output_language)
    intelligence = normalize_marketing_intelligence(
        {
            **base,
            "phase": "demand_supply",
            "status": "ready",
            "competitors": base.get("competitors") or [],
        },
        suite_research_payload(suite),
        output_language,
    )
    return _save_marketing_intelligence(suite, intelligence)


def _marketing_plan_response(
    suite: Suite,
    suite_id: str,
    job: GenerationJob | None,
    status: str | None = None,
) -> dict[str, Any]:
    deck = _deck(suite)
    return {
        "status": status or ("ready" if deck else "missing"),
        "suite_id": suite_id,
        "language": infer_plan_language(suite),
        "deck": _public_deck(deck) if deck else None,
        "intelligence": _intelligence(suite),
        "action_plan": _action_plan(suite),
        "generation_status": serialize_job(job, suite_id=suite_id),
    }


async def _find_by_share_token(db: AsyncSession, token: str) -> tuple[Suite, dict[str, Any]] | None:
    result = await db.execute(select(Suite))
    for suite in result.scalars().all():
        deck = _deck(suite)
        if not deck:
            continue
        share = _share(deck)
        if share.get("enabled") and share.get("token") == token:
            return suite, deck
    return None


@router.get("/suites/{suite_id}/marketing-plan")
async def get_marketing_plan(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    deck = _deck(suite)
    job = await _latest_marketing_plan_job(db, suite_id)
    if not deck:
        return _marketing_plan_response(suite, suite_id, job, "missing")
    return _marketing_plan_response(suite, suite_id, job, "ready")


@router.post("/suites/{suite_id}/marketing-plan/generate")
async def generate_marketing_plan(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    active = await _active_marketing_plan_job(db, suite_id)
    if active:
        return _marketing_plan_response(suite, suite_id, active, active.status.value)

    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.marketing_plan,
        user_id=current_user.id,
        input_data={
            "section": "strategy",
            "language": request_data.language,
            "near_term_focus": request_data.near_term_focus,
            "upcoming_campaigns": [item for item in request_data.upcoming_campaigns if item.strip()][:12],
            "planning_notes": request_data.planning_notes,
        },
    )
    return _marketing_plan_response(suite, suite_id, job, job.status.value)


@router.delete("/suites/{suite_id}/marketing-plan")
async def delete_marketing_plan(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    active = await _active_marketing_plan_job(db, suite_id)
    if active:
        raise HTTPException(status_code=409, detail="Wait for the active marketing plan job to finish before deleting it.")
    removed = _clear_marketing_plan_data(suite)
    await db.commit()
    response = _marketing_plan_response(suite, suite_id, await _latest_marketing_plan_job(db, suite_id), "missing")
    response["deleted"] = True
    response["removed"] = removed
    return response


async def _generate_marketing_plan_section(
    suite_id: str,
    section: str,
    payload: GenerateMarketingPlanRequest | None,
    current_user: User,
    db: AsyncSession,
):
    suite = await get_owned_suite(db, suite_id, current_user)
    if not _deck(suite):
        raise HTTPException(status_code=404, detail="Generate the core marketing plan before this section.")
    request_data = payload or GenerateMarketingPlanRequest()
    active = await _active_marketing_plan_job(db, suite_id)
    if active:
        return _marketing_plan_response(suite, suite_id, active, active.status.value)
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.marketing_plan,
        user_id=current_user.id,
        input_data={
            "section": section,
            "language": request_data.language,
            "near_term_focus": request_data.near_term_focus,
            "upcoming_campaigns": [item for item in request_data.upcoming_campaigns if item.strip()][:12],
            "planning_notes": request_data.planning_notes,
        },
    )
    return _marketing_plan_response(suite, suite_id, job, job.status.value)


async def _generate_marketing_research_section(
    suite_id: str,
    section: str,
    payload: GenerateMarketingPlanRequest | None,
    current_user: User,
    db: AsyncSession,
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    active = await _active_marketing_plan_job(db, suite_id)
    if active:
        return _marketing_plan_response(suite, suite_id, active, active.status.value)
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.marketing_plan,
        user_id=current_user.id,
        input_data={
            "section": section,
            "language": request_data.language,
            "near_term_focus": request_data.near_term_focus,
            "upcoming_campaigns": [item for item in request_data.upcoming_campaigns if item.strip()][:12],
            "planning_notes": request_data.planning_notes,
        },
    )
    return _marketing_plan_response(suite, suite_id, job, job.status.value)


@router.post("/suites/{suite_id}/marketing-plan/competitors/generate")
async def generate_marketing_competitors(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    await _save_competitor_scratch_from_search(suite, request_data.language)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/competitors/generate-more")
async def generate_more_marketing_competitors(
    suite_id: str,
    payload: MarketingStageRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or MarketingStageRequest()
    await _append_competitor_scratch_from_search(suite, request_data.language)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.patch("/suites/{suite_id}/marketing-plan/competitors/{competitor_id}")
async def update_marketing_competitor(
    suite_id: str,
    competitor_id: str,
    payload: CompetitorClassificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    language = infer_plan_language(suite)
    intelligence = normalize_marketing_intelligence(
        _strategy(suite).get("marketing_intelligence"),
        suite_research_payload(suite),
        language,
    )
    allowed = {"not_competitor", "good_competitor", "local_competitor", "global_competitor"}
    tags = [tag for tag in _unique_strings(payload.classification_tags, 8) if tag in allowed]
    competitors = []
    found = False
    for competitor in intelligence.get("competitors") or []:
        if isinstance(competitor, dict) and competitor.get("id") == competitor_id:
            competitor = {**competitor, "classification_tags": tags}
            found = True
        competitors.append(competitor)
    if not found:
        raise HTTPException(status_code=404, detail="Competitor not found")
    intelligence["competitors"] = competitors
    _save_marketing_intelligence(suite, intelligence)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/keywords/generate")
async def generate_marketing_keywords(
    suite_id: str,
    payload: MarketingStageRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or MarketingStageRequest()
    output_language = infer_plan_language(suite, request_data.language)
    intelligence = normalize_marketing_intelligence(
        {
            **(_strategy(suite).get("marketing_intelligence") if isinstance(_strategy(suite).get("marketing_intelligence"), dict) else {}),
            "phase": "keywords",
        },
        suite_research_payload(suite),
        output_language,
    )
    keywords = await _generate_keywords(suite, output_language, [], more=False)
    intelligence["keywords"] = keywords
    intelligence["status"] = "keywords_ready"
    intelligence["generated_at"] = datetime.now(timezone.utc).isoformat()
    _save_marketing_intelligence(suite, intelligence)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/keywords/generate-more")
async def generate_more_marketing_keywords(
    suite_id: str,
    payload: MarketingStageRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or MarketingStageRequest()
    output_language = infer_plan_language(suite, request_data.language)
    intelligence = normalize_marketing_intelligence(
        {
            **(_strategy(suite).get("marketing_intelligence") if isinstance(_strategy(suite).get("marketing_intelligence"), dict) else {}),
            "phase": "keywords",
        },
        suite_research_payload(suite),
        output_language,
    )
    current = list(intelligence.get("keywords") or [])
    existing_texts = [str(item.get("text") or "") for item in current if isinstance(item, dict)]
    more_keywords = await _generate_keywords(suite, output_language, [*existing_texts, *request_data.existing_values], more=True)
    seen = {item.casefold() for item in existing_texts if item}
    for keyword in more_keywords:
        marker = str(keyword.get("text") or "").casefold()
        if marker and marker not in seen:
            current.append(keyword)
            seen.add(marker)
    intelligence["keywords"] = current[:80]
    intelligence["status"] = "keywords_ready"
    intelligence["generated_at"] = datetime.now(timezone.utc).isoformat()
    _save_marketing_intelligence(suite, intelligence)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/demand-supply/generate")
async def generate_marketing_demand_supply(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    _save_demand_supply_scratch(suite, request_data.language)
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/social-plan/generate")
async def generate_marketing_social_plan(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _generate_marketing_plan_section(suite_id, "social", payload, current_user, db)


@router.post("/suites/{suite_id}/marketing-plan/paid-funnel/generate")
async def generate_marketing_paid_funnel(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _generate_marketing_plan_section(suite_id, "ads", payload, current_user, db)


@router.get("/suites/{suite_id}/marketing-plan/generation-status")
async def marketing_plan_generation_status(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    job = await _latest_marketing_plan_job(db, suite_id)
    return serialize_job(job, suite_id=suite_id)


@router.post("/suites/{suite_id}/marketing-plan/share")
async def configure_marketing_plan_share(
    suite_id: str,
    payload: MarketingPlanShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    deck = _deck(suite)
    if not deck:
        raise HTTPException(status_code=404, detail="Generate the marketing plan before sharing it.")
    share = _share(deck)
    token = share.get("token") or secrets.token_urlsafe(24)
    deck["share"] = {
        "enabled": payload.enabled,
        "token": token,
        "password_hash": hash_password(payload.password) if payload.password else share.get("password_hash"),
    }
    if payload.password == "":
        deck["share"].pop("password_hash", None)
    _save_deck(suite, deck)
    await db.commit()
    return {"ok": True, "share": _public_deck(deck)["share"]}


@router.get("/marketing-plans/share/{token}")
async def get_public_marketing_plan(token: str, db: AsyncSession = Depends(get_db)):
    found = await _find_by_share_token(db, token)
    if not found:
        raise HTTPException(status_code=404, detail="Marketing plan not found")
    suite, deck = found
    share = _share(deck)
    if share.get("password_hash"):
        return {
            "locked": True,
            "suite_name": suite.name,
            "share": {"enabled": True, "token": token, "password_required": True},
        }
    return {"locked": False, "suite_name": suite.name, "deck": _public_deck(deck)}


@router.post("/marketing-plans/share/{token}/unlock")
async def unlock_public_marketing_plan(
    token: str,
    payload: MarketingPlanUnlockRequest,
    db: AsyncSession = Depends(get_db),
):
    found = await _find_by_share_token(db, token)
    if not found:
        raise HTTPException(status_code=404, detail="Marketing plan not found")
    suite, deck = found
    share = _share(deck)
    password_hash = share.get("password_hash")
    if password_hash and not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=403, detail="Wrong password")
    return {"locked": False, "suite_name": suite.name, "deck": _public_deck(deck)}
