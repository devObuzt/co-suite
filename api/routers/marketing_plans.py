"""Marketing plan deck API."""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
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


class GenerateMarketingPlanRequest(BaseModel):
    language: str | None = None
    near_term_focus: str | None = Field(default=None, max_length=2000)
    upcoming_campaigns: list[str] = Field(default_factory=list, max_length=12)
    planning_notes: str | None = Field(default=None, max_length=2000)


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
    return await _generate_marketing_research_section(suite_id, "competitors", payload, current_user, db)


@router.post("/suites/{suite_id}/marketing-plan/demand-supply/generate")
async def generate_marketing_demand_supply(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _generate_marketing_research_section(suite_id, "demand_supply", payload, current_user, db)


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
