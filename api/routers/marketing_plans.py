"""Marketing plan deck API."""
from __future__ import annotations

import asyncio
import logging
import random
import secrets
from datetime import datetime, timezone
import json
import re
from typing import Any

log = logging.getLogger(__name__)

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.external_calls import external_call
from ..core.llm_client import call_text_ai
from ..core.security import get_current_user, hash_password, verify_password
from ..models.generation_job import GenerationJob, GenerationJobType
from ..models.suite import Suite
from ..models.user import User
from ..services.billing import enforce_generation_gate, estimate_content_generation_tokens
from ..services.generation_jobs import ACTIVE_STATUSES, create_job, get_active_job, serialize_job
from ..services.google_ads import build_keyword_planner_summary, fetch_keyword_planner_ideas
from ..services.admin_audit import record_audit_log, record_provider_usage
from ..services.provider_pricing import estimate_google_ads_keyword_planner_cost_usd, estimate_serpapi_cost_usd
from ..services.marketing_plan_generator import (
    build_social_plan_schedule,
    generate_paid_content_work_plan,
    generate_social_content_work_plan,
    generate_marketing_customer_personas_research,
    infer_plan_language,
    normalize_marketing_action_plan,
    normalize_marketing_intelligence,
    suite_research_payload,
)
from ..services.social_ideas_generator import generate_social_ideas
from ..services.marketing_plan_pdf import build_marketing_plan_pdf
from ..services.marketing_plan_visuals import deck_visuals, ensure_marketing_plan_visuals
from ..services.meta_interests import match_meta_interests
from ..services.funnel_guard import block_funnel_regeneration, enforce_funnel_call_limit
from ..services.multi_scraper import search_web
from ..services.suite_access import require_suite_access

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
    count: int = Field(default=5, ge=1, le=10)


class GenerateSocialContentPlanRequest(BaseModel):
    language: str | None = None
    monthly_posts: int = Field(default=15, ge=1, le=31)
    plan_type: str = Field(default="monthly", pattern="^(weekly|monthly)$")


class UpdateSocialContentItemRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    idea: str | None = Field(default=None, max_length=2000)
    script: str | None = Field(default=None, max_length=6000)
    cta: str | None = Field(default=None, max_length=500)


class GenerateSocialContentItemsRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, max_length=40)


class SocialContentPlanSelectionRequest(BaseModel):
    selected_ids: list[str] = Field(default_factory=list, max_length=80)


class GenerateSocialIdeasRequest(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")   # e.g. "2026-08"
    target_count: int = Field(default=12, ge=1, le=31)
    language: str | None = None


class SocialIdeasSelectionRequest(BaseModel):
    selected_ids: list[str] = Field(default_factory=list, max_length=80)
    notes: dict[str, str] = Field(default_factory=dict)              # idea_id -> note
    assets: dict[str, list[str]] = Field(default_factory=dict)       # idea_id -> chosen asset_types


class GeneratePaidContentPlanRequest(BaseModel):
    language: str | None = None


class PaidContentPlanSelectionRequest(BaseModel):
    selected_ids: list[str] = Field(default_factory=list, max_length=80)


class MarketingKeywordInput(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    text: str = Field(min_length=1, max_length=120)
    intent: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=80)
    confidence: str | None = Field(default=None, max_length=80)


class MarketingKeywordsUpdateRequest(BaseModel):
    keywords: list[MarketingKeywordInput] = Field(default_factory=list, max_length=80)


class MarketingCompetitorInput(BaseModel):
    id: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    title: str | None = Field(default=None, max_length=240)
    platform: str | None = Field(default=None, max_length=80)
    result_type: str | None = Field(default=None, max_length=80)
    url: str | None = Field(default=None, max_length=1000)
    snippet: str | None = Field(default=None, max_length=1200)
    reason: str | None = Field(default=None, max_length=1200)
    evidence: str | None = Field(default=None, max_length=1200)
    offer: str | None = Field(default=None, max_length=1200)
    opportunity: str | None = Field(default=None, max_length=1200)
    confidence: str | None = Field(default=None, max_length=80)
    research_lead: bool | None = None
    classification_tags: list[str] = Field(default_factory=list, max_length=8)
    relevance: str | None = Field(default=None, max_length=20)
    rating: float | None = Field(default=None, ge=0, le=5)
    reviews: int | None = Field(default=None, ge=0)
    address: str | None = Field(default=None, max_length=500)


class MarketingCompetitorsUpdateRequest(BaseModel):
    competitors: list[MarketingCompetitorInput] = Field(default_factory=list, max_length=80)


class CompetitorClassificationRequest(BaseModel):
    classification_tags: list[str] = Field(default_factory=list, max_length=8)


class MarketingMessageUpdateRequest(BaseModel):
    message: str = Field(default="", max_length=4000)


class MarketingPlanShareRequest(BaseModel):
    enabled: bool = True
    password: str | None = Field(default=None, max_length=120)


class MarketingPlanUnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=120)


async def get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    return await require_suite_access(db, suite_id, user)


def _strategy(suite: Suite) -> dict[str, Any]:
    return suite.strategy if isinstance(suite.strategy, dict) else {}


def _deck(suite: Suite) -> dict[str, Any] | None:
    deck = _strategy(suite).get("marketing_plan_deck")
    return deck if isinstance(deck, dict) else None


def _redact_sensitive_text(value: str) -> str:
    return re.sub(r"api_key=[^&\s'\"<>]+", "[redacted]", value)


def _sanitize_market_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, list):
        return [_sanitize_market_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_market_value(item) for key, item in value.items()}
    return value


