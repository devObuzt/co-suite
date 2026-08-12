"""Public startbyconnec funnel: phone OTP → name → suite → plans → services → request."""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.llm_client import call_text_ai
from ..core.phone import normalize_phone
from ..core.security import create_access_token, get_current_user, hash_password
from ..models.services_catalog import (
    Lead,
    Package,
    PhoneOtp,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_package,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import MemberRole, Suite, SuiteMember, SuiteStatus
from ..models.user import User
from ..services.admin_audit import record_audit_log, serialize_user_public
from ..services.otp_sender import OtpSendError, generate_code, send_otp
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
    # Either pick individual services, or pick one ready-made package, or both.
    items: list[SelectionItem] = Field(default_factory=list)
    package_id: str | None = None
    customer_notes: str | None = Field(default=None, max_length=4000)


async def _lead_for(db: AsyncSession, user: User) -> Lead | None:
    return (await db.execute(select(Lead).where(Lead.user_id == user.id))).scalar_one_or_none()


async def _require_lead(db: AsyncSession, user: User) -> Lead:
    lead = await _lead_for(db, user)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found — register via the funnel first")
    return lead


# ── Phone-only OTP auth ──────────────────────────────────────────────────────

FUNNEL_STEPS = ["phone", "name", "suite", "plans", "services", "done"]


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=6, max_length=32)


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=8)


class FunnelProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)


class FunnelProgressIn(BaseModel):
    step: str


def _step_index(step: str | None) -> int:
    try:
        return FUNNEL_STEPS.index(step or "phone")
    except ValueError:
        return 0


def resume_step_for(lead: Lead) -> str:
    """Where a verified visitor should land: the stored step, floored by what
    the data proves they already did."""
    stored = (lead.progress or {}).get("step")
    floor = "name"
    if (lead.progress or {}).get("request_submitted"):
        floor = "done"
    elif lead.suite_id:
        floor = "plans"
    elif (lead.full_name or "").strip():
        floor = "suite"
    candidate = stored if stored in FUNNEL_STEPS else "name"
    return candidate if _step_index(candidate) >= _step_index(floor) else floor


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def _lead_by_phone(db: AsyncSession, phone: str) -> Lead | None:
    return (
        await db.execute(select(Lead).where(Lead.phone == phone).order_by(Lead.created_at))
    ).scalars().first()


@router.post("/otp/request")
async def otp_request(data: OtpRequestIn, db: AsyncSession = Depends(get_db)):
    phone = normalize_phone(data.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="invalid_phone")
    now = datetime.now(timezone.utc)

    # Lead is captured at first touch, before any verification.
    lead = await _lead_by_phone(db, phone)
    new_lead = lead is None
    if not lead:
        lead = Lead(phone=phone, progress={"step": "phone"})
        db.add(lead)

    last = (
        await db.execute(
            select(PhoneOtp)
            .where(PhoneOtp.phone == phone, PhoneOtp.verified_at.is_(None))
            .order_by(PhoneOtp.created_at.desc())
        )
    ).scalars().first()
    if last is not None:
        created = _as_utc(last.created_at)
        expires = _as_utc(last.expires_at)
        if created and expires and expires > now:
            elapsed = (now - created).total_seconds()
            if elapsed < settings.funnel_otp_resend_seconds:
                await db.commit()  # still persist the lead
                raise HTTPException(status_code=429, detail="resend_too_soon")

    otp = PhoneOtp(
        phone=phone,
        code=generate_code(),
        expires_at=now + timedelta(seconds=settings.funnel_otp_ttl_seconds),
    )
    db.add(otp)
    await db.commit()
    try:
        await send_otp(phone, otp.code)
    except OtpSendError:
        # The code is worthless if it never arrived — drop it so the visitor can
        # retry immediately instead of being held by the resend throttle.
        log.warning("otp delivery failed for %s", phone, exc_info=True)
        await db.delete(otp)
        await db.commit()
        raise HTTPException(status_code=502, detail="otp_send_failed")
    if new_lead:
        # The owner hears about every captured phone immediately, even if the
        # visitor never finishes. Send failure must not fail the request.
        try:
            base = (settings.frontend_url.split(",")[0] or "").strip().rstrip("/")
            await send_company_message(
                f"🟡 <b>ليد جديد — startbyconnec</b>\n📞 {phone}\n🔗 {base}/admin/leads"
            )
        except Exception:
            log.warning("new-lead telegram notification failed", exc_info=True)
    return {"ok": True}


