"""Billing service — subscriptions, credit tracking, freeze logic."""
import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from ..models.billing import (
    BillingEventType,
    BillingStatus,
    LedgerAccountType,
    PlanTier,
    Subscription,
    UsageEvent,
)
from ..models.suite import Suite

# ── Pricing ───────────────────────────────────────────────────────────────────

PRICING: dict[PlanTier, float] = {
    PlanTier.solo: 14.99,        # per seat/month
    PlanTier.team: 11.99,        # per seat/month, 2-24 seats
    PlanTier.enterprise: 7.99,   # per seat/month, 25+ seats
}

MONTHLY_TOKEN_GRANTS: dict[PlanTier, int] = {
    PlanTier.solo: 1000,
    PlanTier.team: 1500,
    PlanTier.enterprise: 2500,
}

CREDIT_MULTIPLIER = 3.0   # actual API cost × 3 = billed amount
FREEZE_THRESHOLD = -10.0  # freeze when balance reaches this
FREE_TRIAL_GENERATION_UNITS = 3


class GenerationGateStatus(str, enum.Enum):
    paid = "paid"
    free_trial = "free_trial"
    blocked = "blocked"


@dataclass(frozen=True)
class GenerationGateDecision:
    status: GenerationGateStatus
    required_tokens: int
    token_balance: int
    free_trial_remaining: int
    payment_required: bool
    detail: dict

    @property
    def allowed(self) -> bool:
        return self.status in {GenerationGateStatus.paid, GenerationGateStatus.free_trial}


def get_tier(seat_count: int) -> PlanTier:
    if seat_count >= 25:
        return PlanTier.enterprise
    if seat_count >= 2:
        return PlanTier.team
    return PlanTier.solo


def monthly_total(seat_count: int) -> float:
    tier = get_tier(seat_count)
    return round(PRICING[tier] * seat_count, 2)


def monthly_token_grant(seat_count: int) -> int:
    tier = get_tier(seat_count)
    return MONTHLY_TOKEN_GRANTS[tier] * max(1, seat_count)


def generation_gate_decision(
    sub: Subscription,
    *,
    required_tokens: int,
    free_trial_units_used: int,
    requested_units: int,
    allow_free_trial: bool,
) -> GenerationGateDecision:
    required = max(1, int(required_tokens))
    requested = max(1, int(requested_units))
    balance = max(0, int(sub.generation_token_balance or 0))
    remaining = max(0, FREE_TRIAL_GENERATION_UNITS - max(0, int(free_trial_units_used)))

    if balance >= required:
        return GenerationGateDecision(
            status=GenerationGateStatus.paid,
            required_tokens=required,
            token_balance=balance,
            free_trial_remaining=remaining,
            payment_required=False,
            detail={
                "code": "generation_allowed",
                "required_tokens": required,
                "token_balance": balance,
                "free_trial_remaining": remaining,
            },
        )

    if allow_free_trial and requested <= remaining:
        return GenerationGateDecision(
            status=GenerationGateStatus.free_trial,
            required_tokens=required,
            token_balance=balance,
            free_trial_remaining=remaining - requested,
            payment_required=False,
            detail={
                "code": "free_trial_generation",
                "required_tokens": required,
                "token_balance": balance,
                "free_trial_remaining": remaining - requested,
            },
        )

    return GenerationGateDecision(
        status=GenerationGateStatus.blocked,
        required_tokens=required,
        token_balance=balance,
        free_trial_remaining=remaining,
        payment_required=True,
        detail={
            "code": "generation_tokens_exhausted",
            "message": "Generation tokens are exhausted. Upgrade your plan or buy generation tokens to continue.",
            "required_tokens": required,
            "token_balance": balance,
            "free_trial_remaining": remaining,
            "allowed_actions": ["upgrade_plan", "buy_generation_tokens"],
        },
    )


