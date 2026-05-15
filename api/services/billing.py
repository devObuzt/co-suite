"""Billing service — subscriptions, credit tracking, freeze logic."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.billing import Subscription, UsageEvent, PlanTier, BillingStatus
from ..models.suite import Suite

# ── Pricing ───────────────────────────────────────────────────────────────────

PRICING: dict[PlanTier, float] = {
    PlanTier.solo: 14.99,        # per seat/month
    PlanTier.team: 11.99,        # per seat/month, 2-24 seats
    PlanTier.enterprise: 7.99,   # per seat/month, 25+ seats
}

CREDIT_MULTIPLIER = 3.0   # actual API cost × 3 = billed amount
FREEZE_THRESHOLD = -10.0  # freeze when balance reaches this


def get_tier(seat_count: int) -> PlanTier:
    if seat_count >= 25:
        return PlanTier.enterprise
    if seat_count >= 2:
        return PlanTier.team
    return PlanTier.solo


def monthly_total(seat_count: int) -> float:
    tier = get_tier(seat_count)
    return round(PRICING[tier] * seat_count, 2)


# ── Subscription CRUD ─────────────────────────────────────────────────────────

async def get_or_create_subscription(suite_id: str, db: AsyncSession) -> Subscription:
    result = await db.execute(select(Subscription).where(Subscription.suite_id == suite_id))
    sub = result.scalar_one_or_none()
    if not sub:
        sub = Subscription(
            id=str(uuid.uuid4()),
            suite_id=suite_id,
            tier=PlanTier.solo,
            status=BillingStatus.active,
            seat_count=1,
            credit_balance=0.0,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
    return sub


async def update_seats(suite_id: str, seat_count: int, db: AsyncSession) -> Subscription:
    sub = await get_or_create_subscription(suite_id, db)
    sub.seat_count = max(1, seat_count)
    sub.tier = get_tier(sub.seat_count)
    await db.commit()
    await db.refresh(sub)
    return sub


# ── Credit / Usage ────────────────────────────────────────────────────────────

async def record_usage(
    suite_id: str,
    event_type: str,
    actual_cost_usd: float,
    db: AsyncSession,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    """Record an AI usage event and deduct 3× cost from the suite's credit balance."""
    sub = await get_or_create_subscription(suite_id, db)

    billed = round(actual_cost_usd * CREDIT_MULTIPLIER, 4)
    event = UsageEvent(
        id=str(uuid.uuid4()),
        subscription_id=sub.id,
        suite_id=suite_id,
        event_type=event_type,
        actual_cost_usd=actual_cost_usd,
        billed_amount=billed,
        event_data=metadata,
    )
    db.add(event)

    sub.credit_balance = round(sub.credit_balance - billed, 4)

    # Auto-freeze if threshold crossed
    if sub.credit_balance <= FREEZE_THRESHOLD and sub.status == BillingStatus.active:
        sub.status = BillingStatus.frozen

    await db.commit()
    await db.refresh(sub)
    return event


async def apply_payment(suite_id: str, amount_usd: float, db: AsyncSession) -> Subscription:
    """Credit the suite's balance after a payment is confirmed."""
    sub = await get_or_create_subscription(suite_id, db)
    sub.credit_balance = round(sub.credit_balance + amount_usd, 4)
    if sub.credit_balance > FREEZE_THRESHOLD and sub.status == BillingStatus.frozen:
        sub.status = BillingStatus.active
    await db.commit()
    await db.refresh(sub)
    return sub


async def is_frozen(suite_id: str, db: AsyncSession) -> bool:
    result = await db.execute(select(Subscription).where(Subscription.suite_id == suite_id))
    sub = result.scalar_one_or_none()
    return sub is not None and sub.status == BillingStatus.frozen


# ── AI cost constants (approximate) ──────────────────────────────────────────
# Use these when recording usage events from content generation / publishing.

COSTS = {
    "llm_idea_gen": 0.012,      # Claude Sonnet — ~1k prompt + 4k output
    "image_gen": 0.039,         # Imagen 4 Fast per image
    "video_gen_fast": 0.40,     # Veo 3 Fast per 8s clip (estimated)
    "video_gen_hq": 0.80,       # Veo 3 HD per 8s clip (estimated)
    "brand_extract": 0.005,     # Claude — onboarding scrape
}