def _sanitize_marketing_intelligence(intelligence: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_market_value(intelligence)
    return sanitized if isinstance(sanitized, dict) else intelligence


def _intelligence(suite: Suite) -> dict[str, Any]:
    strategy = _strategy(suite)
    language = infer_plan_language(suite)
    existing = strategy.get("marketing_intelligence")
    if isinstance(existing, dict):
        return _sanitize_marketing_intelligence(
            normalize_marketing_intelligence(existing, suite_research_payload(suite), language)
        )
    if not _deck(suite):
        return _empty_marketing_intelligence(language)
    return _sanitize_marketing_intelligence(normalize_marketing_intelligence({}, suite_research_payload(suite), language))


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
        "personas": [],
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
    intelligence = _sanitize_marketing_intelligence(intelligence)
    strategy["marketing_intelligence"] = intelligence
    suite.strategy = strategy
    return intelligence


def _save_marketing_message(suite: Suite, message: str) -> str:
    strategy = dict(_strategy(suite))
    strategy["marketing_message"] = message
    suite.strategy = strategy
    return message


def _save_social_content_plan(suite: Suite, plan: dict[str, Any]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    existing_action = strategy.get("marketing_action_plan")
    action_plan = dict(existing_action) if isinstance(existing_action, dict) else {}
    action_plan["social_content_plan"] = plan
    action_plan["status"] = "ready"
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy
    return plan


def _save_social_ideas_plan(suite: Suite, plan: dict[str, Any]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    existing_action = strategy.get("marketing_action_plan")
    action_plan = dict(existing_action) if isinstance(existing_action, dict) else {}
    action_plan["social_ideas_plan"] = plan
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy
    return plan


def _social_ideas_plan(suite: Suite) -> dict[str, Any]:
    action = _strategy(suite).get("marketing_action_plan")
    plan = action.get("social_ideas_plan") if isinstance(action, dict) else None
    return plan if isinstance(plan, dict) else {}


def _update_social_ideas_selection(
    suite: Suite, selected_ids: list[str], notes: dict[str, str], assets: dict[str, list[str]]
) -> dict[str, Any]:
    plan = dict(_social_ideas_plan(suite))
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    chosen = set(selected_ids)
    updated = []
    for idea in candidates:
        if not isinstance(idea, dict):
            continue
        idea = dict(idea)
        idea_id = str(idea.get("id"))
        idea["selected"] = idea_id in chosen
        if idea_id in notes:
            idea["user_notes"] = str(notes[idea_id])[:2000]
        if idea_id in assets:
            picked = set(assets[idea_id])
            idea["apply_assets"] = [
                {**a, "recommended": a.get("asset_type") in picked}
                for a in (idea.get("apply_assets") or [])
                if isinstance(a, dict)
            ]
        updated.append(idea)
    plan["candidates"] = updated
    plan["selected_ids"] = [i for i in selected_ids]
    _save_social_ideas_plan(suite, plan)
    return plan


def _save_paid_content_plan(suite: Suite, plan: dict[str, Any]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    existing_action = strategy.get("marketing_action_plan")
    action_plan = dict(existing_action) if isinstance(existing_action, dict) else {}
    action_plan["paid_content_plan"] = plan
    action_plan["status"] = "ready"
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy
    return plan


def _update_social_content_selection(suite: Suite, selected_ids: list[str]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    action_plan = dict(strategy.get("marketing_action_plan") or {})
    plan = dict(action_plan.get("social_content_plan") or {})
    if not plan:
        raise HTTPException(status_code=404, detail="Generate the social content work plan first.")
    valid_ids = {
        str(item.get("id"))
        for group in (plan.get("candidates") or {}).values()
        if isinstance(group, list)
        for item in group
        if isinstance(item, dict) and item.get("id")
    }
    clean_ids = []
    seen = set()
    for item_id in selected_ids:
        value = str(item_id or "").strip()
        if value and value in valid_ids and value not in seen:
            clean_ids.append(value)
            seen.add(value)
    plan["selected_ids"] = clean_ids
    build_social_plan_schedule(plan)
    action_plan["social_content_plan"] = plan
    action_plan["status"] = "ready" if clean_ids else "draft"
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy
    return plan


def _social_plan_for_update(suite: Suite) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    strategy = dict(_strategy(suite))
    action_plan = dict(strategy.get("marketing_action_plan") or {})
    plan = dict(action_plan.get("social_content_plan") or {})
    if not plan:
        raise HTTPException(status_code=404, detail="Generate the social content work plan first.")
    return strategy, action_plan, plan


def _store_social_plan(suite: Suite, strategy: dict[str, Any], action_plan: dict[str, Any], plan: dict[str, Any]) -> None:
    action_plan["social_content_plan"] = plan
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy


def _find_social_plan_item(plan: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for group in (plan.get("candidates") or {}).values():
        if not isinstance(group, list):
            continue
        for item in group:
            if isinstance(item, dict) and str(item.get("id")) == item_id:
                return item
    return None


def _social_item_content_type(item: dict[str, Any]) -> str:
    text = str(item.get("format") or "").lower()
    mode = str(item.get("production_mode") or "").lower()
    if "carousel" in text or mode == "ai_carousel":
        return "carousel"
    if "reel" in text or "video" in text or "story" in text or mode == "ai_video":
        return "video"
    return "image"


def _social_item_generation_prompt(suite: Suite, item: dict[str, Any], language: str) -> str:
    brand = dict(suite.brand or {})
    footer_bits = []
    if brand.get("name"):
        footer_bits.append(f"Business name: {brand['name']}")
    for key, label in (("phone", "Phone"), ("whatsapp", "WhatsApp"), ("website", "Website"), ("working_hours", "Working hours")):
        if brand.get(key):
            footer_bits.append(f"{label}: {brand[key]}")
    social_links = brand.get("social_links") or {}
    if not brand.get("website") and social_links.get("instagram"):
        footer_bits.append(f"Instagram: {social_links['instagram']}")
    intelligence = _strategy(suite).get("marketing_intelligence") or {}
    keywords = []
    for keyword in (intelligence.get("keywords") or [])[:12]:
        text = str(keyword.get("text") if isinstance(keyword, dict) else keyword or "").strip()
        if text:
            keywords.append(text)
    return "\n".join(
        [
            "Execute this planned content idea EXACTLY as described — do not invent a different idea.",
            f"Title / hook: {item.get('title') or ''}",
            f"Idea: {item.get('idea') or ''}",
            f"Script draft (use it as the base of the caption): {item.get('script') or ''}",
            f"Call to action: {item.get('cta') or ''}",
            "",
            "Caption requirements:",
            "- Follow the script's story and tone; polish it into a ready-to-publish caption.",
            "- End the caption with a short business footer built ONLY from these details (skip anything missing): "
            + ("; ".join(footer_bits) or "business name only"),
            "- Close with a hashtags section inspired by the idea plus these strategy keywords: "
            + (", ".join(keywords) or "the business services"),
        ]
    )


async def _sync_social_plan_generation(db: AsyncSession, suite: Suite) -> None:
    """Lazily reconcile plan items with their generation jobs (called on plan reads)."""
    strategy = dict(_strategy(suite))
    action_plan = dict(strategy.get("marketing_action_plan") or {})
    plan = dict(action_plan.get("social_content_plan") or {})
    if not plan:
        return
    pending: dict[str, dict[str, Any]] = {}
    for group in (plan.get("candidates") or {}).values():
        if not isinstance(group, list):
            continue
        for item in group:
            generation = item.get("generation") if isinstance(item, dict) else None
            if not isinstance(generation, dict):
                continue
            if generation.get("status") in {"queued", "generating"} and generation.get("job_id"):
                pending[str(generation["job_id"])] = item
    if not pending:
        return
    result = await db.execute(select(GenerationJob).where(GenerationJob.id.in_(list(pending.keys()))))
    changed = False
    for job in result.scalars().all():
        item = pending.get(job.id)
        if not item:
            continue
        generation = dict(item.get("generation") or {})
        status = str(job.status.value if hasattr(job.status, "value") else job.status)
        if status == "completed":
            post_ids = list((job.result or {}).get("post_ids") or [])
            generation.update(
                {
                    "status": "ready",
                    "post_id": post_ids[0] if post_ids else None,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            changed = True
        elif status in {"failed", "cancelled"}:
            generation.update({"status": "failed", "error": job.error or "Generation failed."})
            changed = True
        elif status == "running" and generation.get("status") != "generating":
            generation["status"] = "generating"
            changed = True
        item["generation"] = generation
    if changed:
        _store_social_plan(suite, strategy, action_plan, plan)
        await db.commit()


def _update_paid_content_selection(suite: Suite, selected_ids: list[str]) -> dict[str, Any]:
    strategy = dict(_strategy(suite))
    action_plan = dict(strategy.get("marketing_action_plan") or {})
    plan = dict(action_plan.get("paid_content_plan") or {})
    if not plan:
        raise HTTPException(status_code=404, detail="Generate the paid content work plan first.")
    valid_items = {
        str(item.get("id")): str(item.get("stage") or stage_key)
        for stage_key, group in (plan.get("candidates") or {}).items()
        if isinstance(group, list)
        for item in group
        if isinstance(item, dict) and item.get("id")
    }
    stage_limits = {
        str(stage.get("key")): max(0, int(stage.get("required_count") or 1))
        for stage in (plan.get("stages") or [])
        if isinstance(stage, dict) and stage.get("key")
    }
    clean_ids = []
    seen = set()
    selected_per_stage: dict[str, int] = {}
    for item_id in selected_ids:
        value = str(item_id or "").strip()
        stage = valid_items.get(value)
        limit = stage_limits.get(str(stage), 1)
        if value and stage and value not in seen and selected_per_stage.get(stage, 0) < limit:
            clean_ids.append(value)
            seen.add(value)
            selected_per_stage[stage] = selected_per_stage.get(stage, 0) + 1
    plan["selected_ids"] = clean_ids
    action_plan["paid_content_plan"] = plan
    action_plan["status"] = "ready" if clean_ids else "draft"
    strategy["marketing_action_plan"] = action_plan
    suite.strategy = strategy
    return plan


def _normalize_competitor_tags(values: Any) -> list[str]:
    allowed = {"not_competitor", "good_competitor", "local_competitor", "global_competitor"}
    tags = [tag for tag in _unique_strings(values, 8) if tag in allowed]
    if "not_competitor" in tags:
        return ["not_competitor"]
    priority = ["good_competitor", "local_competitor", "global_competitor"]
    return [tag for tag in priority if tag in tags]


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


def _clean_search_fragment(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("name", "label", "country", "city", "location", "audience_location"):
            if value.get(key):
                parts.append(_clean_search_fragment(value.get(key)))
        for key in ("countries", "cities"):
            nested = value.get(key)
            if isinstance(nested, list):
                parts.extend(_clean_search_fragment(item) for item in nested[:3])
        return " ".join(part for part in _unique_strings(parts, 4) if part).strip()
    if isinstance(value, list):
        return " ".join(part for part in (_clean_search_fragment(item) for item in value[:3]) if part).strip()
    text = str(value or "").strip()
    if not text or text.startswith("{") or text.startswith("["):
        return ""
    return re.sub(r"\s+", " ", text)


def _suite_services(suite: Suite) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    strategy = _strategy(suite)
    marketing_plan = strategy.get("marketing_plan") if isinstance(strategy.get("marketing_plan"), dict) else {}
    def values(key: str, source: dict[str, Any]) -> list[Any]:
        value = source.get(key)
        return value if isinstance(value, list) else ([value] if value else [])
    return _unique_strings(
        [
            *[_clean_search_fragment(item) for item in values("services", brand)],
            *[_clean_search_fragment(item) for item in values("products", brand)],
            *[_clean_search_fragment(item) for item in values("products_services", brand)],
            *[_clean_search_fragment(item) for item in values("services", strategy)],
            *[_clean_search_fragment(item) for item in values("products", strategy)],
            *[_clean_search_fragment(item) for item in values("products_services", strategy)],
            *[_clean_search_fragment(item) for item in values("services", marketing_plan)],
            *[_clean_search_fragment(item) for item in values("products", marketing_plan)],
            *[_clean_search_fragment(item) for item in values("products_services", marketing_plan)],
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


def _suite_location(suite: Suite) -> str:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    for key in ("audience_country", "country", "location", "audience_location", "target_country"):
        value = _clean_search_fragment(brand.get(key))
        if value:
            return value
    return ""


def _suite_website_url(suite: Suite) -> str:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    for key in ("website", "url", "website_url", "site_url"):
        value = str(brand.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return ""


HEBREW_MARKET_TERM_MAP = {
    "تداول": "מסחר",
    "دورات تداول": "קורס מסחר",
    "تعليم تداول": "לימודי מסחר",
    "تعلم التداول": "לימוד מסחר",
    "استثمار": "השקעות",
    "تعليم الاستثمار": "לימודי השקעות",
    "أسهم": "מניות",
    "الأسهم": "מניות",
    "تحليل الأسهم": "ניתוח מניות",
    "اكاديمية": "אקדמיה",
    "أكاديمية": "אקדמיה",
}


def _is_israel_market(suite: Suite) -> bool:
    location = _suite_location(suite)
    return bool(_serpapi_country_code(location) == "il" or any(term in location.casefold() for term in ("israel", "إسرائيل", "اسرائيل", "ישראל")))


def _is_global_market(suite: Suite) -> bool:
    """No target country selected, or the audience scope is explicitly worldwide."""
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    audience_location = brand.get("audience_location") if isinstance(brand.get("audience_location"), dict) else {}
    scope = str(audience_location.get("scope") or "").strip().casefold()
    if scope in {"world", "worldwide", "global"}:
        return True
    return not _suite_location(suite).strip()


# Economically leading markets checked for worldwide suites (name passed to
# the Keyword Planner geo lookup).
GLOBAL_PLANNER_MARKETS = ("United States", "United Kingdom", "United Arab Emirates")


def _needs_hebrew_market_terms(suite: Suite, language: str) -> bool:
    if not str(language or "").startswith("ar"):
        return False
    return _is_israel_market(suite)


def _contains_hebrew(text: str) -> bool:
    return any("\u0590" <= char <= "\u05ff" for char in str(text or ""))


def _hebrew_market_terms(values: list[str], limit: int = 10) -> list[str]:
    terms: list[str] = []
    for value in values:
        text = _clean_search_fragment(value)
        lowered = text.casefold()
        if not text:
            continue
        for arabic, hebrew in HEBREW_MARKET_TERM_MAP.items():
            if arabic.casefold() in lowered:
                terms.append(hebrew)
        if _contains_hebrew(text):
            terms.append(text)
    return _unique_strings(terms, limit)


def _is_latin_term(text: str) -> bool:
    return bool(text) and not _contains_hebrew(text) and not any("؀" <= char <= "ۿ" for char in text)


async def _english_planner_terms(keywords: list[str], limit: int = 10) -> list[str]:
    """English Keyword Planner seeds for worldwide suites: AI translation of the
    plan keywords, falling back to whichever terms are already Latin-script."""
    fallback = _unique_strings([keyword for keyword in keywords if _is_latin_term(keyword)], limit)
    source = [keyword for keyword in _unique_strings(keywords, limit) if not _is_latin_term(keyword)]
    if not source:
        return fallback
    try:
        prompt = {
            "keywords": source,
            "instructions": "Translate every keyword into the English search term people would actually type into Google for the same intent (1-3 words each). Return JSON only: {\"keywords\":[\"...\"]}.",
        }
        raw = await call_text_ai(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            max_tokens=1200,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            system="You translate marketing search keywords into natural English search terms. Return strict JSON only.",
            timeout=40,
        )
        parsed = json.loads(raw)
        incoming = parsed.get("keywords") if isinstance(parsed, dict) else []
        translated = [
            _clean_search_fragment(item)
            for item in incoming or []
            if isinstance(item, str) and _is_latin_term(item)
        ]
        return _unique_strings([*translated, *fallback], limit)
    except Exception:
        return fallback


async def _hebrew_planner_terms(keywords: list[str], limit: int = 10) -> list[str]:
    """Hebrew Keyword Planner seeds: AI translation of the plan keywords, with the static map as fallback."""
    fallback = _hebrew_market_terms(keywords, limit)
    source = [keyword for keyword in _unique_strings(keywords, limit) if not _contains_hebrew(keyword)]
    if not source:
        return fallback
    try:
        prompt = {
            "keywords": source,
            "instructions": "Translate every keyword into the Hebrew search term Israelis would actually type into Google for the same intent (1-3 words each). Return JSON only: {\"keywords\":[\"...\"]}.",
        }
        raw = await call_text_ai(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            max_tokens=1200,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            system="You translate marketing search keywords into natural Hebrew search terms. Return strict JSON only.",
            timeout=40,
        )
        parsed = json.loads(raw)
        incoming = parsed.get("keywords") if isinstance(parsed, dict) else []
        translated = [
            _clean_search_fragment(item)
            for item in incoming or []
            if isinstance(item, str) and _contains_hebrew(item)
        ]
        return _unique_strings([*translated, *fallback], limit)
    except Exception:
        return fallback


def _demand_supply_seed_pools(suite: Suite, language: str | None = None) -> tuple[list[str], list[str]]:
    """Two seed pools for the Keyword Planner: plan keywords and suite services/products."""
    output_language = infer_plan_language(suite, language)
    intelligence = _intelligence(suite)
    keywords = [
        _clean_search_fragment(item.get("text") or item.get("keyword") or "")
        for item in intelligence.get("keywords") or []
        if isinstance(item, dict)
    ]
    keyword_pool = _unique_strings(keywords, 60)
    if not keyword_pool:
        keyword_pool = _unique_strings([item["text"] for item in _keyword_candidates(suite, output_language)], 60)
    keyword_markers = {item.casefold() for item in keyword_pool}
    service_pool = [item for item in _suite_services(suite) if item.casefold() not in keyword_markers]
    return keyword_pool, service_pool


def _demand_supply_seed_selection(
    keyword_pool: list[str],
    service_pool: list[str],
    checked: set[str],
    per_source: int = 5,
) -> tuple[list[str], list[str], int]:
    """Randomly pick up to per_source unchecked terms from each pool; also return how many stay unchecked."""
    remaining_keywords = [item for item in keyword_pool if item.casefold() not in checked]
    remaining_services = [item for item in service_pool if item.casefold() not in checked]
    selected_keywords = random.sample(remaining_keywords, min(per_source, len(remaining_keywords)))
    selected_services = random.sample(remaining_services, min(per_source, len(remaining_services)))
    remaining = (len(remaining_keywords) - len(selected_keywords)) + (len(remaining_services) - len(selected_services))
    return selected_keywords, selected_services, remaining


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
                break
        if len(keywords) >= 18:
            break
    if _needs_hebrew_market_terms(suite, language):
        for term in _hebrew_market_terms(base_terms, 6):
            marker = term.casefold()
            if not term or marker in existing_markers:
                continue
            keywords.append({
                "id": f"kw-{len(keywords) + 1}",
                "text": term,
                "intent": "core",
                "source": "fallback_hebrew",
                "confidence": "starter",
            })
            existing_markers.add(marker)
            if len(keywords) >= 24:
                break
    return keywords


async def _generate_keywords(suite: Suite, language: str, existing: list[str] | None = None, more: bool = False) -> list[dict[str, Any]]:
    fallback = _keyword_candidates(suite, language, existing, more)
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    services = _suite_services(suite)
    if not services and not brand:
        return fallback
    needs_hebrew = _needs_hebrew_market_terms(suite, language)
    instructions = (
        "Return JSON only: {\"keywords\":[{\"text\":\"...\",\"intent\":\"core|commercial|local|problem|comparison\",\"confidence\":\"medium\"}]}. "
        "Write every keyword in the target audience's native country language and selected audience language. "
        "Each keyword must be a short generic business-search term of 1 to 3 words. It should be useful as part of a search for a business like this Suite. "
        "Use the Suite name only as context to understand the business; do not return the brand/business name, partial brand-name keywords, or modifier phrases combined with the business name. "
        "Base keywords on the business category, services, products, audience needs, and location. "
        "Do not return English keywords unless English is one of the audience languages."
    )
    if needs_hebrew:
        instructions += (
            " IMPORTANT: this business operates in Israel, where customers search Google in BOTH Arabic and Hebrew. "
            "Return each search concept twice — once in Arabic and once as the natural Hebrew term Israelis actually type "
            "(not a literal translation when a different Hebrew term is more common). At least 40% of the keywords must be Hebrew."
        )
    try:
        prompt = {
            "language": language,
            "audience_keyword_languages": _audience_keyword_languages(suite, language),
            "hebrew_market": needs_hebrew,
            "business": {
                "name": brand.get("name") or suite.name,
                "category": brand.get("industry") or brand.get("category") or brand.get("niche"),
                "services": services,
                "audience": brand.get("target_audience") or brand.get("audience_notes"),
                "location": brand.get("location") or brand.get("audience_location"),
            },
            "existing_keywords": existing or [],
            "mode": "generate_more" if more else "generate",
            "instructions": instructions,
        }
        raw = await call_text_ai(
            max_tokens=4000,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            system="You generate practical marketing keywords. Return strict JSON only.",
            timeout=90,
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
        if generated and needs_hebrew:
            hebrew_count = sum(1 for item in generated if _contains_hebrew(item["text"]))
            if hebrew_count < max(4, len(generated) // 3):
                arabic_texts = [item["text"] for item in generated if not _contains_hebrew(item["text"])]
                for text in await _hebrew_planner_terms(arabic_texts, 8):
                    if text.casefold() in existing_markers:
                        continue
                    generated.append({
                        "id": f"kw-{len(generated) + 1}",
                        "text": text,
                        "intent": "core",
                        "source": "ai_hebrew",
                        "confidence": "medium",
                    })
                    existing_markers.add(text.casefold())
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


def _serpapi_country_code(location: str) -> str:
    lowered = str(location or "").casefold()
    if any(item in lowered for item in ("israel", "إسرائيل", "ישראל")):
        return "il"
    if any(item in lowered for item in ("palestine", "فلسطين")):
        return "ps"
    if any(item in lowered for item in ("jordan", "الأردن", "اردن")):
        return "jo"
    if any(item in lowered for item in ("united states", "usa", "us", "أمريكا", "امريكا")):
        return "us"
    if any(item in lowered for item in ("saudi", "السعودية")):
        return "sa"
    if any(item in lowered for item in ("uae", "emirates", "الإمارات", "الامارات")):
        return "ae"
    return ""


def _serpapi_error_message(label: str, exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
            detail = payload.get("error") or payload.get("message") or str(payload)[:180]
        except Exception:
            detail = (getattr(response, "text", "") or str(exc)).split("api_key=")[0][:180]
        status_code = getattr(response, "status_code", "")
        return f"SerpAPI {label} failed{f' ({status_code})' if status_code else ''}: {detail}"
    detail = str(exc).split("api_key=")[0][:180] or type(exc).__name__
    return f"SerpAPI {label} failed: {detail}"


def _competitor_search_terms(suite: Suite, language: str, offset: int = 0) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    category = _clean_search_fragment(brand.get("industry") or brand.get("category") or brand.get("niche") or "")
    location = _clean_search_fragment(brand.get("location") or brand.get("audience_location") or brand.get("audience_country") or "")
    services = _suite_services(suite)
    intelligence = _intelligence(suite)
    keywords = [
        _clean_search_fragment(item.get("text") or item.get("keyword") or "")
        for item in intelligence.get("keywords") or []
        if isinstance(item, dict)
    ]
    base_seed_values = _unique_strings([*keywords[:4], *services[:6], category], 12)
    if _needs_hebrew_market_terms(suite, language):
        hebrew_seed_values = _hebrew_market_terms(base_seed_values, 8)
        seeds = _unique_strings([*base_seed_values[:3], *hebrew_seed_values, *base_seed_values[3:]], 16)
    else:
        seeds = base_seed_values
    seeds = seeds or [_clean_search_fragment(suite.name)]
    rotated = seeds[offset % len(seeds):] + seeds[:offset % len(seeds)]
    terms = []
    for seed in rotated[:8]:
        seed = _clean_search_fragment(seed)
        if not seed:
            continue
        term = " ".join(part for part in [seed, location] if part).strip()
        if term:
            terms.append(term)
        if seed and seed != term:
            terms.append(seed)
    return _unique_strings(terms, 8) or [_clean_search_fragment(suite.name)]


def _competitor_relevance_terms(suite: Suite, language: str, limit: int = 40) -> list[str]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    intelligence = _intelligence(suite)
    raw_terms: list[str] = [
        str(brand.get("industry") or ""),
        str(brand.get("category") or ""),
        str(brand.get("niche") or ""),
        *_suite_services(suite),
        *[
            str(item.get("text") or item.get("keyword") or "")
            for item in intelligence.get("keywords") or []
            if isinstance(item, dict)
        ],
    ]
    brand_markers = _brand_keyword_markers(str(brand.get("name") or suite.name or ""))
    blocked = {
        "best", "services", "service", "company", "business", "near", "nearby",
        "أفضل", "افضل", "خدمات", "شركة", "قريب", "محلي",
        "שירות", "שירותים", "חברה", "קרוב", "מקומי",
    } | brand_markers
    terms: list[str] = []
    for raw in raw_terms:
        phrase = " ".join(str(raw or "").casefold().split())
        if not phrase or phrase in blocked or _mentions_brand_keyword(phrase, str(brand.get("name") or suite.name or "")):
            continue
        terms.append(phrase)
        for token in re.split(r"[\s,،/|()\\[\\]{}:;.!?\\-]+", phrase):
            token = token.strip().casefold()
            if len(token) < 3 or token in blocked:
                continue
            terms.append(token)
    if not terms:
        terms = [item["text"].casefold() for item in _keyword_candidates(suite, language)[:8]]
    return _unique_strings(terms, limit)


def _is_relevant_social_competitor(suite: Suite, language: str, item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "name", "snippet", "reason", "evidence", "offer", "url")
    ).casefold()
    if not haystack:
        return False
    return any(term in haystack for term in _competitor_relevance_terms(suite, language))


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
        url = str(raw.get("link") or raw.get("website") or raw.get("url") or "").strip()
        if "serpapi.com" in url:
            url = ""
        if result_type == "maps" and not url:
            place_id = str(raw.get("place_id") or "").strip()
            if place_id:
                url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
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
            rating = raw.get("rating")
            if isinstance(rating, (int, float)) and 0 < float(rating) <= 5:
                item["rating"] = round(float(rating), 1)
            reviews = raw.get("reviews")
            if isinstance(reviews, (int, float)) and int(reviews) > 0:
                item["reviews"] = int(reviews)
            address = str(raw.get("address") or "").strip()
            if address:
                item["address"] = address
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


def _filter_relevant_competitors(suite: Suite, language: str, source: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if source not in {"instagram", "facebook", "tiktok"}:
        return items
    filtered = [item for item in items if _is_relevant_social_competitor(suite, language, item)]
    return filtered


def _fallback_competitor_for_source(
    suite: Suite,
    language: str,
    source: str,
    existing_markers: set[str],
    offset: int = 0,
) -> dict[str, Any] | None:
    spec = next((item for item in SERPAPI_SOURCE_SPECS if item["result_type"] == source), None)
    if not spec:
        return None
    terms = _competitor_search_terms(suite, language, offset) or [_clean_search_fragment(suite.name)]
    if str(language).startswith("ar"):
        modifiers = ["", "منافسين", "أكاديميات", "شركات"]
    elif str(language).startswith("he"):
        modifiers = ["", "מתחרים", "אקדמיות", "חברות"]
    else:
        modifiers = ["", "competitors", "academy", "companies"]
    fallback_terms = _unique_strings(
        [
            " ".join(part for part in [term, modifier] if part).strip()
            for term in terms
            for modifier in modifiers
        ],
        24,
    )
    term = fallback_terms[offset % len(fallback_terms)] if fallback_terms else _clean_search_fragment(suite.name)
    encoded = term.replace(" ", "+")
    if source == "maps":
        url = f"https://www.google.com/maps/search/{encoded}"
    elif spec.get("site"):
        url = f"https://www.google.com/search?q={spec['site'].replace(':', '%3A')}+{encoded}"
    else:
        url = f"https://www.google.com/search?q={encoded}"
    marker = url or f"{source}:{term}".casefold()
    if marker in existing_markers:
        return None
    existing_markers.add(marker)
    title_prefix = "مصدر بحث" if str(language).startswith("ar") else "Source lead"
    snippet = (
        f"لم تصل نتائج مباشرة كافية من {spec['label']} لهذا المصطلح بعد عدة محاولات. هذا رابط بحث جاهز للمراجعة اليدوية."
        if str(language).startswith("ar")
        else f"Not enough direct {spec['label']} results came back for this term after retries. This is a ready search lead for manual review."
    )
    return {
        "id": f"fallback-{source}-{_stable_slug(term, str(offset + 1))}",
        "name": f"{title_prefix}: {term}",
        "title": f"{title_prefix}: {term}",
        "platform": spec["platform"],
        "result_type": source,
        "url": url,
        "reason": snippet,
        "offer": spec["label"],
        "evidence": term,
        "snippet": snippet,
        "opportunity": "",
        "confidence": "starter",
        "classification_tags": [],
        "research_lead": True,
    }


def _ensure_competitor_source_coverage(
    suite: Suite,
    language: str,
    competitors: list[dict[str, Any]],
    existing_urls: list[str] | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    # A search-lead card is a manual-review pointer, not a competitor: add at
    # most ONE per source, and only when that source produced nothing real.
    minimum_per_source = 1
    counts: dict[str, int] = {}
    for item in competitors:
        if not isinstance(item, dict):
            continue
        source = str(item.get("result_type") or item.get("platform") or "").lower()
        counts[source] = counts.get(source, 0) + 1
    markers = {
        str(item.get("url") or item.get("title") or "").casefold()
        for item in competitors
        if isinstance(item, dict)
    }
    markers.update(str(value or "").casefold() for value in (existing_urls or []) if value)
    filled = list(competitors)
    for index, source in enumerate(["google_organic", "maps", "instagram", "facebook", "tiktok"]):
        source_count = counts.get(source, 0)
        attempts = 0
        while source_count < minimum_per_source and attempts < 4:
            fallback = _fallback_competitor_for_source(suite, language, source, markers, offset + index + attempts)
            attempts += 1
            if not fallback:
                continue
            filled.append(fallback)
            source_count += 1
    return filled


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
    location = _clean_search_fragment(brand.get("location") or brand.get("audience_location") or brand.get("audience_country") or "")
    country_code = _serpapi_country_code(location)
    unique: list[dict[str, Any]] = []
    target_count = 5
    search_terms = terms[:5]
    if spec["engine"] == "google_maps":
        search_terms = [term for term in terms if location and location in term][:3] or terms[:3]
    last_error: Exception | None = None
    for term in search_terms:
        query = term
        if spec.get("site"):
            query = f"{spec['site']} {term}"
        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": spec["engine"],
            "q": query,
            "hl": "ar" if str(language).startswith("ar") else "he" if str(language).startswith("he") else "en",
            "num": 10,
        }
        if country_code:
            params["gl"] = country_code
        if spec["engine"] == "google_maps":
            params["type"] = "search"
        try:
            async with external_call("serpapi", "search", query_type=spec["engine"], country=country_code or None) as call:
                response = await client.get("https://serpapi.com/search.json", params=params)
                call.note(status_code=response.status_code)
                response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # One failing term must not sink the whole source — try the next term.
            last_error = exc
            continue
        candidates = _serpapi_competitors_from_payload(payload, str(spec["result_type"]), 8)
        candidates = _filter_relevant_competitors(suite, language, str(spec["result_type"]), candidates)
        for item in candidates:
            url = str(item.get("url") or "")
            marker = url or str(item.get("title") or "").casefold()
            if marker in existing_urls:
                continue
            existing_urls.add(marker)
            unique.append(item)
            if len(unique) >= target_count:
                return unique
    if not unique and last_error is not None:
        raise last_error
    return unique


_PLACEHOLDER_NAME_MARKERS = ("افتراض", "hypothetical", "generic", "عام (", "(عامة", "example", "מדומה")


def _known_competitor_names(suite: Suite, limit: int = 5) -> list[str]:
    """Competitor names the user/AI already identified (onboarding + brand).

    Placeholder/hypothetical names from onboarding are skipped — searching them
    only surfaces junk matches.
    """
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    strategy = _strategy(suite)
    names: list[str] = []
    for raw in brand.get("competitors") or []:
        if isinstance(raw, str):
            names.append(raw)
        elif isinstance(raw, dict):
            names.append(str(raw.get("name") or ""))
    for raw in (strategy.get("marketing_plan") or {}).get("competitors") or []:
        if isinstance(raw, dict):
            names.append(str(raw.get("name") or ""))
        elif isinstance(raw, str):
            names.append(raw)
    cleaned = []
    for name in names:
        fragment = _clean_search_fragment(name)
        if not fragment or any(marker in fragment.casefold() for marker in _PLACEHOLDER_NAME_MARKERS):
            continue
        cleaned.append(fragment)
    return _unique_strings(cleaned, limit)


def _platform_from_url(url: str) -> str:
    lowered = str(url or "").casefold()
    if "instagram.com" in lowered:
        return "instagram"
    if "tiktok.com" in lowered:
        return "tiktok"
    if "facebook.com" in lowered or "fb.com" in lowered:
        return "facebook"
    if "google.com/maps" in lowered:
        return "maps"
    return "google"


_SUGGEST_COMPETITOR_NAMES_PROMPT = """Suggest real competitors for this business:
{business}

Rules:
- Only ACTUAL existing businesses you are reasonably confident about, serving the same audience — ideally in or near the same city/area.
- No generic placeholders, no made-up names, no global brands unless they truly compete locally.
- 3 to 5 names, each as people would search it (brand name, optionally + city).
- If you cannot name any real local competitor, return the closest real competitors in the same country.

Return STRICT JSON only: {{"names": ["...", "..."]}}"""


async def _suggest_competitor_names(suite: Suite, language: str) -> list[str]:
    """Ask the fast model for likely real competitor names when none are saved."""
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    business = json.dumps(
        {
            "name": brand.get("name") or suite.name,
            "field": brand.get("industry") or brand.get("category") or brand.get("niche"),
            "services": _suite_services(suite)[:8],
            "location": _suite_location(suite),
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        raw = await call_text_ai(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            max_tokens=400,
            messages=[{"role": "user", "content": _SUGGEST_COMPETITOR_NAMES_PROMPT.format(business=business)}],
            system="You know local business markets. Return strict JSON only.",
            timeout=30,
        )
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text).strip()
        parsed = json.loads(text)
        names = [
            _clean_search_fragment(name)
            for name in (parsed.get("names") or [])
            if isinstance(name, str) and name.strip()
        ]
        return _unique_strings(names, 5)
    except Exception as exc:
        log.warning("Competitor name suggestion failed: %s", exc)
        return []


async def _fetch_known_competitors(
    client: httpx.AsyncClient,
    suite: Suite,
    language: str,
    existing_urls: set[str],
    names: list[str] | None = None,
    confidence: str = "known_competitor",
) -> list[dict[str, Any]]:
    """Search the already-identified competitors by NAME — the anchor for relevance."""
    api_key = settings.serpapi_api_key.strip()
    names = names if names is not None else _known_competitor_names(suite)
    if not api_key or not names:
        return []
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    location = _clean_search_fragment(brand.get("location") or brand.get("audience_location") or brand.get("audience_country") or "")
    country_code = _serpapi_country_code(location)
    items: list[dict[str, Any]] = []
    for name in names:
        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "google",
            "q": " ".join(part for part in [name, location] if part),
            "hl": "ar" if str(language).startswith("ar") else "he" if str(language).startswith("he") else "en",
            "num": 6,
        }
        if country_code:
            params["gl"] = country_code
        try:
            async with external_call("serpapi", "search", query_type="google", country=country_code or None) as call:
                response = await client.get("https://serpapi.com/search.json", params=params)
                call.note(status_code=response.status_code)
                response.raise_for_status()
            payload = response.json()
        except Exception:
            continue
        name_tokens = {token for token in name.casefold().split() if len(token) >= 3}
        for raw in (payload.get("organic_results") or [])[:6]:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            url = str(raw.get("link") or "").strip()
            haystack = f"{title} {url}".casefold()
            if not title or not url or not any(token in haystack for token in name_tokens):
                continue
            marker = url or title.casefold()
            if marker in existing_urls:
                continue
            existing_urls.add(marker)
            platform = _platform_from_url(url)
            items.append({
                "id": f"known-{_stable_slug(name, str(len(items) + 1))}-{len(items) + 1}",
                "name": title,
                "title": title,
                "platform": platform,
                "result_type": platform if platform in {"instagram", "facebook", "tiktok", "maps"} else "google_organic",
                "url": url,
                "reason": str(raw.get("snippet") or "").strip(),
                "offer": str(raw.get("displayed_link") or "").strip(),
                "evidence": name,
                "snippet": str(raw.get("snippet") or "").strip(),
                "opportunity": "",
                "confidence": confidence,
                "relevance": "nearby",
                "classification_tags": ["known"] if confidence == "known_competitor" else ["suggested"],
                "research_lead": False,
            })
            if sum(1 for item in items if item["evidence"] == name) >= 2:
                break
    return items


_COMPETITOR_CLASSIFY_PROMPT = """You judge search results for a business's competitor research.

Business:
{business}

For each candidate below, decide:
- "nearby": a REAL competing business serving the same audience in or near the same city/area.
- "real": a real competing business, but not local/nearby.
- "irrelevant": not a competitor — articles, directories, marketplaces, news, job boards, tool/software pages, dictionaries, or businesses in a different field.

Candidates:
{candidates}

Return STRICT JSON only: {{"verdicts": [{{"id": "...", "verdict": "nearby|real|irrelevant"}}]}}
Include every candidate id exactly once."""


async def _classify_competitor_candidates(
    suite: Suite,
    language: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """AI relevance pass: keep nearby + real competitors, drop everything else.

    Known-competitor and research-lead items skip classification. On AI failure
    the items pass through unchanged so the flow never hard-fails.
    """
    to_classify = [
        item for item in items
        if isinstance(item, dict)
        and not item.get("research_lead")
        and item.get("confidence") not in {"mock", "starter"}
    ]
    if not to_classify:
        return items
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    business = json.dumps(
        {
            "name": brand.get("name") or suite.name,
            "field": brand.get("industry") or brand.get("category") or brand.get("niche"),
            "services": _suite_services(suite)[:8],
            "location": brand.get("location") or brand.get("audience_location"),
        },
        ensure_ascii=False,
        default=str,
    )
    candidates = json.dumps(
        [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "snippet": (str(item.get("snippet") or ""))[:200],
                "url": item.get("url"),
            }
            for item in to_classify[:40]
        ],
        ensure_ascii=False,
    )
    verdicts: dict[str, str] = {}
    try:
        raw = await call_text_ai(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            max_tokens=1500,
            messages=[{"role": "user", "content": _COMPETITOR_CLASSIFY_PROMPT.format(business=business, candidates=candidates)}],
            system="You classify competitor search results. Return strict JSON only.",
            timeout=45,
        )
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text).strip()
        parsed = json.loads(text)
        for entry in parsed.get("verdicts") or []:
            if isinstance(entry, dict) and entry.get("id"):
                verdicts[str(entry["id"])] = str(entry.get("verdict") or "").strip().lower()
    except Exception as exc:
        log.warning("Competitor relevance classification failed: %s", exc)
        return items

    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        verdict = verdicts.get(str(item.get("id") or ""))
        if verdict is None:
            kept.append(item)
            continue
        if verdict == "irrelevant":
            continue
        item["relevance"] = "nearby" if verdict == "nearby" else "real"
        kept.append(item)

    order = {"nearby": 0, "real": 1}
    kept.sort(
        key=lambda item: (
            0 if item.get("confidence") == "known_competitor" else 1,
            order.get(str(item.get("relevance") or ""), 2),
        )
    )
    return kept


_WEB_SEARCH_COMPETITOR_QUERIES = (
    ("instagram", "site:instagram.com"),
    ("facebook", "site:facebook.com"),
    ("tiktok", "site:tiktok.com"),
    ("google_organic", ""),
)


async def _web_search_competitors(
    suite: Suite,
    language: str,
    existing_urls: set[str],
) -> list[dict[str, Any]]:
    """Free DDG/Google HTML search — the engine that powers the dashboard
    market-research section, added here as a parallel competitor source."""
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    niche = _clean_search_fragment(
        brand.get("niche") or brand.get("industry") or brand.get("category") or (_suite_services(suite) or [""])[0]
    )
    location = _suite_location(suite)
    if not niche:
        return []
    queries = [
        (result_type, " ".join(part for part in [site, niche, location] if part))
        for result_type, site in _WEB_SEARCH_COMPETITOR_QUERIES
    ]
    batches = await asyncio.gather(
        *[search_web(query, 6) for _result_type, query in queries],
        return_exceptions=True,
    )
    items: list[dict[str, Any]] = []
    for (result_type, _query), batch in zip(queries, batches):
        if not isinstance(batch, list):
            continue
        for raw in batch:
            url = str(raw.get("url") or "").strip()
            title = str(raw.get("title") or "").strip()
            marker = url or title.casefold()
            if not title or not url or marker in existing_urls:
                continue
            existing_urls.add(marker)
            platform = str(raw.get("platform") or "web")
            items.append({
                "id": f"web-{result_type}-{_stable_slug(title, str(len(items) + 1))}",
                "name": title,
                "title": title,
                "platform": platform if platform != "web" else "google",
                "result_type": result_type if result_type != "google_organic" else (
                    platform if platform in {"instagram", "facebook", "tiktok"} else "google_organic"
                ),
                "url": url,
                "reason": str(raw.get("snippet") or "").strip(),
                "offer": "",
                "evidence": niche,
                "snippet": str(raw.get("snippet") or "").strip(),
                "opportunity": "",
                "confidence": "web_search",
                "classification_tags": [],
                "research_lead": False,
            })
    return items


async def _serpapi_competitors(suite: Suite, language: str, existing_urls: list[str] | None = None, offset: int = 0) -> tuple[list[dict[str, Any]], list[str]]:
    existing = {url for url in (existing_urls or []) if url}
    competitors: list[dict[str, Any]] = []
    warnings: list[str] = []
    has_serpapi = bool(settings.serpapi_api_key.strip())
    if not has_serpapi:
        warnings.append("SERPAPI_API_KEY is not configured on the API service.")

    names = _known_competitor_names(suite)
    names_confidence = "known_competitor"
    if not names:
        names = await _suggest_competitor_names(suite, language)
        names_confidence = "ai_suggested"

    async with httpx.AsyncClient(timeout=25) as client:
        tasks: list[tuple[str, Any]] = [
            ("web search", _web_search_competitors(suite, language, existing)),
        ]
        if has_serpapi:
            tasks.append(
                ("known competitors", _fetch_known_competitors(client, suite, language, existing, names, names_confidence))
            )
            tasks.extend(
                (spec["label"], _fetch_serpapi_source(client, suite, language, spec, existing, offset + index))
                for index, spec in enumerate(SERPAPI_SOURCE_SPECS)
            )
        results = await asyncio.gather(*[task for _label, task in tasks], return_exceptions=True)
    for (label, _task), result in zip(tasks, results):
        if isinstance(result, Exception):
            warnings.append(_serpapi_error_message(label, result))
            continue
        items = result if isinstance(result, list) else []
        competitors.extend(items[:8])
        if not items and label not in ("web search", "known competitors"):
            warnings.append(f"SerpAPI returned no usable {label} results.")
    competitors = await _classify_competitor_candidates(suite, language, competitors)
    return competitors, _combine_serpapi_warnings(warnings)


def _combine_serpapi_warnings(warnings: list[str]) -> list[str]:
    """Merge identical SerpAPI failures across sources into a single line."""
    grouped: dict[tuple[str, str], list[str]] = {}
    passthrough: list[str] = []
    for warning in warnings:
        match = re.match(r"^SerpAPI (.+?) failed(?: \((\d+)\))?: (.*)$", warning)
        if not match:
            passthrough.append(warning)
            continue
        label, code, detail = match.groups()
        grouped.setdefault((code or "", detail.strip()), []).append(label)
    combined: list[str] = []
    for (code, detail), source_labels in grouped.items():
        prefix = f"SerpAPI ({', '.join(source_labels)})" if len(source_labels) > 1 else f"SerpAPI {source_labels[0]}"
        combined.append(f"{prefix} failed{f' ({code})' if code else ''}: {detail}")
    return passthrough + combined


def _save_competitor_scratch(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    intelligence = normalize_marketing_intelligence({"phase": "competitors"}, suite_research_payload(suite), output_language)
    intelligence["competitors"] = _mock_competitors(suite, output_language)
    intelligence["status"] = "competitors_ready"
    return _save_marketing_intelligence(suite, intelligence)


async def _save_competitor_scratch_from_search(suite: Suite, language: str | None = None) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    existing = _strategy(suite).get("marketing_intelligence")
    existing_payload = existing if isinstance(existing, dict) else {}
    intelligence = normalize_marketing_intelligence(
        {**existing_payload, "phase": "competitors", "warnings": []},
        suite_research_payload(suite),
        output_language,
    )
    competitors, serpapi_warnings = await _serpapi_competitors(suite, output_language)
    competitors = _ensure_competitor_source_coverage(suite, output_language, competitors)
    if serpapi_warnings:
        # Source-level failures are platform concerns, not user errors: log for
        # the admin and keep them out of the visible response.
        log.error("Competitor source warnings for suite %s: %s", suite.id, " | ".join(serpapi_warnings[:6]))
    if competitors:
        intelligence["competitors"] = competitors
        intelligence["warnings"] = []
        intelligence["suppress_starter_warnings"] = True
        intelligence["source_warnings"] = []
    else:
        intelligence["competitors"] = []
        intelligence["warnings"] = [
            "SerpAPI did not return usable direct competitor results.",
        ]
        intelligence["source_warnings"] = []
    intelligence["internal_source_warnings"] = serpapi_warnings[:6]
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
    more, serpapi_warnings = await _serpapi_competitors(suite, output_language, existing_urls, offset=len(current))
    more = _ensure_competitor_source_coverage(suite, output_language, more, existing_urls, offset=len(current))
    if serpapi_warnings:
        log.error("Competitor source warnings for suite %s: %s", suite.id, " | ".join(serpapi_warnings[:6]))
    if not more:
        more = []
        base["warnings"] = [
            "SerpAPI did not return additional direct competitor results.",
        ]
    else:
        base["warnings"] = []
    base["suppress_starter_warnings"] = True
    base["source_warnings"] = []
    base["internal_source_warnings"] = serpapi_warnings[:6]
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


def _demand_supply_unavailable_signals(planner: dict[str, Any], language: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    warning = str(planner.get("warning") or "").strip()
    ar = str(language).startswith("ar")
    if ar:
        demand = "لا توجد أرقام طلب من Keyword Planner بعد. مصدر Google Ads المركزي يُدار داخليًا من المنصة."
        supply = "لا توجد كثافة منافسة فعلية بعد لأن Google Ads لم يرجع Metrics قابلة للاستخدام."
        opportunity = warning or "بعد جاهزية المصدر المركزي، أعد التوليد لعرض البحث الشهري، المنافسة، واقتراحات الكلمات."
    else:
        demand = "No Keyword Planner demand metrics yet. The platform-managed Google Ads source is handled internally."
        supply = "No real competition density yet because Google Ads did not return usable metrics."
        opportunity = warning or "After the platform source is ready, regenerate to show monthly searches, competition, and keyword suggestions."
    return (
        [{"id": "google-ads-demand-unavailable", "title": demand, "source": "google_ads"}],
        [{"id": "google-ads-competition-unavailable", "title": supply, "source": "google_ads"}],
        [{"id": "google-ads-next-step", "title": opportunity, "source": "google_ads"}],
    )


def _missing_platform_google_ads_config() -> list[str]:
    customer_id = settings.google_ads_customer_id or settings.google_ads_login_customer_id
    required = {
        "GOOGLE_ADS_CUSTOMER_ID": customer_id,
        "GOOGLE_ADS_REFRESH_TOKEN": settings.google_ads_refresh_token,
        "GOOGLE_ADS_CLIENT_ID": settings.google_ads_client_id,
        "GOOGLE_ADS_CLIENT_SECRET": settings.google_ads_client_secret,
        "GOOGLE_ADS_DEVELOPER_TOKEN": settings.google_ads_developer_token,
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _google_ads_keyword_planner_credentials() -> tuple[str, str, str, list[str]]:
    missing = _missing_platform_google_ads_config()
    if missing:
        return "", "", "platform_missing", missing
    return (
        str(settings.google_ads_customer_id or settings.google_ads_login_customer_id or "").strip(),
        str(settings.google_ads_refresh_token or "").strip(),
        "platform",
        [],
    )


def _platform_google_ads_missing_warning(missing: list[str], language: str) -> str:
    missing_text = ", ".join(missing)
    if str(language).startswith("ar"):
        return f"إعداد Google Ads المركزي ناقص على خدمة API: {missing_text}. أضف هذه المتغيرات على خدمة الباكند في Railway ثم أعد النشر."
    return f"Google Ads platform configuration is missing on the API service: {missing_text}. Add these variables to the backend service in Railway, then redeploy."


def _public_demand_supply_warning(warning: str | None, language: str, credential_source: str) -> str | None:
    if not warning:
        return None
    marker = str(warning).casefold()
    if str(language).startswith("ar"):
        if "user_permission_denied" in marker or "does not have permission" in marker:
            return "حساب Google Ads المركزي لا يملك صلاحية على حساب الإعلانات المستخدم لقراءة Keyword Planner. حدّث GOOGLE_ADS_CUSTOMER_ID أو GOOGLE_ADS_LOGIN_CUSTOMER_ID لحساب يملك صلاحية، ثم أعد النشر."
        if "unsupported_version" in marker or "version" in marker and "deprecated" in marker:
            return "نسخة Google Ads API المستخدمة غير مدعومة حاليًا. حدّث خدمة الباكند ثم أعد التوليد."
    if credential_source in {"platform", "platform_missing"}:
        return str(warning)
    missing_connection = "account is not connected" in marker or "refresh_token" in marker or "customer_id" in marker
    if credential_source == "platform" and not missing_connection:
        return str(warning)
    if str(language).startswith("ar"):
        return "مصدر بيانات العرض والطلب غير جاهز داخليًا بعد. سنعرض تقديرًا تمهيديًا الآن، وبعد تفعيل مصدر Google Ads المركزي ستظهر أرقام البحث والمنافسة."
    return "The internal demand and supply data source is not ready yet. We are showing a starter estimate now; once the platform Google Ads source is active, search and competition metrics will appear."


def _merge_keyword_planner_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    warnings: list[str] = []
    request_languages: list[Any] = []
    seen_metrics: set[str] = set()
    seen_suggestions: set[str] = set()
    for result in results:
        request = result.get("request") if isinstance(result.get("request"), dict) else {}
        if request.get("language"):
            request_languages.append(request.get("language"))
        for item in result.get("keyword_metrics") or []:
            if not isinstance(item, dict):
                continue
            marker = str(item.get("keyword") or "").casefold()
            if not marker or marker in seen_metrics:
                continue
            seen_metrics.add(marker)
            metrics.append(item)
        for item in result.get("suggested_keywords") or []:
            if not isinstance(item, dict):
                continue
            marker = str(item.get("keyword") or "").casefold()
            if not marker or marker in seen_suggestions:
                continue
            seen_suggestions.add(marker)
            suggestions.append(item)
        if result.get("warning"):
            warnings.append(str(result["warning"]))
    summary = build_keyword_planner_summary(metrics)
    summary["suggested_keywords"] = len(suggestions)
    return {
        "keyword_metrics": metrics,
        "suggested_keywords": suggestions[:30],
        "summary": summary,
        "request": {
            "languages": _unique_strings(request_languages, 4),
            "attempts": len(results),
        },
        "warning": "; ".join(_unique_strings(warnings, 3)) if warnings and not metrics else None,
    }


async def _fetch_keyword_planner_ideas_logged(
    customer_id: Any,
    refresh_token: Any,
    seed_terms: list[str],
    language: str,
    location: Any,
    website: Any,
) -> dict[str, Any]:
    """fetch_keyword_planner_ideas with one external-call log line per request."""
    async with external_call(
        "google-ads",
        "keyword_ideas",
        language=language,
        location=str(location or "") or None,
        seed_count=len(seed_terms or []),
    ) as call:
        result = await fetch_keyword_planner_ideas(customer_id, refresh_token, seed_terms, language, location, website)
        if isinstance(result, dict) and result.get("warning") and not result.get("keyword_metrics"):
            call.fail(result["warning"])
        return result


async def _social_demand_snapshot(suite: Suite) -> dict[str, Any]:
    """Social-side demand: how many audience interests exist as Meta Ads
    targeting interests, and how big their combined audience is."""
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    interests = [str(item).strip() for item in (brand.get("audience_interests") or []) if str(item).strip()]
    if not interests:
        return {"provider": "meta_ads_interest_search", "level": "UNKNOWN", "checked": 0, "matched": 0, "audience_size": 0, "matches": []}
    english_terms = await _english_planner_terms(interests, 10)
    snapshot = await match_meta_interests(english_terms or interests[:10])
    if snapshot.get("level") == "UNKNOWN" and snapshot.get("internal_warning"):
        # Meta unavailable — estimate from how rich the audience definition is.
        log.error("Meta interest search unavailable for suite %s: %s", suite.id, snapshot.get("internal_warning"))
        snapshot["level"] = "MEDIUM" if len(interests) >= 6 else "LOW"
        snapshot["source"] = "estimate"
    return snapshot


async def _save_demand_supply_from_google_ads(suite: Suite, language: str | None = None, more: bool = False) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    existing = _strategy(suite).get("marketing_intelligence")
    base = existing if isinstance(existing, dict) else {"phase": "competitors"}
    base = normalize_marketing_intelligence(base, suite_research_payload(suite), output_language)
    customer_id, refresh_token, credential_source, missing_config = _google_ads_keyword_planner_credentials()
    previous = base.get("demand_supply") if isinstance(base.get("demand_supply"), dict) else {}
    previous_metrics = [item for item in (previous.get("keyword_metrics") or []) if isinstance(item, dict)] if more else []
    previous_suggestions = [item for item in (previous.get("suggested_keywords") or []) if isinstance(item, dict)] if more else []
    checked_terms = _unique_strings([str(term) for term in previous.get("checked_terms") or []], 200) if more else []
    checked = {term.casefold() for term in checked_terms}
    keyword_pool, service_pool = _demand_supply_seed_pools(suite, output_language)
    selected_keywords, selected_services, remaining_terms = _demand_supply_seed_selection(keyword_pool, service_pool, checked)
    planner_keywords = _unique_strings([*selected_keywords, *selected_services], 10)
    if missing_config:
        planner = {
            "keyword_metrics": [],
            "suggested_keywords": [],
            "summary": build_keyword_planner_summary([]),
            "request": {"attempts": 0, "missing_config": missing_config},
            "warning": _platform_google_ads_missing_warning(missing_config, output_language),
        }
    elif not planner_keywords:
        summary = build_keyword_planner_summary(previous_metrics)
        summary["suggested_keywords"] = len(previous_suggestions)
        planner = {
            "keyword_metrics": previous_metrics,
            "suggested_keywords": previous_suggestions,
            "summary": summary,
            "request": {"attempts": 0},
            "warning": None if previous_metrics else "No keywords or services are available yet to check in Keyword Planner.",
        }
    elif _is_global_market(suite):
        # Worldwide suite: translate the seeds to English and check demand in
        # several economically leading markets, then merge the results.
        english_terms = await _english_planner_terms(planner_keywords, 10)
        seed_terms = english_terms or planner_keywords
        website = _suite_website_url(suite)
        raw_results = await asyncio.gather(
            *[
                _fetch_keyword_planner_ideas_logged(customer_id, refresh_token, seed_terms, "en", market, website)
                for market in GLOBAL_PLANNER_MARKETS
            ],
            return_exceptions=True,
        )
        planner_results = [result for result in raw_results if isinstance(result, dict)]
        if not planner_results:
            first_error = next((result for result in raw_results if isinstance(result, Exception)), None)
            planner_results = [{
                "keyword_metrics": [],
                "suggested_keywords": [],
                "summary": build_keyword_planner_summary([]),
                "request": {},
                "warning": str(first_error) if first_error else "Keyword Planner returned no results for the global markets.",
            }]
        if previous_metrics or previous_suggestions:
            planner_results.insert(0, {"keyword_metrics": previous_metrics, "suggested_keywords": previous_suggestions, "request": {}})
        planner = _merge_keyword_planner_results(planner_results)
        planner.setdefault("request", {})["global_markets"] = list(GLOBAL_PLANNER_MARKETS)
        planner["request"]["english_seeds"] = seed_terms
    else:
        needs_hebrew = _needs_hebrew_market_terms(suite, output_language)
        primary_keywords = [keyword for keyword in planner_keywords if not _contains_hebrew(keyword)] or planner_keywords
        planner_results = [
            await _fetch_keyword_planner_ideas_logged(
                customer_id,
                refresh_token,
                primary_keywords,
                output_language,
                _suite_location(suite),
                _suite_website_url(suite),
            )
        ]
        hebrew_terms = await _hebrew_planner_terms(planner_keywords, 10) if needs_hebrew else []
        if needs_hebrew and (hebrew_terms or _suite_website_url(suite)):
            planner_results.append(
                await _fetch_keyword_planner_ideas_logged(
                    customer_id,
                    refresh_token,
                    hebrew_terms,
                    "he",
                    _suite_location(suite),
                    _suite_website_url(suite),
                )
            )
        if previous_metrics or previous_suggestions:
            planner_results.insert(0, {"keyword_metrics": previous_metrics, "suggested_keywords": previous_suggestions, "request": {}})
        planner = _merge_keyword_planner_results(planner_results)
    summary = planner.get("summary") or {}
    warnings: list[str] = []
    public_warning = _public_demand_supply_warning(planner.get("warning"), output_language, credential_source)
    has_keyword_metrics = bool(planner.get("keyword_metrics"))
    demand_title = (
        f"متوسط البحث الشهري: {summary.get('average_monthly_searches', 0)}"
        if str(output_language).startswith("ar")
        else f"Average monthly searches: {summary.get('average_monthly_searches', 0)}"
    )
    competition_title = (
        f"المنافسة: {summary.get('competition_level', 'UNKNOWN')}"
        if str(output_language).startswith("ar")
        else f"Competition: {summary.get('competition_level', 'UNKNOWN')}"
    )
    pressure_title = (
        f"ضغط السوق: {summary.get('market_pressure_score', 0)}/100"
        if str(output_language).startswith("ar")
        else f"Market pressure: {summary.get('market_pressure_score', 0)}/100"
    )
    fallback_planner = {**planner, "warning": public_warning}
    fallback_demand, fallback_supply, fallback_opportunities = _demand_supply_unavailable_signals(fallback_planner, output_language)
    intelligence = {
        **base,
        "phase": "demand_supply",
        "status": "demand_supply_ready",
        "language": output_language,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competitors": base.get("competitors") or [],
        "demand_signals": [{"id": "google-ads-demand", "title": demand_title, "source": "google_ads"}] if has_keyword_metrics else fallback_demand,
        "supply_signals": [{"id": "google-ads-competition", "title": competition_title, "source": "google_ads"}] if has_keyword_metrics else fallback_supply,
        "opportunities": [{"id": "google-ads-pressure", "title": pressure_title, "source": "google_ads"}] if has_keyword_metrics else fallback_opportunities,
        "warnings": warnings,
    }
    intelligence["demand_supply"] = {
        "provider": "google_ads_keyword_planner",
        "summary": summary,
        "keyword_metrics": planner.get("keyword_metrics") or [],
        "suggested_keywords": planner.get("suggested_keywords") or [],
        "request": planner.get("request") or {},
        "warning": public_warning,
        "internal_warning": planner.get("warning"),
        "credential_source": credential_source,
        "missing_config": missing_config,
        "checked_terms": _unique_strings([*checked_terms, *planner_keywords], 200),
        "remaining_terms": remaining_terms,
        "last_seeds": {"keywords": selected_keywords, "services": selected_services},
    }
    previous_social = previous.get("social") if isinstance(previous.get("social"), dict) else None
    if more and previous_social and previous_social.get("matched"):
        intelligence["demand_supply"]["social"] = previous_social
    else:
        try:
            intelligence["demand_supply"]["social"] = await _social_demand_snapshot(suite)
        except Exception as exc:  # social snapshot must never sink the Google side
            log.error("Social demand snapshot failed for suite %s: %s", suite.id, exc)
            if previous_social:
                intelligence["demand_supply"]["social"] = previous_social
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
        "visuals": deck_visuals(suite),
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
    await _sync_social_plan_generation(db, suite)
    deck = _deck(suite)
    job = await _latest_marketing_plan_job(db, suite_id)
    if not deck:
        return _marketing_plan_response(suite, suite_id, job, "missing")
    return _marketing_plan_response(suite, suite_id, job, "ready")


@router.post("/suites/{suite_id}/marketing-plan/visuals/generate")
async def generate_marketing_plan_visuals(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate the plan's field images once — shared by the plan page and the PDF."""
    await enforce_funnel_call_limit(db, current_user, "marketing_plan_visuals", 1)
    suite = await get_owned_suite(db, suite_id, current_user)
    visuals = await ensure_marketing_plan_visuals(suite)
    if visuals:
        await db.commit()
    return {"visuals": visuals}


@router.get("/suites/{suite_id}/marketing-plan/pdf")
async def download_marketing_plan_pdf(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    try:
        visuals = await ensure_marketing_plan_visuals(suite)
        if visuals:
            await db.commit()
    except Exception:
        log.warning("Marketing plan visuals generation failed; exporting PDF without images", exc_info=True)
    pdf_bytes, filename = build_marketing_plan_pdf(suite)
    await record_audit_log(
        db,
        action="marketing.pdf.download",
        resource_type="marketing_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"filename": filename, "bytes": len(pdf_bytes)},
    )
    await db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/suites/{suite_id}/marketing-plan/generate")
async def generate_marketing_plan(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    block_funnel_regeneration(current_user, already_generated=bool(_deck(suite)))
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
    await enforce_funnel_call_limit(db, current_user, "marketing_competitors", 2)
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    await _save_competitor_scratch_from_search(suite, request_data.language)
    intelligence = _intelligence(suite)
    await record_provider_usage(
        db,
        provider="serpapi",
        operation="marketing_competitors.generate",
        endpoint="search.json",
        status="partial" if intelligence.get("source_warnings") or intelligence.get("warnings") else "success",
        actual_cost_usd=estimate_serpapi_cost_usd(len(SERPAPI_SOURCE_SPECS)),
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "search_count": len(SERPAPI_SOURCE_SPECS),
            "cost_basis": "configured_per_search" if settings.serpapi_cost_per_search_usd else "missing_serpapi_unit_cost",
            "competitors": len(intelligence.get("competitors") or []),
            "warnings": list(intelligence.get("source_warnings") or intelligence.get("warnings") or [])[:5],
        },
    )
    await record_audit_log(
        db,
        action="marketing.competitors.generate",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"competitors": len(intelligence.get("competitors") or [])},
    )
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
    intelligence = _intelligence(suite)
    await record_provider_usage(
        db,
        provider="serpapi",
        operation="marketing_competitors.generate_more",
        endpoint="search.json",
        status="partial" if intelligence.get("source_warnings") or intelligence.get("warnings") else "success",
        actual_cost_usd=estimate_serpapi_cost_usd(len(SERPAPI_SOURCE_SPECS)),
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "search_count": len(SERPAPI_SOURCE_SPECS),
            "cost_basis": "configured_per_search" if settings.serpapi_cost_per_search_usd else "missing_serpapi_unit_cost",
            "competitors": len(intelligence.get("competitors") or []),
            "warnings": list(intelligence.get("source_warnings") or intelligence.get("warnings") or [])[-5:],
        },
    )
    await record_audit_log(
        db,
        action="marketing.competitors.generate_more",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"competitors": len(intelligence.get("competitors") or [])},
    )
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
    tags = _normalize_competitor_tags(payload.classification_tags)
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
    await record_audit_log(
        db,
        action="marketing.competitor.update",
        resource_type="marketing_competitor",
        resource_id=competitor_id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"classification_tags": tags},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.patch("/suites/{suite_id}/marketing-plan/competitors")
async def update_marketing_competitors(
    suite_id: str,
    payload: MarketingCompetitorsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    output_language = infer_plan_language(suite)
    existing_payload = _strategy(suite).get("marketing_intelligence")
    existing_payload = existing_payload if isinstance(existing_payload, dict) else {}
    intelligence = normalize_marketing_intelligence(
        {
            **existing_payload,
            "phase": "competitors",
        },
        suite_research_payload(suite),
        output_language,
    )
    preserved = normalize_marketing_intelligence(existing_payload, suite_research_payload(suite), output_language) if existing_payload else {}
    for key in (
        "keywords",
        "demand_signals",
        "supply_signals",
        "opportunities",
        "personas",
        "source_links",
        "warnings",
        "source_warnings",
        "demand_supply",
        "suppress_starter_warnings",
    ):
        if key in existing_payload:
            intelligence[key] = preserved.get(key, existing_payload.get(key))

    saved_competitors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, competitor in enumerate(payload.competitors):
        name = re.sub(r"\s+", " ", competitor.name).strip()
        title = re.sub(r"\s+", " ", competitor.title or name).strip()
        result_type = re.sub(r"\s+", "_", competitor.result_type or competitor.platform or "other").strip().lower() or "other"
        platform = re.sub(r"\s+", "_", competitor.platform or result_type).strip().lower() or result_type
        url = str(competitor.url or "").strip()
        marker = (url or f"{result_type}:{name}").casefold()
        if not name or marker in seen:
            continue
        seen.add(marker)
        item: dict[str, Any] = {
            "id": competitor.id or f"competitor-manual-{secrets.token_urlsafe(6)}",
            "name": name,
            "title": title,
            "platform": platform,
            "result_type": result_type,
            "url": url,
            "snippet": str(competitor.snippet or competitor.reason or competitor.evidence or "").strip(),
            "reason": str(competitor.reason or "").strip(),
            "evidence": str(competitor.evidence or "").strip(),
            "offer": str(competitor.offer or "").strip(),
            "opportunity": str(competitor.opportunity or "").strip(),
            "confidence": competitor.confidence or "manual",
            "research_lead": bool(competitor.research_lead),
            "classification_tags": _normalize_competitor_tags(competitor.classification_tags),
            "position": index,
        }
        if competitor.relevance and competitor.relevance.strip().lower() in {"nearby", "real"}:
            item["relevance"] = competitor.relevance.strip().lower()
        if competitor.rating is not None and competitor.rating > 0:
            item["rating"] = round(competitor.rating, 1)
        if competitor.reviews:
            item["reviews"] = competitor.reviews
        if competitor.address and competitor.address.strip():
            item["address"] = competitor.address.strip()
        saved_competitors.append(item)

    intelligence["competitors"] = saved_competitors[:80]
    intelligence["status"] = "competitors_ready" if saved_competitors else intelligence.get("status") or "missing"
    intelligence["generated_at"] = datetime.now(timezone.utc).isoformat()
    _save_marketing_intelligence(suite, intelligence)
    await record_audit_log(
        db,
        action="marketing.competitors.update",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"competitors": len(saved_competitors)},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/keywords/generate")
async def generate_marketing_keywords(
    suite_id: str,
    payload: MarketingStageRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_funnel_call_limit(db, current_user, "marketing_keywords", 2)
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
    await record_provider_usage(
        db,
        provider=settings.ai_text_provider,
        operation="marketing_keywords.generate",
        model=settings.openai_text_model if settings.ai_text_provider == "openai" else settings.anthropic_text_model,
        status="success",
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={"keywords": len(keywords), "language": output_language, "cost_basis": "missing_provider_usage"},
    )
    await record_audit_log(
        db,
        action="marketing.keywords.generate",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"keywords": len(keywords)},
    )
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
    await record_audit_log(
        db,
        action="marketing.keywords.generate_more",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"keywords": len(current)},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.patch("/suites/{suite_id}/marketing-plan/keywords")
async def update_marketing_keywords(
    suite_id: str,
    payload: MarketingKeywordsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    output_language = infer_plan_language(suite)
    existing_payload = _strategy(suite).get("marketing_intelligence")
    existing_payload = existing_payload if isinstance(existing_payload, dict) else {}
    intelligence = normalize_marketing_intelligence(
        {
            **existing_payload,
            "phase": "keywords",
        },
        suite_research_payload(suite),
        output_language,
    )
    preserved = normalize_marketing_intelligence(existing_payload, suite_research_payload(suite), output_language) if existing_payload else {}
    for key in (
        "competitors",
        "demand_signals",
        "supply_signals",
        "opportunities",
        "personas",
        "source_links",
        "warnings",
        "source_warnings",
        "demand_supply",
        "suppress_starter_warnings",
    ):
        if key in existing_payload:
            intelligence[key] = preserved.get(key, existing_payload.get(key))
    saved_keywords: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, keyword in enumerate(payload.keywords):
        text = re.sub(r"\s+", " ", keyword.text).strip()
        marker = text.casefold()
        if not text or marker in seen:
            continue
        seen.add(marker)
        saved_keywords.append(
            {
                "id": keyword.id or f"kw-manual-{secrets.token_urlsafe(6)}",
                "text": text,
                "intent": keyword.intent or "manual",
                "source": keyword.source or "manual",
                "confidence": keyword.confidence or "manual",
                "position": index,
            }
        )
    intelligence["keywords"] = saved_keywords[:80]
    intelligence["status"] = "keywords_ready" if saved_keywords else intelligence.get("status") or "missing"
    intelligence["generated_at"] = datetime.now(timezone.utc).isoformat()
    _save_marketing_intelligence(suite, intelligence)
    await record_audit_log(
        db,
        action="marketing.keywords.update",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"keywords": len(saved_keywords)},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.patch("/suites/{suite_id}/marketing-plan/message")
async def update_marketing_message(
    suite_id: str,
    payload: MarketingMessageUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually edit the marketing message. A user rewriting their own copy is
    not an AI regeneration, so the funnel one-shot guard does not apply here."""
    suite = await get_owned_suite(db, suite_id, current_user)
    message = re.sub(r"[ \t]+\n", "\n", payload.message).strip()
    _save_marketing_message(suite, message)
    await record_audit_log(
        db,
        action="marketing.message.update",
        resource_type="marketing_message",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"length": len(message)},
    )
    await db.commit()
    return {"marketing_message": message}


async def _run_demand_supply_generation(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None,
    current_user: User,
    db: AsyncSession,
    more: bool = False,
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    await _save_demand_supply_from_google_ads(suite, request_data.language, more=more)
    intelligence = _intelligence(suite)
    demand_supply = intelligence.get("demand_supply") if isinstance(intelligence.get("demand_supply"), dict) else {}
    summary = demand_supply.get("summary") if isinstance(demand_supply.get("summary"), dict) else {}
    operation_suffix = "generate_more" if more else "generate"
    await record_provider_usage(
        db,
        provider="google",
        operation=f"marketing_demand_supply.{operation_suffix}",
        model="Google Ads Keyword Planner",
        endpoint="google_ads.keyword_plan_idea_service",
        status="warning" if demand_supply.get("warning") else "success",
        actual_cost_usd=estimate_google_ads_keyword_planner_cost_usd(1),
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "request_count": 1,
            "cost_basis": "configured_per_request" if settings.google_ads_keyword_planner_cost_usd else "no_direct_api_cost_configured",
            "analyzed_keywords": summary.get("analyzed_keywords"),
            "suggested_keywords": summary.get("suggested_keywords"),
            "warning": demand_supply.get("warning"),
            "credential_source": demand_supply.get("credential_source"),
            "missing_config": demand_supply.get("missing_config"),
            "remaining_terms": demand_supply.get("remaining_terms"),
            "last_seeds": demand_supply.get("last_seeds"),
        },
    )
    await record_audit_log(
        db,
        action=f"marketing.demand_supply.{operation_suffix}",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"summary": summary},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/demand-supply/generate")
async def generate_marketing_demand_supply(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_funnel_call_limit(db, current_user, "marketing_demand_supply", 2)
    return await _run_demand_supply_generation(suite_id, payload, current_user, db, more=False)


@router.post("/suites/{suite_id}/marketing-plan/demand-supply/generate-more")
async def generate_more_marketing_demand_supply(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _run_demand_supply_generation(suite_id, payload, current_user, db, more=True)


@router.post("/suites/{suite_id}/marketing-plan/personas/generate")
async def generate_marketing_personas(
    suite_id: str,
    payload: MarketingStageRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Personas stream in batches of 2 up to 10, so the funnel cap covers one full run.
    await enforce_funnel_call_limit(db, current_user, "marketing_personas", 6)
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or MarketingStageRequest()
    output_language = infer_plan_language(suite, request_data.language)
    existing_values = _unique_strings(request_data.existing_values, limit=20)
    append = bool(existing_values)
    intelligence = await generate_marketing_customer_personas_research(
        suite,
        output_language,
        count=request_data.count,
        existing_persona_values=existing_values,
        append=append,
    )
    _save_marketing_intelligence(suite, intelligence)
    personas = intelligence.get("personas") if isinstance(intelligence.get("personas"), list) else []
    await record_provider_usage(
        db,
        provider=settings.ai_text_provider,
        operation="marketing_personas.generate_more" if append else "marketing_personas.generate",
        model=settings.openai_text_model if settings.ai_text_provider == "openai" else settings.anthropic_text_model,
        status="success",
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "personas": len(personas),
            "batch_size": 5,
            "append": append,
            "language": output_language,
            "cost_basis": "missing_provider_usage",
        },
    )
    await record_audit_log(
        db,
        action="marketing.personas.generate_more" if append else "marketing.personas.generate",
        resource_type="marketing_intelligence",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"personas": len(personas), "batch_size": 5, "append": append},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "market_ready")


@router.post("/suites/{suite_id}/marketing-plan/social-content-plan/generate")
async def generate_marketing_social_content_plan(
    suite_id: str,
    payload: GenerateSocialContentPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    block_funnel_regeneration(
        current_user,
        already_generated=bool((_action_plan(suite) or {}).get("social_content_plan")),
    )
    request_data = payload or GenerateSocialContentPlanRequest()
    output_language = infer_plan_language(suite, request_data.language)
    plan = await generate_social_content_work_plan(
        suite,
        output_language,
        monthly_posts=request_data.monthly_posts,
        plan_type=request_data.plan_type,
    )
    _save_social_content_plan(suite, plan)
    candidate_count = sum(
        len(group)
        for group in (plan.get("candidates") or {}).values()
        if isinstance(group, list)
    )
    warnings = plan.get("warnings") if isinstance(plan.get("warnings"), list) else []
    await record_provider_usage(
        db,
        provider="anthropic+openai",
        operation="marketing_social_content_plan.generate",
        model=f"{settings.anthropic_text_model}+{settings.openai_text_model}",
        status="partial" if warnings else "success",
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "monthly_posts": plan.get("monthly_posts"),
            "candidate_count": candidate_count,
            "selected_count": len(plan.get("selected_ids") or []),
            "language": output_language,
            "warnings": warnings,
            "cost_basis": "provider_usage_logged_without_actual_token_meter",
        },
    )
    await record_audit_log(
        db,
        action="marketing.social_content_plan.generate",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={
            "monthly_posts": plan.get("monthly_posts"),
            "candidate_count": candidate_count,
            "selected_count": len(plan.get("selected_ids") or []),
        },
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


@router.post("/suites/{suite_id}/marketing-plan/social-content-plan/selection")
async def update_marketing_social_content_plan_selection(
    suite_id: str,
    payload: SocialContentPlanSelectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    plan = _update_social_content_selection(suite, payload.selected_ids)
    await record_audit_log(
        db,
        action="marketing.social_content_plan.selection.update",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"selected_count": len(plan.get("selected_ids") or [])},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


async def _run_social_ideas_generation(suite_id: str, user_id: str, payload: "GenerateSocialIdeasRequest") -> None:
    """Server-side social-ideas run: keeps going even if the visitor navigates
    away or closes the app. Result (or a failed marker) lands on the suite; the
    client just polls the plan until status leaves "generating"."""
    from ..core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one_or_none()
        if suite is None:
            return
        try:
            plan = await generate_social_ideas(
                db,
                suite,
                period=payload.period,
                target_count=payload.target_count,
                requested_language=payload.language,
            )
        except Exception as e:
            log.exception("Background social-ideas generation failed for suite %s", suite_id)
            _save_social_ideas_plan(suite, {
                "status": "failed",
                "period": payload.period,
                "target_count": payload.target_count,
                "error": str(e)[:300],
            })
            await db.commit()
            return

        plan["status"] = "ready"
        _save_social_ideas_plan(suite, plan)
        warnings = plan.get("warnings") if isinstance(plan.get("warnings"), list) else []
        await record_provider_usage(
            db,
            provider=settings.ai_text_provider,
            operation="marketing_social_ideas.generate",
            model=settings.anthropic_text_model,
            status="partial" if warnings else "success",
            suite_id=suite.id,
            user_id=user_id,
            metadata={
                "period": payload.period,
                "target_count": plan.get("target_count"),
                "candidate_count": len(plan.get("candidates") or []),
                "occasion_count": len(plan.get("occasions") or []),
                "warnings": warnings,
            },
        )
        actor = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if actor is not None:
            await record_audit_log(
                db,
                action="marketing.social_ideas.generate",
                resource_type="marketing_action_plan",
                resource_id=suite.id,
                suite_id=suite.id,
                actor=actor,
                metadata={"period": payload.period, "candidate_count": len(plan.get("candidates") or [])},
            )
        await db.commit()


@router.post("/suites/{suite_id}/marketing-plan/social-ideas/generate")
async def generate_marketing_social_ideas(
    suite_id: str,
    payload: GenerateSocialIdeasRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)

    # A run is already in flight server-side — don't start a second one.
    existing = _social_ideas_plan(suite)
    if existing.get("status") == "generating":
        try:
            started = datetime.fromisoformat(str(existing.get("started_at")))
            still_fresh = (datetime.now(timezone.utc) - started).total_seconds() < 600
        except Exception:
            still_fresh = False
        if still_fresh:
            return _marketing_plan_response(suite, suite_id, None, "generating")

    _save_social_ideas_plan(suite, {
        "status": "generating",
        "period": payload.period,
        "target_count": payload.target_count,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.commit()
    await db.refresh(suite)
    asyncio.create_task(_run_social_ideas_generation(suite_id, current_user.id, payload))
    return _marketing_plan_response(suite, suite_id, None, "generating")


@router.post("/suites/{suite_id}/marketing-plan/social-ideas/selection")
async def update_marketing_social_ideas_selection(
    suite_id: str,
    payload: SocialIdeasSelectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    plan = _update_social_ideas_selection(suite, payload.selected_ids, payload.notes, payload.assets)
    await record_audit_log(
        db,
        action="marketing.social_ideas.selection.update",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"selected_count": len(plan.get("selected_ids") or [])},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


@router.patch("/suites/{suite_id}/marketing-plan/social-content-plan/items/{item_id}")
async def update_marketing_social_content_item(
    suite_id: str,
    item_id: str,
    payload: UpdateSocialContentItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    strategy, action_plan, plan = _social_plan_for_update(suite)
    item = _find_social_plan_item(plan, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    edits = {}
    for field in ("title", "idea", "script", "cta"):
        value = getattr(payload, field)
        if value is not None and value.strip():
            item[field] = value.strip()
            edits[field] = True
    if edits:
        item["edited_at"] = datetime.now(timezone.utc).isoformat()
        item["edited_by_user"] = True
    _store_social_plan(suite, strategy, action_plan, plan)
    await record_audit_log(
        db,
        action="marketing.social_content_plan.item.update",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"item_id": item_id, "fields": sorted(edits.keys())},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


async def _queue_social_item_generation(
    db: AsyncSession,
    suite: Suite,
    item: dict[str, Any],
    user: User,
    language: str,
) -> GenerationJob:
    content_type = _social_item_content_type(item)
    await enforce_generation_gate(
        suite.id,
        db,
        required_tokens=estimate_content_generation_tokens(1, content_type),
        requested_units=1,
        allow_free_trial=content_type != "video",
        event_type="social_plan_item_generation",
        metadata={
            "job_type": GenerationJobType.content_generation.value,
            "content_type": content_type,
            "plan_item_id": item.get("id"),
        },
    )
    job = await create_job(
        db,
        suite.id,
        GenerationJobType.content_generation,
        user.id,
        input_data={
            "mode": "quick",
            "content_type": content_type,
            "count": 1,
            "destination": "social",
            "use_brand": True,
            "language": language,
            "prompt": _social_item_generation_prompt(suite, item, language),
            "plan_item_id": item.get("id"),
            "plan_kind": "social_content_plan",
        },
    )
    item["generation"] = {
        "status": "queued",
        "job_id": job.id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    return job


@router.post("/suites/{suite_id}/marketing-plan/social-content-plan/items/{item_id}/generate", status_code=202)
async def generate_marketing_social_content_item(
    suite_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    strategy, action_plan, plan = _social_plan_for_update(suite)
    item = _find_social_plan_item(plan, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    if item.get("ai_capability") == "user_required":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "user_assets_required",
                "message": "هذه الفكرة بحاجة لتصوير/ملفات من عندك قبل التوليد.",
                "user_intervention": item.get("user_intervention"),
            },
        )
    generation = item.get("generation") if isinstance(item.get("generation"), dict) else {}
    if generation.get("job_id") and generation.get("status") in {"queued", "generating"}:
        result = await db.execute(select(GenerationJob).where(GenerationJob.id == generation["job_id"]))
        existing = result.scalar_one_or_none()
        if existing and existing.status in ACTIVE_STATUSES:
            return serialize_job(existing, suite_id=suite_id)
    language = infer_plan_language(suite, plan.get("language"))
    job = await _queue_social_item_generation(db, suite, item, current_user, language)
    _store_social_plan(suite, strategy, action_plan, plan)
    await record_audit_log(
        db,
        action="marketing.social_content_plan.item.generate",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"item_id": item_id, "job_id": job.id},
    )
    await db.commit()
    return serialize_job(job, suite_id=suite_id)


@router.post("/suites/{suite_id}/marketing-plan/social-content-plan/generate-items", status_code=202)
async def generate_marketing_social_content_items(
    suite_id: str,
    payload: GenerateSocialContentItemsRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    strategy, action_plan, plan = _social_plan_for_update(suite)
    request_data = payload or GenerateSocialContentItemsRequest()
    target_ids = request_data.item_ids or list(plan.get("selected_ids") or [])
    language = infer_plan_language(suite, plan.get("language"))
    queued: list[str] = []
    skipped: list[dict[str, str]] = []
    blocked_reason: str | None = None
    for item_id in target_ids:
        item = _find_social_plan_item(plan, str(item_id))
        if not item:
            skipped.append({"item_id": str(item_id), "reason": "not_found"})
            continue
        if item.get("ai_capability") == "user_required":
            skipped.append({"item_id": str(item_id), "reason": "user_assets_required"})
            continue
        generation = item.get("generation") if isinstance(item.get("generation"), dict) else {}
        if generation.get("status") in {"queued", "generating", "ready"}:
            skipped.append({"item_id": str(item_id), "reason": generation.get("status") or "active"})
            continue
        try:
            job = await _queue_social_item_generation(db, suite, item, current_user, language)
        except HTTPException as exc:
            if exc.status_code == 402:
                blocked_reason = "generation_tokens_exhausted"
                skipped.append({"item_id": str(item_id), "reason": "payment_required"})
                break
            raise
        queued.append(job.id)
    _store_social_plan(suite, strategy, action_plan, plan)
    await record_audit_log(
        db,
        action="marketing.social_content_plan.generate_items",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"queued": len(queued), "skipped": len(skipped)},
    )
    await db.commit()
    return {
        "queued_job_ids": queued,
        "skipped": skipped,
        "payment_required": blocked_reason is not None,
        **_marketing_plan_response(suite, suite_id, None, "action_plan_ready"),
    }


@router.post("/suites/{suite_id}/marketing-plan/social-plan/generate")
async def generate_marketing_social_plan(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _generate_marketing_plan_section(suite_id, "social", payload, current_user, db)


@router.post("/suites/{suite_id}/marketing-plan/paid-content-plan/generate")
async def generate_marketing_paid_content_plan(
    suite_id: str,
    payload: GeneratePaidContentPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    block_funnel_regeneration(
        current_user,
        already_generated=bool((_action_plan(suite) or {}).get("paid_content_plan")),
    )
    request_data = payload or GeneratePaidContentPlanRequest()
    output_language = infer_plan_language(suite, request_data.language)
    plan = await generate_paid_content_work_plan(suite, output_language)
    _save_paid_content_plan(suite, plan)
    candidate_count = sum(
        len(group)
        for group in (plan.get("candidates") or {}).values()
        if isinstance(group, list)
    )
    warnings = plan.get("warnings") if isinstance(plan.get("warnings"), list) else []
    await record_provider_usage(
        db,
        provider="anthropic+openai",
        operation="marketing_paid_content_plan.generate",
        model=f"{settings.anthropic_text_model}+{settings.openai_text_model}",
        status="partial" if warnings else "success",
        suite_id=suite.id,
        user_id=current_user.id,
        metadata={
            "candidate_count": candidate_count,
            "selected_count": len(plan.get("selected_ids") or []),
            "language": output_language,
            "warnings": warnings,
            "cost_basis": "provider_usage_logged_without_actual_token_meter",
        },
    )
    await record_audit_log(
        db,
        action="marketing.paid_content_plan.generate",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={
            "candidate_count": candidate_count,
            "selected_count": len(plan.get("selected_ids") or []),
        },
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


@router.post("/suites/{suite_id}/marketing-plan/paid-content-plan/selection")
async def update_marketing_paid_content_plan_selection(
    suite_id: str,
    payload: PaidContentPlanSelectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    plan = _update_paid_content_selection(suite, payload.selected_ids)
    await record_audit_log(
        db,
        action="marketing.paid_content_plan.selection.update",
        resource_type="marketing_action_plan",
        resource_id=suite.id,
        suite_id=suite.id,
        actor=current_user,
        metadata={"selected_count": len(plan.get("selected_ids") or [])},
    )
    await db.commit()
    return _marketing_plan_response(suite, suite_id, None, "action_plan_ready")


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