def estimate_content_generation_tokens(count: int, content_type: Optional[str] = None) -> int:
    unit_costs = {
        "text": 75,
        "image": 150,
        "carousel": 250,
        "video": 800,
        "mixed": 200,
    }
    normalized = (content_type or "mixed").strip().lower()
    return max(1, int(count or 1)) * unit_costs.get(normalized, unit_costs["mixed"])


async def count_free_trial_generation_units(suite_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(func.abs(UsageEvent.amount_tokens)), 0)).where(
            UsageEvent.suite_id == suite_id,
            UsageEvent.event_type == "free_trial_generation",
        )
    )
    return int(result.scalar_one() or 0)


async def enforce_generation_gate(
    suite_id: str,
    db: AsyncSession,
    *,
    required_tokens: int,
    requested_units: int = 1,
    allow_free_trial: bool = False,
    event_type: str = "generation_request",
    metadata: Optional[dict] = None,
) -> GenerationGateDecision:
    sub = await get_or_create_subscription(suite_id, db)
    free_trial_units_used = await count_free_trial_generation_units(suite_id, db)
    decision = generation_gate_decision(
        sub,
        required_tokens=required_tokens,
        free_trial_units_used=free_trial_units_used,
        requested_units=requested_units,
        allow_free_trial=allow_free_trial,
    )
    if decision.status == GenerationGateStatus.blocked:
        raise HTTPException(status_code=402, detail=decision.detail)

    payload = {
        "gate_status": decision.status.value,
        "event_type": event_type,
        **(metadata or {}),
    }
    if decision.status == GenerationGateStatus.paid:
        event = record_generation_token_usage(sub, tokens=decision.required_tokens, event_type=event_type, metadata=payload)
    else:
        event = _ledger_event(
            sub,
            ledger_account=LedgerAccountType.generation_tokens,
            billing_event_type=BillingEventType.generation_usage,
            event_type="free_trial_generation",
            amount_tokens=-max(1, requested_units),
            balance_after_tokens=sub.generation_token_balance or 0,
            metadata=payload,
        )
    db.add(event)
    await db.commit()
    await db.refresh(sub)
    return decision


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
            generation_token_balance=0,
            marketing_budget_balance_usd=0.0,
            monthly_generation_token_grant=monthly_token_grant(1),
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
    return sub


async def update_seats(suite_id: str, seat_count: int, db: AsyncSession) -> Subscription:
    sub = await get_or_create_subscription(suite_id, db)
    normalized_seat_count = max(1, seat_count)
    event = record_subscription_plan_set(
        sub,
        tier=get_tier(normalized_seat_count),
        seat_count=normalized_seat_count,
        monthly_tokens=monthly_token_grant(normalized_seat_count),
    )
    db.add(event)
    await db.commit()
    await db.refresh(sub)
    return sub


# ── Credit / Usage ────────────────────────────────────────────────────────────