@router.post("/otp/verify")
async def otp_verify(data: OtpVerifyIn, request: Request, db: AsyncSession = Depends(get_db)):
    phone = normalize_phone(data.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="invalid_phone")
    now = datetime.now(timezone.utc)

    otp = (
        await db.execute(
            select(PhoneOtp)
            .where(PhoneOtp.phone == phone, PhoneOtp.verified_at.is_(None))
            .order_by(PhoneOtp.created_at.desc())
        )
    ).scalars().first()
    if otp is None:
        raise HTTPException(status_code=400, detail="otp_not_found")
    expires = _as_utc(otp.expires_at)
    if expires is None or expires < now:
        raise HTTPException(status_code=400, detail="code_expired")
    if otp.attempts >= settings.funnel_otp_max_attempts:
        raise HTTPException(status_code=400, detail="too_many_attempts")
    if data.code.strip() != otp.code:
        otp.attempts += 1
        await db.commit()
        raise HTTPException(status_code=400, detail="invalid_code")

    otp.verified_at = now

    lead = await _lead_by_phone(db, phone)
    if not lead:
        lead = Lead(phone=phone, progress={"step": "phone"})
        db.add(lead)
        await db.flush()

    user: User | None = None
    if lead.user_id:
        user = (await db.execute(select(User).where(User.id == lead.user_id))).scalar_one_or_none()
    if user is None:
        user = (await db.execute(select(User).where(User.phone == phone))).scalars().first()
    if user is None:
        digits = phone.lstrip("+")
        email = f"p{digits}@lead.cosuite.app"
        clash = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if clash is not None:
            email = f"p{digits}.{secrets.token_hex(3)}@lead.cosuite.app"
        user = User(
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(16)),
            full_name=(lead.full_name or "").strip(),
            phone=phone,
            approval_status="funnel",
        )
        db.add(user)
        await db.flush()
    else:
        if (user.approval_status or "frozen") != "approved":
            user.approval_status = "funnel"
        if not user.phone:
            user.phone = phone

    lead.user_id = user.id
    progress = dict(lead.progress or {})
    if _step_index(progress.get("step")) < _step_index("name"):
        progress["step"] = "name"
    lead.progress = progress

    await record_audit_log(
        db, action="funnel.otp_verify", resource_type="lead", resource_id=lead.id,
        target_user_id=user.id, actor=user, request=request, metadata={"phone": phone},
    )
    await db.commit()
    await db.refresh(user)
    await db.refresh(lead)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": serialize_user_public(user),
        "lead": serialize_lead(lead),
        "resume_step": resume_step_for(lead),
    }


