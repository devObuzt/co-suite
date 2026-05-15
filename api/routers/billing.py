from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..core.database import get_db
from ..core.config import settings
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite
from ..models.billing import Subscription, UsageEvent, BillingStatus
from ..services.billing import (
    get_or_create_subscription, update_seats, apply_payment,
    get_tier, monthly_total, PRICING, FREEZE_THRESHOLD,
)

router = APIRouter(prefix="/billing", tags=["billing"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SubscriptionOut(BaseModel):
    suite_id: str
    tier: str
    status: str
    seat_count: int
    credit_balance: float
    auto_pay_enabled: bool
    monthly_total: float
    price_per_seat: float
    freeze_threshold: float

    class Config:
        from_attributes = True


class UsageEventOut(BaseModel):
    id: str
    event_type: str
    actual_cost_usd: float
    billed_amount: float
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateSeatsRequest(BaseModel):
    seat_count: int


class AutoPayRequest(BaseModel):
    enabled: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{suite_id}", response_model=SubscriptionOut)
async def get_subscription(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_owner(suite_id, current_user, db)
    sub = await get_or_create_subscription(suite_id, db)
    tier = get_tier(sub.seat_count)
    return SubscriptionOut(
        suite_id=suite_id,
        tier=sub.tier.value,
        status=sub.status.value,
        seat_count=sub.seat_count,
        credit_balance=sub.credit_balance,
        auto_pay_enabled=sub.auto_pay_enabled,
        monthly_total=monthly_total(sub.seat_count),
        price_per_seat=PRICING[tier],
        freeze_threshold=FREEZE_THRESHOLD,
    )


@router.get("/{suite_id}/usage", response_model=list[UsageEventOut])
async def get_usage(
    suite_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_owner(suite_id, current_user, db)
    result = await db.execute(
        select(UsageEvent)
        .where(UsageEvent.suite_id == suite_id)
        .order_by(UsageEvent.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.patch("/{suite_id}/seats", response_model=SubscriptionOut)
async def change_seats(
    suite_id: str,
    data: UpdateSeatsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_owner(suite_id, current_user, db)
    sub = await update_seats(suite_id, data.seat_count, db)
    tier = get_tier(sub.seat_count)
    return SubscriptionOut(
        suite_id=suite_id,
        tier=sub.tier.value,
        status=sub.status.value,
        seat_count=sub.seat_count,
        credit_balance=sub.credit_balance,
        auto_pay_enabled=sub.auto_pay_enabled,
        monthly_total=monthly_total(sub.seat_count),
        price_per_seat=PRICING[tier],
        freeze_threshold=FREEZE_THRESHOLD,
    )


@router.patch("/{suite_id}/auto-pay")
async def toggle_auto_pay(
    suite_id: str,
    data: AutoPayRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_owner(suite_id, current_user, db)
    sub = await get_or_create_subscription(suite_id, db)
    sub.auto_pay_enabled = data.enabled
    await db.commit()
    return {"ok": True, "auto_pay_enabled": data.enabled}


@router.get("/{suite_id}/subscribe-url")
async def get_subscribe_url(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the Morning payment URL for subscribing / upgrading."""
    await _assert_owner(suite_id, current_user, db)
    sub = await get_or_create_subscription(suite_id, db)
    morning_url = settings.morning_subscribe_url or "https://morning.co.il"
    url = (
        f"{morning_url}"
        f"?suite_id={suite_id}"
        f"&plan={sub.tier.value}"
        f"&seats={sub.seat_count}"
        f"&amount={monthly_total(sub.seat_count)}"
        f"&return_url={settings.frontend_url}/suite/{suite_id}/billing"
    )
    return {"url": url}


@router.get("/{suite_id}/pay-url")
async def get_pay_balance_url(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the Morning payment URL for paying off a negative balance."""
    await _assert_owner(suite_id, current_user, db)
    sub = await get_or_create_subscription(suite_id, db)
    if sub.credit_balance >= 0:
        raise HTTPException(status_code=400, detail="No balance to pay")
    amount = abs(sub.credit_balance)
    morning_url = settings.morning_pay_url or "https://morning.co.il"
    url = (
        f"{morning_url}"
        f"?suite_id={suite_id}"
        f"&type=balance"
        f"&amount={amount:.2f}"
        f"&return_url={settings.frontend_url}/suite/{suite_id}/billing"
    )
    return {"url": url, "amount": amount}


@router.post("/webhook/morning")
async def morning_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Morning calls this after a successful payment."""
    payload = await request.json()
    suite_id = payload.get("suite_id")
    amount = float(payload.get("amount", 0))
    payment_type = payload.get("type", "subscription")

    if not suite_id or amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payload")

    if payment_type == "balance":
        await apply_payment(suite_id, amount, db)

    return {"ok": True}


# ── Helper ────────────────────────────────────────────────────────────────────

async def _assert_owner(suite_id: str, user: User, db: AsyncSession):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