def _ledger_event(
    sub: Subscription,
    *,
    ledger_account: LedgerAccountType,
    billing_event_type: BillingEventType,
    event_type: str,
    amount_tokens: int = 0,
    balance_after_tokens: Optional[int] = None,
    amount_usd: float = 0.0,
    balance_after_usd: Optional[float] = None,
    actual_cost_usd: float = 0.0,
    billed_amount: float = 0.0,
    external_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    return UsageEvent(
        id=str(uuid.uuid4()),
        subscription_id=sub.id,
        suite_id=sub.suite_id,
        event_type=event_type,
        ledger_account=ledger_account,
        billing_event_type=billing_event_type,
        amount_tokens=amount_tokens,
        balance_after_tokens=balance_after_tokens,
        amount_usd=amount_usd,
        balance_after_usd=balance_after_usd,
        actual_cost_usd=actual_cost_usd,
        billed_amount=billed_amount,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        event_data=metadata,
    )


def record_subscription_plan_set(
    sub: Subscription,
    *,
    tier: PlanTier,
    seat_count: int,
    monthly_tokens: int,
    external_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> UsageEvent:
    sub.tier = tier
    sub.seat_count = max(1, seat_count)
    sub.monthly_generation_token_grant = max(0, monthly_tokens)
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.subscription,
        billing_event_type=BillingEventType.subscription_plan_set,
        event_type=BillingEventType.subscription_plan_set.value,
        amount_tokens=0,
        balance_after_tokens=sub.generation_token_balance or 0,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        metadata={
            "tier": sub.tier.value,
            "seat_count": sub.seat_count,
            "monthly_generation_token_grant": sub.monthly_generation_token_grant,
        },
    )


def apply_monthly_plan_token_grant(
    sub: Subscription,
    *,
    tokens: int,
    reason: str,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    if tokens <= 0:
        raise ValueError("Token grant must be positive")
    sub.generation_token_balance = (sub.generation_token_balance or 0) + tokens
    payload = {"reason": reason, **(metadata or {})}
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.generation_tokens,
        billing_event_type=BillingEventType.subscription_token_grant,
        event_type=BillingEventType.subscription_token_grant.value,
        amount_tokens=tokens,
        balance_after_tokens=sub.generation_token_balance,
        idempotency_key=idempotency_key,
        metadata=payload,
    )


def apply_token_purchase(
    sub: Subscription,
    *,
    tokens: int,
    amount_usd: float,
    external_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    if tokens <= 0:
        raise ValueError("Token purchase must add positive tokens")
    if amount_usd <= 0:
        raise ValueError("Token purchase amount must be positive")
    sub.generation_token_balance = (sub.generation_token_balance or 0) + tokens
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.generation_tokens,
        billing_event_type=BillingEventType.token_purchase,
        event_type=BillingEventType.token_purchase.value,
        amount_tokens=tokens,
        balance_after_tokens=sub.generation_token_balance,
        amount_usd=round(amount_usd, 2),
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def record_generation_token_usage(
    sub: Subscription,
    *,
    tokens: int,
    event_type: str,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    if tokens <= 0:
        raise ValueError("Generation token usage must be positive")
    if (sub.generation_token_balance or 0) < tokens:
        raise ValueError("Insufficient generation tokens")
    sub.generation_token_balance -= tokens
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.generation_tokens,
        billing_event_type=BillingEventType.generation_usage,
        event_type=event_type,
        amount_tokens=-tokens,
        balance_after_tokens=sub.generation_token_balance,
        metadata=metadata,
    )


def apply_marketing_budget_top_up(
    sub: Subscription,
    *,
    amount_usd: float,
    external_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    if amount_usd <= 0:
        raise ValueError("Marketing budget top-up must be positive")
    amount = round(amount_usd, 2)
    sub.marketing_budget_balance_usd = round((sub.marketing_budget_balance_usd or 0.0) + amount, 2)
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.marketing_budget,
        billing_event_type=BillingEventType.marketing_budget_top_up,
        event_type=BillingEventType.marketing_budget_top_up.value,
        amount_usd=amount,
        balance_after_usd=sub.marketing_budget_balance_usd,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def record_marketing_budget_spend(
    sub: Subscription,
    *,
    amount_usd: float,
    event_type: str,
    metadata: Optional[dict] = None,
) -> UsageEvent:
    if amount_usd <= 0:
        raise ValueError("Marketing budget spend must be positive")
    amount = round(amount_usd, 2)
    if (sub.marketing_budget_balance_usd or 0.0) < amount:
        raise ValueError("Insufficient marketing budget")
    sub.marketing_budget_balance_usd = round(sub.marketing_budget_balance_usd - amount, 2)
    return _ledger_event(
        sub,
        ledger_account=LedgerAccountType.marketing_budget,
        billing_event_type=BillingEventType.marketing_budget_spend,
        event_type=event_type,
        amount_usd=-amount,
        balance_after_usd=sub.marketing_budget_balance_usd,
        metadata=metadata,
    )

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
        ledger_account=LedgerAccountType.generation_tokens,
        billing_event_type=BillingEventType.legacy_usage_charge,
        amount_tokens=0,
        actual_cost_usd=actual_cost_usd,
        billed_amount=billed,
        amount_usd=-billed,
        balance_after_usd=round(sub.credit_balance - billed, 4),
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
