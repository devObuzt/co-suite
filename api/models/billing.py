import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Float, JSON, ForeignKey, Enum, func, Boolean
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


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, unique=True)
    tier: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.solo)
    status: Mapped[BillingStatus] = mapped_column(Enum(BillingStatus), default=BillingStatus.active)
    seat_count: Mapped[int] = mapped_column(default=1)

    # Credit system
    credit_balance: Mapped[float] = mapped_column(Float, default=0.0)  # negative = owes money
    auto_pay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_pay_threshold: Mapped[float] = mapped_column(Float, default=-10.0)  # freeze trigger

    # Payment provider
    morning_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    morning_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usage_events: Mapped[list["UsageEvent"]] = relationship("UsageEvent", back_populates="subscription")


class UsageEvent(Base):
    """Records every AI cost event. Actual cost × 3 = negative credit added."""
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("subscriptions.id"), nullable=False)
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False)

    event_type: Mapped[str] = mapped_column(String, nullable=False)  # "image_gen", "video_gen", "llm_call"
    actual_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    billed_amount: Mapped[float] = mapped_column(Float, nullable=False)  # actual_cost × 3
    event_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="usage_events")
