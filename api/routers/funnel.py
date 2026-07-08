"""Public startbyconnec funnel: register → suite → plans → services → request."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.llm_client import call_text_ai
from ..core.security import create_access_token, get_current_user, hash_password
from ..models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import MemberRole, Suite, SuiteMember, SuiteStatus
from ..models.user import User
from ..services.admin_audit import record_audit_log, serialize_user_public
from ..services.service_pricing import compute_totals
from ..services.telegram_notify import send_company_message
from .suites import slugify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/funnel", tags=["funnel"])


class FunnelRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1)
    phone: str = Field(min_length=6)

    @field_validator("phone")
    @classmethod
    def phone_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("phone required")
        return v.strip()


class FunnelEnrollRequest(BaseModel):
    phone: str | None = None


class FunnelSuiteRequest(BaseModel):
    name: str = Field(min_length=1)


class SelectionItem(BaseModel):
    service_id: str
    qty: int = Field(default=1, ge=1, le=99)


class FunnelServiceRequestIn(BaseModel):
    items: list[SelectionItem] = Field(min_length=1)
    customer_notes: str | None = Field(default=None, max_length=4000)


async def _lead_for(db: AsyncSession, user: User) -> Lead | None:
    return (await db.execute(select(Lead).where(Lead.user_id == user.id))).scalar_one_or_none()


async def _require_lead(db: AsyncSession, user: User) -> Lead:
    lead = await _lead_for(db, user)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found — register via the funnel first")
    return lead


def snapshot_selection(
    selections: list[dict], catalog: dict[str, ServiceItem]
) -> tuple[list[dict], dict]:
    """Validate ids against the active catalog and snapshot names + prices."""
    items: list[dict] = []
    for sel in selections:
        service_id = sel["service_id"] if isinstance(sel, dict) else sel.service_id
        qty = int(sel.get("qty", 1) if isinstance(sel, dict) else sel.qty)
        item = catalog.get(service_id)
        if not item or not item.is_active:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service_id}")
        snapshot = serialize_service_item(item)
        snapshot["qty"] = max(1, qty)
        items.append(snapshot)
    totals = compute_totals(items)
    return items, totals


def _fmt(amount: float) -> str:
    return f"{amount:,.0f}"


def lead_notification_text(lead: Lead, totals: dict, *, frontend_url: str) -> str:
    base = (frontend_url.split(",")[0] or "").strip().rstrip("/")
    cycle_labels = {"one_time": "لمرة واحدة", "monthly": "شهري", "yearly": "سنوي"}
    lines = [
        "🟢 <b>طلب خدمة جديد — startbyconnec</b>",
        f"👤 {lead.full_name}",
        f"📞 {lead.phone}",
        f"✉️ {lead.email}",
        "",
    ]
    for cycle, bucket in totals.items():
        label = cycle_labels.get(cycle, cycle)
        if bucket["min"] == bucket["max"]:
            lines.append(f"💰 {label}: ₪{_fmt(bucket['min'])}")
        else:
            lines.append(f"💰 {label}: ₪{_fmt(bucket['min'])}–{_fmt(bucket['max'])}")
    lines += [
        "",
        f"🔗 {base}/admin/leads?lead={lead.id}",
    ]
    if lead.suite_id:
        lines.append(f"🏠 {base}/suite/{lead.suite_id}/profile")
    return "\n".join(lines)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: FunnelRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        approval_status="funnel",
    )
    db.add(user)
    await db.flush()
    lead = Lead(
        user_id=user.id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        progress={"registered": True},
    )
    db.add(lead)
    await record_audit_log(
        db, action="funnel.register", resource_type="lead", resource_id=lead.id,
        target_user_id=user.id, actor=user, request=request, metadata={"email": user.email},
    )
    await db.commit()
    await db.refresh(user)
    await db.refresh(lead)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": serialize_user_public(user),
        "lead_id": lead.id,
    }


@router.post("/enroll")
async def enroll(
    data: FunnelEnrollRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (current_user.approval_status or "frozen") == "approved":
        raise HTTPException(status_code=400, detail="Account already approved")
    if data.phone and data.phone.strip():
        current_user.phone = data.phone.strip()
    if not current_user.phone:
        raise HTTPException(status_code=400, detail="phone_required")
    current_user.approval_status = "funnel"
    lead = await _lead_for(db, current_user)
    if not lead:
        lead = Lead(
            user_id=current_user.id,
            full_name=current_user.full_name,
            email=current_user.email,
            phone=current_user.phone,
            progress={"registered": True},
        )
        db.add(lead)
    await record_audit_log(
        db, action="funnel.enroll", resource_type="lead", resource_id=lead.id,
        target_user_id=current_user.id, actor=current_user, request=request,
    )
    await db.commit()
    await db.refresh(lead)
    return {"user": serialize_user_public(current_user), "lead_id": lead.id}


@router.get("/state")
async def state(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await _lead_for(db, current_user)
    if not lead:
        return {"lead": None, "suite_id": None, "steps": {}}
    progress = dict(lead.progress or {})
    return {
        "lead": serialize_lead(lead),
        "suite_id": lead.suite_id,
        "steps": {
            "suite_created": bool(lead.suite_id),
            "request_submitted": bool(progress.get("request_submitted")),
        },
    }


@router.post("/suite", status_code=status.HTTP_201_CREATED)
async def create_funnel_suite(
    data: FunnelSuiteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lead = await _require_lead(db, current_user)
    if lead.suite_id:
        raise HTTPException(status_code=409, detail="funnel_suite_exists")
    owner_email = settings.lead_owner_email.strip().lower()
    owner = (
        await db.execute(select(User).where(User.email.ilike(owner_email)))
    ).scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=500, detail=f"Lead owner account missing: {owner_email}")

    base_slug = slugify(data.name) or "suite"
    slug = base_slug
    counter = 1
    while (await db.execute(select(Suite).where(Suite.slug == slug))).scalar_one_or_none():
        slug = f"{base_slug}-{counter}"
        counter += 1

    suite = Suite(owner_id=owner.id, name=data.name, slug=slug, status=SuiteStatus.onboarding)
    db.add(suite)
    await db.flush()
    db.add(SuiteMember(suite_id=suite.id, user_id=current_user.id, role=MemberRole.member, can_chat_ai=True))
    lead.suite_id = suite.id
    lead.progress = {**(lead.progress or {}), "suite_created": True}
    await record_audit_log(
        db, action="funnel.suite_created", resource_type="suite", resource_id=suite.id,
        suite_id=suite.id, target_user_id=current_user.id, actor=current_user, request=request,
    )
    await db.commit()
    await db.refresh(suite)
    return {"id": suite.id, "name": suite.name, "slug": suite.slug, "status": suite.status.value}


@router.get("/catalog")
async def catalog(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ServiceItem).where(ServiceItem.is_active.is_(True)).order_by(ServiceItem.sort_order)
        )
    ).scalars().all()
    return [serialize_service_item(item) for item in rows]


@router.post("/recommendations")
async def recommendations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await _require_lead(db, current_user)
    if lead.recommendations:
        return lead.recommendations
    if not lead.suite_id:
        raise HTTPException(status_code=400, detail="Create the suite first")
    suite = (await db.execute(select(Suite).where(Suite.id == lead.suite_id))).scalar_one_or_none()
    brand = dict(suite.brand or {}) if suite else {}
    rows = (
        await db.execute(select(ServiceItem).where(ServiceItem.is_active.is_(True)))
    ).scalars().all()
    catalog_lines = [
        f"- id={item.id} | {item.name.get('ar', '')} | {item.billing_cycle}"
        for item in rows
    ]
    raw = await call_text_ai(
        max_tokens=400,
        system=(
            "You match marketing/web services to a business. Return ONLY a JSON object: "
            '{"recommended_service_ids": ["..."]} with 3-6 ids from the provided catalog.'
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Business brand JSON:\n{json.dumps(brand, ensure_ascii=False)[:4000]}\n\n"
                f"Catalog:\n" + "\n".join(catalog_lines)
            ),
        }],
    )
    try:
        parsed = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        ids = [i for i in parsed.get("recommended_service_ids", []) if any(r.id == i for r in rows)]
    except Exception:
        log.warning("recommendations parse failed; storing empty list")
        ids = []
    lead.recommendations = {"recommended_service_ids": ids}
    await db.commit()
    return lead.recommendations


@router.post("/service-request", status_code=status.HTTP_201_CREATED)
async def submit_service_request(
    data: FunnelServiceRequestIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lead = await _require_lead(db, current_user)
    rows = (
        await db.execute(select(ServiceItem).where(ServiceItem.is_active.is_(True)))
    ).scalars().all()
    items, totals = snapshot_selection([s.model_dump() for s in data.items], {r.id: r for r in rows})
    req = ServiceRequest(
        lead_id=lead.id,
        items=items,
        totals=totals,
        customer_notes=(data.customer_notes or "").strip() or None,
    )
    db.add(req)
    lead.progress = {**(lead.progress or {}), "request_submitted": True}
    if lead.status == "new":
        lead.status = "in_progress"
    await record_audit_log(
        db, action="funnel.service_request", resource_type="service_request",
        resource_id=req.id, suite_id=lead.suite_id, target_user_id=current_user.id,
        actor=current_user, request=request, metadata={"totals": totals},
    )
    await db.commit()
    await db.refresh(req)
    await send_company_message(lead_notification_text(lead, totals, frontend_url=settings.frontend_url))
    return serialize_service_request(req)
