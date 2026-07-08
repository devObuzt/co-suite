"""Admin CRUD for the startbyconnec service catalog + leads inbox."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.admin_audit import record_audit_log, require_super_admin, serialize_user_public

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
