import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ResearchCache(Base):
    """Reusable research shared across suites, keyed by (kind, country, language, period).

    ``kind`` discriminates the payload: "occasions" (holidays/events for a
    month) or "market" (audience/competitor snapshot). Reserved for "trends"
    later — same table, no schema change.
    """

    __tablename__ = "research_cache"
    __table_args__ = (
        UniqueConstraint(
            "kind", "country", "language", "period",
            name="uq_research_cache_kind_country_language_period",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    period: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="hybrid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
