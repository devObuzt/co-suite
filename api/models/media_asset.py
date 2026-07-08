import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class MediaAsset(Base):
    """A finished media file filed into a suite's media library.

    The hierarchy shown in the UI (library -> year -> month) is derived from
    ``library`` and ``created_at`` — there is no manual folder management yet.
    """

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, index=True)
    library: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="video/mp4")
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
