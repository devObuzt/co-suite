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
from ..models.suite import Suite
from ..models.user import User
from ..services.marketing_plan_generator import generate_marketing_plan_deck, infer_plan_language

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


def _save_deck(suite: Suite, deck: dict[str, Any]) -> None:
    strategy = dict(_strategy(suite))
    strategy["marketing_plan_deck"] = deck
    suite.strategy = strategy


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
    if not deck:
        return {
            "status": "missing",
            "suite_id": suite_id,
            "language": infer_plan_language(suite),
            "deck": None,
        }
    return {"status": "ready", "suite_id": suite_id, "deck": _public_deck(deck)}


@router.post("/suites/{suite_id}/marketing-plan/generate")
async def generate_marketing_plan(
    suite_id: str,
    payload: GenerateMarketingPlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    request_data = payload or GenerateMarketingPlanRequest()
    planning_inputs = {
        "near_term_focus": request_data.near_term_focus,
        "upcoming_campaigns": [item for item in request_data.upcoming_campaigns if item.strip()][:12],
        "planning_notes": request_data.planning_notes,
    }
    deck = await generate_marketing_plan_deck(suite, request_data.language, planning_inputs=planning_inputs)
    existing = _deck(suite)
    if existing and isinstance(existing.get("share"), dict):
        deck["share"] = existing["share"]
    _save_deck(suite, deck)
    await db.commit()
    await db.refresh(suite)
    return {"status": "ready", "suite_id": suite_id, "deck": _public_deck(deck)}


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
