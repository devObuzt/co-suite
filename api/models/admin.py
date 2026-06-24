import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    actor_email: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    suite_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("suites.id"), nullable=True, index=True)
    target_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ProviderUsageEvent(Base):
    __tablename__ = "provider_usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    operation: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="success", index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    suite_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("suites.id"), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    generation_job_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("generation_jobs.id"), nullable=True, index=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
