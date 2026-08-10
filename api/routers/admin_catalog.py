"""Admin CRUD for the startbyconnec service catalog + packages + leads inbox."""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.services_catalog import (
    Lead,
    Package,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_package,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.admin_audit import record_audit_log, require_super_admin, serialize_user_public
from ..services.content_generator import _generate_image
from ..services.creative_assets import PACKAGE_COVER_KIND, create_asset_from_bytes

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


async def _admin_user(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    return await require_super_admin(current_user, db)


def _bilingual(value: dict) -> dict:
    if not isinstance(value, dict) or not str(value.get("ar", "")).strip() or not str(value.get("he", "")).strip():
        raise ValueError("both 'ar' and 'he' are required")
    return {"ar": str(value["ar"]).strip(), "he": str(value["he"]).strip()}


class ServiceItemIn(BaseModel):
    name: dict
    description: dict
    category: dict
    billing_cycle: Literal["one_time", "monthly", "yearly"]
    price_min: float = Field(gt=0)
    price_max: float | None = Field(default=None, gt=0)
    unit: dict | None = None
    is_active: bool = True
    sort_order: int = 0

    @field_validator("name", "description", "category")
    @classmethod
    def check_bilingual(cls, v: dict) -> dict:
        return _bilingual(v)


class ServiceItemPatch(BaseModel):
    name: dict | None = None
    description: dict | None = None
    category: dict | None = None
    billing_cycle: Literal["one_time", "monthly", "yearly"] | None = None
    price_min: float | None = Field(default=None, gt=0)
    price_max: float | None = Field(default=None, gt=0)
    unit: dict | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class PackageIn(BaseModel):
    name: dict
    description: dict
    billing_cycle: Literal["one_time", "monthly", "yearly"]
    price_min: float = Field(gt=0)
    price_max: float | None = Field(default=None, gt=0)
    features: list[dict] | None = None
    audience: str = "all"
    is_active: bool = True
    sort_order: int = 0

    @field_validator("name", "description")
    @classmethod
    def check_bilingual(cls, v: dict) -> dict:
        return _bilingual(v)


class PackagePatch(BaseModel):
    name: dict | None = None
    description: dict | None = None
    billing_cycle: Literal["one_time", "monthly", "yearly"] | None = None
    price_min: float | None = Field(default=None, gt=0)
    price_max: float | None = Field(default=None, gt=0)
    cover_image_url: str | None = None
    features: list[dict] | None = None
    audience: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class LeadPatch(BaseModel):
    status: Literal["new", "in_progress", "won", "lost"] | None = None
    admin_notes: str | None = Field(default=None, max_length=8000)


class RequestPatch(BaseModel):
    status: Literal["new", "seen", "handled"]


@router.get("/services")
async def list_services(admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ServiceItem).order_by(ServiceItem.sort_order))).scalars().all()
    return [serialize_service_item(item) for item in rows]