@router.post("/profile")
async def set_profile(
    data: FunnelProfileIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = data.full_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name_required")
    lead = await _require_lead(db, current_user)
    lead.full_name = name
    current_user.full_name = name
    progress = dict(lead.progress or {})
    if _step_index(progress.get("step")) < _step_index("suite"):
        progress["step"] = "suite"
    lead.progress = progress
    await record_audit_log(
        db, action="funnel.profile", resource_type="lead", resource_id=lead.id,
        target_user_id=current_user.id, actor=current_user, request=request,
    )
    await db.commit()
    await db.refresh(lead)
    await db.refresh(current_user)
    try:
        base = (settings.frontend_url.split(",")[0] or "").strip().rstrip("/")
        await send_company_message(
            f"🟢 <b>الليد سجّل اسمه — startbyconnec</b>\n👤 {name}\n📞 {lead.phone}\n🔗 {base}/admin/leads?lead={lead.id}"
        )
    except Exception:
        log.warning("lead-profile telegram notification failed", exc_info=True)
    return {
        "user": serialize_user_public(current_user),
        "lead": serialize_lead(lead),
        "resume_step": resume_step_for(lead),
    }


@router.post("/progress")
async def set_progress(
    data: FunnelProgressIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.step not in FUNNEL_STEPS:
        raise HTTPException(status_code=400, detail="invalid_step")
    lead = await _require_lead(db, current_user)
    progress = dict(lead.progress or {})
    if _step_index(data.step) > _step_index(progress.get("step")):
        progress["step"] = data.step
        lead.progress = progress
        await db.commit()
        await db.refresh(lead)
    return {"resume_step": resume_step_for(lead)}


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
        f"👤 {lead.full_name or '—'}",
        f"📞 {lead.phone}",
    ]
    if lead.email:
        lines.append(f"✉️ {lead.email}")
    lines.append("")
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
        return {"lead": None, "suite_id": None, "steps": {}, "resume_step": None}
    progress = dict(lead.progress or {})
    return {
        "lead": serialize_lead(lead),
        "suite_id": lead.suite_id,
        "steps": {
            "suite_created": bool(lead.suite_id),
            "request_submitted": bool(progress.get("request_submitted")),
        },
        "resume_step": resume_step_for(lead),
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
    progress = {**(lead.progress or {}), "suite_created": True}
    if _step_index(progress.get("step")) < _step_index("plans"):
        progress["step"] = "plans"
    lead.progress = progress
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


@router.get("/packages")
async def funnel_packages(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Active packages (with covers) shown on the pricing proposal page."""
    rows = (
        await db.execute(
            select(Package).where(Package.is_active.is_(True)).order_by(Package.sort_order)
        )
    ).scalars().all()
    return [serialize_package(pkg) for pkg in rows]


def _plan_signals(suite: Suite | None) -> dict[str, Any]:
    """What the generated plan says this business actually needs.

    Pulls the delivery-shaped parts of the plan — the monthly social work plan
    and the paid funnel — plus the message/demand context, so services can be
    proposed against real planned work instead of the brand blurb alone.
    """
    strategy = suite.strategy if suite and isinstance(suite.strategy, dict) else {}
    intelligence = strategy.get("marketing_intelligence") if isinstance(strategy.get("marketing_intelligence"), dict) else {}
    action = strategy.get("marketing_action_plan") if isinstance(strategy.get("marketing_action_plan"), dict) else {}

    def _titles(items: Any, limit: int) -> list[str]:
        out: list[str] = []
        for item in (items if isinstance(items, list) else [])[:limit]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("title") or item.get("idea") or item.get("name") or "").strip()
            fmt = str(item.get("format") or item.get("content_type") or item.get("channel") or "").strip()
            if label:
                out.append(f"{label}{f' ({fmt})' if fmt else ''}")
        return out

    social = _titles(action.get("social_items"), 14)
    ads = _titles(action.get("ad_funnel_items"), 10)
    message = intelligence.get("marketing_message")
    if isinstance(message, dict):
        message = message.get("text") or message.get("message") or ""
    demand = intelligence.get("demand_supply") if isinstance(intelligence.get("demand_supply"), dict) else {}
    return {
        "social_plan_items": social,
        "paid_funnel_items": ads,
        "marketing_message": str(message or "")[:600],
        "demand_recommendation": str(demand.get("recommendation") or "")[:400],
        # Volume drives how much production capacity the client actually needs.
        "social_item_count": len(action.get("social_items") or []) if isinstance(action.get("social_items"), list) else 0,
        "paid_item_count": len(action.get("ad_funnel_items") or []) if isinstance(action.get("ad_funnel_items"), list) else 0,
    }


@router.post("/recommendations")
async def recommendations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await _require_lead(db, current_user)
    if not lead.suite_id:
        if lead.recommendations:
            return lead.recommendations
        raise HTTPException(status_code=400, detail="Create the suite first")
    suite = (await db.execute(select(Suite).where(Suite.id == lead.suite_id))).scalar_one_or_none()
    signals = _plan_signals(suite)
    has_plan = bool(signals["social_plan_items"] or signals["paid_funnel_items"])

    cached = lead.recommendations if isinstance(lead.recommendations, dict) else None
    # A cached answer computed from the brand alone is stale once the plan
    # exists — the whole point is to propose against the planned work. A cache
    # written before packages existed has no package key at all; without this
    # check those leads never get packages proposed, because the branch below
    # short-circuits forever.
    if cached and "recommended_package_ids" not in cached:
        cached = None
    if cached and (cached.get("plan_based") or not has_plan):
        return cached

    brand = dict(suite.brand or {}) if suite else {}
    rows = (
        await db.execute(select(ServiceItem).where(ServiceItem.is_active.is_(True)))
    ).scalars().all()
    catalog_lines = [
        f"- id={item.id} | {item.name.get('ar', '')} | {item.billing_cycle} | from ₪{item.price_min}"
        for item in rows
    ]
    packages = (
        await db.execute(select(Package).where(Package.is_active.is_(True)).order_by(Package.price_min))
    ).scalars().all()
    package_lines = [
        f"- id={p.id} | {(p.name or {}).get('ar', '')} | ₪{int(p.price_min)}/mo | audience={p.audience}"
        for p in packages
    ]
    try:
        raw = await call_text_ai(
            max_tokens=900,
            system=(
                "You are proposing services and monthly packages to a business owner who has "
                "just received their marketing plan. Recommend ONLY services the plan actually "
                "requires to be executed — match the planned social content volume, formats and "
                "paid-funnel channels to catalog services. Then pick 3-7 packages that fit this "
                "business, cheapest first, giving a real range of options. Package rules: only "
                'include an audience="very_small" package if this business is clearly tiny '
                '(no real budget); only include audience="retail_web" packages for shops/sites '
                'that sell online or depend on search; audience="local_service" suits on-site '
                'trades; audience="all" fits anyone. Return ONLY JSON: '
                '{"recommended_service_ids": ["..."], "reasons": {"<id>": "<one short sentence, '
                'in the same language as the plan, naming the planned work it covers>"}, '
                '"recommended_package_ids": ["..."], "business_size": "very_small|small|normal"}.'
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Business brand JSON:\n{json.dumps(brand, ensure_ascii=False)[:2500]}\n\n"
                    f"Generated marketing plan signals:\n{json.dumps(signals, ensure_ascii=False)[:4000]}\n\n"
                    "Service catalog:\n" + "\n".join(catalog_lines) + "\n\n"
                    "Packages (monthly, VAT included):\n" + "\n".join(package_lines)
                ),
            }],
        )
    except Exception:
        log.warning("recommendations LLM call failed", exc_info=True)
        return cached or {"recommended_service_ids": []}
    try:
        parsed = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        valid = {r.id for r in rows}
        ids = [i for i in parsed.get("recommended_service_ids", []) if i in valid]
        raw_reasons = parsed.get("reasons") if isinstance(parsed.get("reasons"), dict) else {}
        reasons = {k: str(v)[:300] for k, v in raw_reasons.items() if k in ids}
        size = str(parsed.get("business_size") or "").strip().lower()
        by_id = {p.id: p for p in packages}
        picked = [by_id[i] for i in parsed.get("recommended_package_ids", []) if i in by_id]
        # The "very small budgets only" rule is enforced here, not left to the
        # model: that tier must never be shown to a normal business.
        if size != "very_small":
            picked = [p for p in picked if p.audience != "very_small"]
        if not picked:
            picked = [p for p in packages if p.audience == "all"]
        picked.sort(key=lambda p: p.price_min)
        package_ids = [p.id for p in picked[:7]]
    except Exception:
        log.warning("recommendations parse failed; storing empty list")
        ids, reasons, package_ids, size = [], {}, [], ""
    lead.recommendations = {
        "recommended_service_ids": ids,
        "reasons": reasons,
        "recommended_package_ids": package_ids,
        "business_size": size,
        "plan_based": has_plan,
    }
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

    # A chosen package is snapshotted alongside the services and added to the
    # monthly total, so the request shows exactly what the client picked.
    if data.package_id:
        pkg = await db.get(Package, data.package_id)
        if not pkg or not pkg.is_active:
            raise HTTPException(status_code=400, detail="Package not found")
        items = list(items) + [{
            "kind": "package",
            "package_id": pkg.id,
            "name": pkg.name or {},
            "billing_cycle": pkg.billing_cycle,
            "price_min": pkg.price_min,
            "price_max": pkg.price_max,
            "qty": 1,
        }]
        cycle = totals.setdefault(pkg.billing_cycle, {"min": 0.0, "max": 0.0})
        cycle["min"] = float(cycle.get("min") or 0) + float(pkg.price_min or 0)
        cycle["max"] = float(cycle.get("max") or 0) + float(pkg.price_max or pkg.price_min or 0)
    if not items:
        raise HTTPException(status_code=400, detail="Choose at least one service or a package")

    existing = (
        await db.execute(
            select(ServiceRequest).where(
                ServiceRequest.lead_id == lead.id, ServiceRequest.status == "new"
            )
        )
    ).scalar_one_or_none()

    if existing:
        # Coalesce: a pending request is still "new" — update in place instead of
        # creating a duplicate row / firing another Telegram notification.
        existing.items = items
        existing.totals = totals
        existing.customer_notes = (data.customer_notes or "").strip() or None
        lead.progress = {**(lead.progress or {}), "request_submitted": True, "step": "done"}
        await record_audit_log(
            db, action="funnel.service_request", resource_type="service_request",
            resource_id=existing.id, suite_id=lead.suite_id, target_user_id=current_user.id,
            actor=current_user, request=request, metadata={"totals": totals, "coalesced": True},
        )
        await db.commit()
        await db.refresh(existing)
        return serialize_service_request(existing)

    req = ServiceRequest(
        lead_id=lead.id,
        items=items,
        totals=totals,
        customer_notes=(data.customer_notes or "").strip() or None,
    )
    db.add(req)
    lead.progress = {**(lead.progress or {}), "request_submitted": True, "step": "done"}
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
