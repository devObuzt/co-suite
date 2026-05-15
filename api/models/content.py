import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, JSON, ForeignKey, Enum, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from ..core.database import Base


class PostStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"


class PostFormat(str, enum.Enum):
    image = "image"
    carousel = "carousel"
    video = "video"


class ContentPost(Base):
    __tablename__ = "content_posts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    format: Mapped[PostFormat] = mapped_column(Enum(PostFormat), nullable=False)
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus), default=PostStatus.pending)

    # AI-generated content
    topic: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hashtags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Media
    media_urls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # list of URLs

    # Metadata from AI generation
    ai_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Publishing
    publish_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    platform_post_ids: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"instagram": "...", ...}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    suite: Mapped["Suite"] = relationship("Suite", back_populates="content_posts")
