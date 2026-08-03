import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ServiceItem(Base):
    """One sellable service in the public startbyconnec catalog (admin-editable)."""

    __tablename__ = "service_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[dict] = mapped_column(JSON, nullable=False)          # {"ar": ..., "he": ...}
    description: Mapped[dict] = mapped_column(JSON, nullable=False)   # {"ar": ..., "he": ...}
    category: Mapped[dict] = mapped_column(JSON, nullable=False)      # {"ar": ..., "he": ...}
    billing_cycle: Mapped[str] = mapped_column(String, nullable=False, default="one_time")
    price_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # NULL → fixed price
    unit: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # qty stepper shown when set
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Package(Base):
    """A curated offering shown on the startbyconnec pricing proposal.

    Standalone (not a bundle of specific service_ids): a bilingual name +
    description, a price band, and a cover image the admin either uploads or
    generates from the package's own content. Shown to a lead with its cover.
    """

    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[dict] = mapped_column(JSON, nullable=False)          # {"ar": ..., "he": ...}
    description: Mapped[dict] = mapped_column(JSON, nullable=False)   # {"ar": ..., "he": ...}
    billing_cycle: Mapped[str] = mapped_column(String, nullable=False, default="one_time")
    price_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # NULL → fixed price
    cover_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Lead(Base):
    """A startbyconnec visitor: created at funnel registration, enriched later."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nullable: a lead is captured the moment a phone number is submitted,
    # before any user exists or a name/email is known.
    user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    suite_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("suites.id", ondelete="SET NULL"), nullable=True
    )
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    source: Mapped[str] = mapped_column(String, nullable=False, default="startbyconnec")
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendations: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    progress: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ServiceRequest(Base):
    """Submitted service selection: immutable snapshot of items + totals."""

    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"), nullable=False, index=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PhoneOtp(Base):
    """One-time code for phone-only funnel auth. Code is static until the
    WhatsApp/SMS sender is wired in."""

    __tablename__ = "phone_otps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    phone: Mapped[str] = mapped_column(String, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def serialize_service_item(item: ServiceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name or {},
        "description": item.description or {},
        "category": item.category or {},
        "billing_cycle": item.billing_cycle,
        "price_min": item.price_min,
        "price_max": item.price_max,
        "unit": item.unit,
        "is_active": bool(item.is_active if item.is_active is not None else True),
        "sort_order": int(item.sort_order or 0),
    }


def serialize_package(pkg: Package) -> dict[str, Any]:
    return {
        "id": pkg.id,
        "name": pkg.name or {},
        "description": pkg.description or {},
        "billing_cycle": pkg.billing_cycle,
        "price_min": pkg.price_min,
        "price_max": pkg.price_max,
        "cover_image_url": pkg.cover_image_url,
        "is_active": bool(pkg.is_active if pkg.is_active is not None else True),
        "sort_order": int(pkg.sort_order or 0),
    }


def serialize_lead(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "user_id": lead.user_id,
        "suite_id": lead.suite_id,
        "full_name": lead.full_name,
        "email": lead.email,
        "phone": lead.phone,
        "status": lead.status or "new",
        "source": lead.source or "startbyconnec",
        "admin_notes": lead.admin_notes,
        "recommendations": lead.recommendations,
        "progress": lead.progress or {},
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
    }


def serialize_service_request(req: ServiceRequest) -> dict[str, Any]:
    return {
        "id": req.id,
        "lead_id": req.lead_id,
        "items": req.items or [],
        "totals": req.totals or {},
        "customer_notes": req.customer_notes,
        "status": req.status or "new",
        "created_at": req.created_at,
    }
