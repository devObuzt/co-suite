import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Boolean, JSON, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from ..core.database import Base


class SuiteStatus(str, enum.Enum):
    onboarding = "onboarding"
    active = "active"
    suspended = "suspended"


class MemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class Suite(Base):
    __tablename__ = "suites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    status: Mapped[SuiteStatus] = mapped_column(Enum(SuiteStatus), default=SuiteStatus.onboarding)

    # Brand profile (JSON — populated during onboarding)
    brand: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # e.g. {"logo_url": "...", "colors": {"primary": "#..."}, "description": "...", "services": [...], "tagline": "..."}

    # Marketing strategy (JSON — populated after onboarding completes)
    strategy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Settings
    ai_generation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_publish_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    generation_frequency: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "daily", "3x_week", etc.

    # Platform connections (JSON)
    connections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # e.g. {"instagram": {"page_id": "...", "token": "..."}, "facebook": {...}}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship("User", back_populates="owned_suites")
    members: Mapped[list["SuiteMember"]] = relationship("SuiteMember", back_populates="suite")
    content_posts: Mapped[list["ContentPost"]] = relationship("ContentPost", back_populates="suite")


class SuiteMember(Base):
    __tablename__ = "suite_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole), default=MemberRole.member)
    can_chat_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suite: Mapped["Suite"] = relationship("Suite", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="suites")
