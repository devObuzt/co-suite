import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Float, Integer, JSON, ForeignKey, Enum, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from ..core.database import Base


class PlanTier(str, enum.Enum):
    solo = "solo"          # $14.99/user
    team = "team"          # $11.99/user (2-24 users)
    enterprise = "enterprise"  # $7.99/user (25+ users)


class BillingStatus(str, enum.Enum):
    active = "active"
    frozen = "frozen"      # negative credits >= $10
    cancelled = "cancelled"


class LedgerAccountType(str, enum.Enum):
    subscription = "subscription"
    generation_tokens = "generation_tokens"
    marketing_budget = "marketing_budget"


class BillingEventType(str, enum.Enum):
    subscription_plan_set = "subscription_plan_set"
    subscription_token_grant = "subscription_token_grant"
    token_purchase = "token_purchase"
    generation_usage = "generation_usage"
    marketing_budget_top_up = "marketing_budget_top_up"
    marketing_budget_spend = "marketing_budget_spend"
    legacy_usage_charge = "legacy_usage_charge"
    legacy_balance_payment = "legacy_balance_payment"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, unique=True)
    tier: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.solo)
    status: Mapped[BillingStatus] = mapped_column(Enum(BillingStatus), default=BillingStatus.active)
    seat_count: Mapped[int] = mapped_column(default=1)

    # Credit system
    credit_balance: Mapped[float] = mapped_column(Float, default=0.0)  # negative = owes money
    generation_token_balance: Mapped[int] = mapped_column(Integer, default=0)
    marketing_budget_balance_usd: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_generation_token_grant: Mapped[int] = mapped_column(Integer, default=0)
    auto_pay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_pay_threshold: Mapped[float] = mapped_column(Float, default=-10.0)  # freeze trigger

    # Payment provider
    morning_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    morning_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usage_events: Mapped[list["UsageEvent"]] = relationship("UsageEvent", back_populates="subscription")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.credit_balance is None:
            self.credit_balance = 0.0
        if self.generation_token_balance is None:
            self.generation_token_balance = 0
        if self.marketing_budget_balance_usd is None:
            self.marketing_budget_balance_usd = 0.0
        if self.monthly_generation_token_grant is None:
            self.monthly_generation_token_grant = 0


class UsageEvent(Base):
    """Auditable billing ledger event for subscription, token, and ad-budget activity."""
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("subscriptions.id"), nullable=False)
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False)

    event_type: Mapped[str] = mapped_column(String, nullable=False)  # "image_gen", "video_gen", "llm_call"
    ledger_account: Mapped[LedgerAccountType] = mapped_column(
        Enum(LedgerAccountType),
        default=LedgerAccountType.generation_tokens,
        nullable=False,
    )
    billing_event_type: Mapped[BillingEventType] = mapped_column(
        Enum(BillingEventType),
        default=BillingEventType.legacy_usage_charge,
        nullable=False,
    )
    amount_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    balance_after_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    balance_after_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    billed_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # actual_cost × 3
    external_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="usage_events")