@router.post("/services", status_code=201)
async def create_service(
    payload: ServiceItemIn, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = ServiceItem(**payload.model_dump())
    db.add(item)
    await record_audit_log(
        db, action="admin.service.create", resource_type="service_item",
        actor=admin, request=request, metadata={"name": payload.name},
    )
    await db.commit()
    await db.refresh(item)
    return serialize_service_item(item)


@router.patch("/services/{service_id}")
async def update_service(
    service_id: str, payload: ServiceItemPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = await db.get(ServiceItem, service_id)
    if not item:
        raise HTTPException(status_code=404, detail="Service not found")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("name", "description", "category"):
        if key in updates and updates[key] is not None:
            updates[key] = _bilingual(updates[key])
    for key, value in updates.items():
        setattr(item, key, value)
    await record_audit_log(
        db, action="admin.service.update", resource_type="service_item",
        resource_id=item.id, actor=admin, request=request, metadata=updates,
    )
    await db.commit()
    await db.refresh(item)
    return serialize_service_item(item)


@router.delete("/services/{service_id}")
async def deactivate_service(
    service_id: str, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = await db.get(ServiceItem, service_id)
    if not item:
        raise HTTPException(status_code=404, detail="Service not found")
    item.is_active = False
    await record_audit_log(
        db, action="admin.service.deactivate", resource_type="service_item",
        resource_id=item.id, actor=admin, request=request,
    )
    await db.commit()
    return {"ok": True}


# ── Packages ─────────────────────────────────────────────────────────────────

@router.get("/packages")
async def list_packages(admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Package).order_by(Package.sort_order))).scalars().all()
    return [serialize_package(pkg) for pkg in rows]


@router.post("/packages/seed")
async def seed_package_ladder(
    request: Request,
    overwrite: bool = False,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    """Insert the ready-made package ladder (idempotent; admin edits are kept)."""
    from ..services.package_seed import seed_packages

    result = await seed_packages(db, overwrite=overwrite)
    await record_audit_log(
        db, action="admin.package.seed", resource_type="package",
        actor=admin, request=request, metadata=result,
    )
    await db.commit()
    return result


@router.post("/packages", status_code=201)
async def create_package(
    payload: PackageIn, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    pkg = Package(**payload.model_dump())
    db.add(pkg)
    await record_audit_log(
        db, action="admin.package.create", resource_type="package",
        actor=admin, request=request, metadata={"name": payload.name},
    )
    await db.commit()
    await db.refresh(pkg)
    return serialize_package(pkg)


@router.patch("/packages/{package_id}")
async def update_package(
    package_id: str, payload: PackagePatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    pkg = await db.get(Package, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("name", "description"):
        if key in updates and updates[key] is not None:
            updates[key] = _bilingual(updates[key])
    for key, value in updates.items():
        setattr(pkg, key, value)
    await record_audit_log(
        db, action="admin.package.update", resource_type="package",
        resource_id=pkg.id, actor=admin, request=request, metadata=updates,
    )
    await db.commit()
    await db.refresh(pkg)
    return serialize_package(pkg)


@router.delete("/packages/{package_id}")
async def deactivate_package(
    package_id: str, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    pkg = await db.get(Package, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_active = False
    await record_audit_log(
        db, action="admin.package.deactivate", resource_type="package",
        resource_id=pkg.id, actor=admin, request=request,
    )
    await db.commit()
    return {"ok": True}


async def _set_package_cover(db, pkg, data: bytes, *, content_type, filename, prompt=None, generated=False):
    asset = await create_asset_from_bytes(
        db,
        kind=PACKAGE_COVER_KIND,
        title=f"package cover {pkg.id[:8]}",
        filename=filename,
        data=data,
        content_type=content_type,
        classification_prompt=prompt,
        metadata={"package_id": pkg.id, "generated": generated},
    )
    pkg.cover_image_url = asset.storage_url
    return asset


@router.post("/packages/{package_id}/cover")
async def upload_package_cover(
    package_id: str, request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    pkg = await db.get(Package, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    await _set_package_cover(
        db, pkg, data,
        content_type=file.content_type or "image/png",
        filename=file.filename or f"{package_id}.png",
    )
    await record_audit_log(
        db, action="admin.package.cover_upload", resource_type="package",
        resource_id=pkg.id, actor=admin, request=request,
    )
    await db.commit()
    await db.refresh(pkg)
    return serialize_package(pkg)


@router.post("/packages/{package_id}/cover/generate")
async def generate_package_cover(
    package_id: str, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    pkg = await db.get(Package, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    name = str((pkg.name or {}).get("ar") or (pkg.name or {}).get("he") or "package").strip()
    desc = str((pkg.description or {}).get("ar") or (pkg.description or {}).get("he") or "").strip()
    prompt = (
        "A premium, clean marketing cover image for a service package. "
        f"The package is: {name}. {desc} "
        "One strong visual concept that represents this offering, modern, vibrant and professional. "
        "Absolutely NO text, no words, no letters, no logos, no watermarks — a purely photographic/graphic cover. "
        "Wide 16:9 composition."
    )
    data = await asyncio.to_thread(_generate_image, prompt, "16:9")
    if not data:
        raise HTTPException(status_code=502, detail="cover_generation_failed")
    await _set_package_cover(
        db, pkg, data, content_type="image/png",
        filename=f"{package_id}.png", prompt=prompt, generated=True,
    )
    await record_audit_log(
        db, action="admin.package.cover_generate", resource_type="package",
        resource_id=pkg.id, actor=admin, request=request,
    )
    await db.commit()
    await db.refresh(pkg)
    return serialize_package(pkg)


@router.get("/leads")
async def list_leads(
    status: str | None = None,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    query = select(Lead).order_by(Lead.created_at.desc())
    if status in ("new", "in_progress", "won", "lost"):
        query = query.where(Lead.status == status)
    leads = (await db.execute(query)).scalars().all()
    request_lead_ids = {
        row for row in (await db.execute(select(ServiceRequest.lead_id))).scalars().all()
    }
    return [
        {**serialize_lead(lead), "has_request": lead.id in request_lead_ids}
        for lead in leads
    ]


@router.get("/leads/{lead_id}")
async def lead_detail(lead_id: str, admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    user = await db.get(User, lead.user_id)
    suite = await db.get(Suite, lead.suite_id) if lead.suite_id else None
    requests = (
        await db.execute(
            select(ServiceRequest).where(ServiceRequest.lead_id == lead.id).order_by(ServiceRequest.created_at.desc())
        )
    ).scalars().all()
    return {
        "lead": serialize_lead(lead),
        "user": serialize_user_public(user) if user else None,
        "suite": {"id": suite.id, "name": suite.name, "slug": suite.slug} if suite else None,
        "requests": [serialize_service_request(r) for r in requests],
    }


@router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: str, payload: LeadPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(lead, key, value)
    await record_audit_log(
        db, action="admin.lead.update", resource_type="lead",
        resource_id=lead.id, actor=admin, request=request, metadata=updates,
    )
    await db.commit()
    await db.refresh(lead)
    return serialize_lead(lead)


@router.patch("/service-requests/{request_id}")
async def update_service_request(
    request_id: str, payload: RequestPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    req = await db.get(ServiceRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = payload.status
    await record_audit_log(
        db, action="admin.service_request.update", resource_type="service_request",
        resource_id=req.id, actor=admin, request=request, metadata={"status": payload.status},
    )
    await db.commit()
    return serialize_service_request(req)
