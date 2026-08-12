from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Base, get_db
from ..core.config import settings
from ..core.security import get_current_user, hash_password
from ..models.admin import AppTextOverride, AuditLog, CreativeAsset, ProviderUsageEvent
from ..models.billing import UsageEvent
from ..models.generation_job import GenerationJob
from ..models.suite import Suite, SuiteMember
from ..models.user import User
from ..services.admin_audit import (
    period_bounds,
    record_audit_log,
    require_super_admin,
    serialize_user_public,
)
from ..services.provider_pricing import infer_provider_usage_from_billing_event
from ..services.creative_assets import (
    ALL_KINDS,
    create_asset_from_bytes,
    create_asset_from_remote,
    seed_builtin_creative_assets,
    serialize_creative_asset,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    is_verified: bool | None = None
    is_super_admin: bool | None = None
    approval_status: Literal["approved", "frozen", "funnel"] | None = None


class AdminPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class AdminUserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    is_super_admin: bool = False
    is_active: bool = True
    is_verified: bool = True
    approval_status: Literal["approved", "frozen", "funnel"] = "approved"


class AdminUserBulkDeactivate(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=200)


class AppTextOverrideUpdate(BaseModel):
    language: str = Field(min_length=2, max_length=12)
    key: str = Field(min_length=1, max_length=240)
    value: str | None = Field(default=None, max_length=5000)


class CreativeAssetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    tags: list[str] | None = None
    use_cases: list[str] | None = None
    classification: dict[str, Any] | None = None
    active: bool | None = None


class CreativeAssetRemoteCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=40)
    source_url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=240)


async def _admin_user(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    return await require_super_admin(current_user, db)


def _apply_period(query, model, period: str, start: datetime | None, end: datetime | None):
    period_start, period_end = period_bounds(period, start, end)
    if period_start:
        query = query.where(model.created_at >= period_start)
    if period_end:
        query = query.where(model.created_at < period_end)
    return query


def _normalize_language_code(value: str) -> str:
    return re.split(r"[-_]", value.strip().lower(), maxsplit=1)[0][:12]


def _app_text_override_out(row: AppTextOverride) -> dict[str, Any]:
    return {
        "id": row.id,
        "language": row.language,
        "key": row.text_key,
        "value": row.value,
        "updated_by_email": row.updated_by_email,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/summary")
async def summary(
    period: str = Query(default="month", pattern="^(today|yesterday|week|month|all|custom)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user_count = await db.scalar(select(func.count(User.id)))
    active_user_count = await db.scalar(select(func.count(User.id)).where(User.is_active.is_(True)))
    suite_count = await db.scalar(select(func.count(Suite.id)))
    job_count = await db.scalar(_apply_period(select(func.count(GenerationJob.id)), GenerationJob, period, start, end))
    provider_cost = await db.scalar(
        _apply_period(select(func.coalesce(func.sum(ProviderUsageEvent.actual_cost_usd), 0.0)), ProviderUsageEvent, period, start, end)
    )
    billed_amount = await db.scalar(
        _apply_period(select(func.coalesce(func.sum(UsageEvent.billed_amount), 0.0)), UsageEvent, period, start, end)
    )
    return {
        "users": user_count or 0,
        "active_users": active_user_count or 0,
        "suites": suite_count or 0,
        "generation_jobs": job_count or 0,
        "provider_cost_usd": provider_cost or 0.0,
        "billed_amount_usd": billed_amount or 0.0,
    }


@router.get("/providers")
async def providers(admin: User = Depends(_admin_user)):
    return [
        {
            "provider": "anthropic",
            "configured": bool(settings.anthropic_api_key.strip()),
            "models": [settings.anthropic_text_model, settings.anthropic_fast_model],
            "operations": ["text generation", "strategy", "keywords", "marketing plan"],
        },
        {
            "provider": "openai",
            "configured": bool(settings.openai_api_key.strip()),
            "models": [settings.openai_text_model, settings.openai_fast_model, settings.openai_image_model],
            "operations": ["text generation", "image generation"],
        },
        {
            "provider": "google",
            "configured": bool(settings.google_api_key.strip() or settings.google_ads_developer_token.strip()),
            "models": [settings.google_image_model, settings.google_video_model, "Google Ads Keyword Planner"],
            "operations": ["image generation", "video generation", "keyword planner", "ads metrics"],
        },
        {
            "provider": "serpapi",
            "configured": bool(settings.serpapi_api_key.strip()),
            "models": ["google", "google_maps"],
            "operations": ["competitor search", "organic results", "maps", "social source discovery"],
        },
        {
            "provider": "meta",
            "configured": bool(settings.meta_app_id.strip() and settings.meta_app_secret.strip()),
            "models": ["Meta Graph API", "Meta Ads Library"],
            "operations": ["publishing", "campaigns", "ads library"],
        },
        {
            "provider": "morning",
            "configured": bool(settings.morning_api_key.strip() or settings.morning_subscribe_url.strip()),
            "models": ["Morning billing"],
            "operations": ["subscriptions", "payments"],
        },
    ]


@router.get("/app-text")
async def app_text_overrides(
    language: str = Query(default="ar", min_length=2, max_length=12),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    lang = _normalize_language_code(language)
    rows = (
        await db.execute(
            select(AppTextOverride)
            .where(AppTextOverride.language == lang)
            .order_by(AppTextOverride.text_key.asc())
        )
    ).scalars().all()
    return {
        "language": lang,
        "overrides": [_app_text_override_out(row) for row in rows],
    }


@router.patch("/app-text")
async def update_app_text_override(
    payload: AppTextOverrideUpdate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    lang = _normalize_language_code(payload.language)
    key = payload.key.strip()
    value = payload.value.strip() if isinstance(payload.value, str) else None
    existing = (
        await db.execute(
            select(AppTextOverride)
            .where(AppTextOverride.language == lang)
            .where(AppTextOverride.text_key == key)
            .limit(1)
        )
    ).scalar_one_or_none()

    if value is None:
        if existing:
            await db.delete(existing)
        await record_audit_log(
            db,
            action="admin.app_text.reset",
            resource_type="app_text",
            resource_id=f"{lang}:{key}",
            actor=admin,
            request=request,
            metadata={"language": lang, "key": key},
        )
        await db.commit()
        return {"ok": True, "language": lang, "key": key, "override": None}

    if existing:
        before = existing.value
        existing.value = value
        existing.updated_by_user_id = admin.id
        existing.updated_by_email = admin.email
        row = existing
    else:
        before = None
        row = AppTextOverride(
            language=lang,
            text_key=key,
            value=value,
            updated_by_user_id=admin.id,
            updated_by_email=admin.email,
        )
        db.add(row)
    await record_audit_log(
        db,
        action="admin.app_text.update",
        resource_type="app_text",
        resource_id=f"{lang}:{key}",
        actor=admin,
        request=request,
        metadata={"language": lang, "key": key, "before": before, "after": value},
    )
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "language": lang, "key": key, "override": _app_text_override_out(row)}


@router.get("/billing-usage")
async def billing_usage(
    period: str = Query(default="month", pattern="^(today|yesterday|week|month|all|custom)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    suite_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(UsageEvent, Suite.name, User.email)
        .outerjoin(Suite, UsageEvent.suite_id == Suite.id)
        .outerjoin(User, Suite.owner_id == User.id)
        .order_by(UsageEvent.created_at.desc())
        .limit(limit)
    )
    query = _apply_period(query, UsageEvent, period, start, end)
    if suite_id:
        query = query.where(UsageEvent.suite_id == suite_id)
    if event_type:
        query = query.where(UsageEvent.event_type == event_type)
    rows = (await db.execute(query)).all()
    return [_billing_usage_out(event, suite_name, owner_email) for event, suite_name, owner_email in rows]


@router.get("/users")
async def users(
    q: str | None = None,
    approval: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    suite_counts = (
        select(Suite.owner_id, func.count(Suite.id).label("suite_count"))
        .group_by(Suite.owner_id)
        .subquery()
    )
    query = (
        select(User, func.coalesce(suite_counts.c.suite_count, 0))
        .outerjoin(suite_counts, suite_counts.c.owner_id == User.id)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
    if approval in ("approved", "frozen", "funnel"):
        query = query.where(User.approval_status == approval)
    rows = (await db.execute(query)).all()
    return [
        {
            **serialize_user_public(user),
            "suite_count": int(suite_count or 0),
        }
        for user, suite_count in rows
    ]


@router.post("/users", status_code=201)
async def create_user(
    payload: AdminUserCreate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    # Exact-match uniqueness to mirror login/signup (email stored as-is).
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        is_active=payload.is_active,
        is_verified=payload.is_verified,
        is_super_admin=payload.is_super_admin,
        approval_status=payload.approval_status,
    )
    db.add(user)
    await db.flush()
    await record_audit_log(
        db,
        action="admin.user.create",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=admin,
        request=request,
        metadata={"email": user.email, "is_super_admin": user.is_super_admin},
    )
    await db.commit()
    await db.refresh(user)
    return serialize_user_public(user)


@router.post("/users/bulk-deactivate")
async def bulk_deactivate_users(
    payload: AdminUserBulkDeactivate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    # Soft-deactivate (is_active=False), consistent with single-user delete.
    # The admin's own account is always skipped, never their session-killer.
    ids = [uid for uid in dict.fromkeys(payload.user_ids) if uid != admin.id]
    users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all() if ids else []
    deactivated = 0
    for user in users:
        if user.is_active:
            user.is_active = False
            deactivated += 1
    if deactivated:
        await record_audit_log(
            db,
            action="admin.user.bulk_deactivate",
            resource_type="user",
            resource_id=None,
            actor=admin,
            request=request,
            metadata={"user_ids": [u.id for u in users if not u.is_active], "count": deactivated},
        )
    await db.commit()
    return {"ok": True, "deactivated": deactivated, "skipped_self": admin.id in set(payload.user_ids)}


@router.delete("/users/{user_id}/permanent")
async def hard_delete_user(
    user_id: str,
    request: Request,
    confirm_email: str = Query(..., description="Must equal the user's email — guards against a mis-click"),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Irreversibly delete a user row. Deactivation (DELETE /users/{id}) is the reversible option.

    Refuses while the user still owns suites: Suite.owner_id is NOT NULL, so the
    delete would either fail or require destroying the suites and everything
    under them. The admin must delete or transfer those suites first — that stays
    a conscious, separate decision rather than a hidden cascade.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Admin cannot delete their own account")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (confirm_email or "").strip().lower() != (user.email or "").strip().lower():
        raise HTTPException(status_code=400, detail="confirm_email does not match this user's email")

    owned = (await db.execute(select(func.count(Suite.id)).where(Suite.owner_id == user_id))).scalar() or 0
    if owned:
        raise HTTPException(
            status_code=409,
            detail=f"User still owns {owned} suite(s). Delete or transfer them before permanent deletion.",
        )

    email = user.email
    # Detach every nullable reference so the row can go without taking history
    # (audit logs, jobs, posts, usage) with it. Derived from the mapper rather
    # than hand-listed: a hand-written list silently goes stale the moment a
    # model gains a user FK, and the failure only shows up as a 500 here.
    # The NOT NULL referrers are the two handled explicitly: suites.owner_id is
    # refused above, and suite_members rows are deleted below.
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not any(fk.column.table.name == "users" for fk in column.foreign_keys):
                continue
            if table.name == "suite_members" or not column.nullable:
                continue
            await db.execute(
                update(table).where(column == user_id).values({column.name: None})
            )
    await db.execute(delete(SuiteMember).where(SuiteMember.user_id == user_id))

    await record_audit_log(
        db,
        action="admin.user.hard_delete",
        resource_type="user",
        resource_id=user_id,
        actor=admin,
        request=request,
        metadata={"email": email},
    )
    await db.delete(user)
    await db.commit()
    return {"ok": True, "deleted": True, "email": email}


@router.get("/users/{user_id}")
async def user_detail(
    user_id: str,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    suites = (await db.execute(select(Suite).where(Suite.owner_id == user.id).order_by(Suite.created_at.desc()))).scalars().all()
    return {
        "user": serialize_user_public(user),
        "suites": [
            {
                "id": suite.id,
                "name": suite.name,
                "slug": suite.slug,
                "status": suite.status.value if hasattr(suite.status, "value") else str(suite.status),
                "ai_generation_enabled": suite.ai_generation_enabled,
                "auto_publish_enabled": suite.auto_publish_enabled,
                "created_at": suite.created_at,
                "updated_at": suite.updated_at,
            }
            for suite in suites
        ],
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    before = serialize_user_public(user)
    for field in ("email", "full_name", "is_active", "is_verified", "is_super_admin", "approval_status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(user, field, value)
    await record_audit_log(
        db,
        action="admin.user.update",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=admin,
        request=request,
        metadata={"before": before, "after": serialize_user_public(user)},
    )
    await db.commit()
    await db.refresh(user)
    return serialize_user_public(user)


@router.post("/users/{user_id}/password")
async def change_password(
    user_id: str,
    payload: AdminPasswordUpdate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(payload.password)
    await record_audit_log(
        db,
        action="admin.user.password_reset",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=admin,
        request=request,
        metadata={"email": user.email},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate their own account")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await record_audit_log(
        db,
        action="admin.user.deactivate",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=admin,
        request=request,
        metadata={"email": user.email},
    )
    await db.commit()
    return {"ok": True, "deactivated": True}


@router.get("/audit-logs")
async def audit_logs(
    period: str = Query(default="month", pattern="^(today|yesterday|week|month|all|custom)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    action: str | None = None,
    suite_id: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    query = _apply_period(query, AuditLog, period, start, end)
    if action:
        query = query.where(AuditLog.action == action)
    if suite_id:
        query = query.where(AuditLog.suite_id == suite_id)
    if user_id:
        query = query.where(or_(AuditLog.actor_user_id == user_id, AuditLog.target_user_id == user_id))
    logs = (await db.execute(query)).scalars().all()
    return [_audit_log_out(log) for log in logs]


@router.get("/provider-usage")
async def provider_usage(
    period: str = Query(default="month", pattern="^(today|yesterday|week|month|all|custom)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ProviderUsageEvent).order_by(ProviderUsageEvent.created_at.desc()).limit(limit)
    query = _apply_period(query, ProviderUsageEvent, period, start, end)
    if provider:
        query = query.where(ProviderUsageEvent.provider == provider)
    if model:
        query = query.where(ProviderUsageEvent.model == model)
    events = (await db.execute(query)).scalars().all()
    return [_provider_usage_out(event) for event in events]


@router.get("/provider-usage/summary")
async def provider_usage_summary(
    period: str = Query(default="month", pattern="^(today|yesterday|week|month|all|custom)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(
        ProviderUsageEvent.provider,
        ProviderUsageEvent.model,
        func.count(ProviderUsageEvent.id),
        func.coalesce(func.sum(ProviderUsageEvent.total_tokens), 0),
        func.coalesce(func.sum(ProviderUsageEvent.actual_cost_usd), 0.0),
        func.coalesce(func.sum(case((ProviderUsageEvent.status == "success", 1), else_=0)), 0),
    ).group_by(ProviderUsageEvent.provider, ProviderUsageEvent.model)
    query = _apply_period(query, ProviderUsageEvent, period, start, end)
    rows = (await db.execute(query)).all()
    return [
        {
            "provider": provider,
            "model": model,
            "requests": int(requests or 0),
            "total_tokens": int(total_tokens or 0),
            "actual_cost_usd": float(cost or 0.0),
            "successes": int(successes or 0),
        }
        for provider, model, requests, total_tokens, cost, successes in rows
    ]


@router.get("/creative-assets")
async def creative_assets(
    kind: str | None = Query(default=None, max_length=40),
    active: bool | None = True,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=500),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CreativeAsset).order_by(CreativeAsset.kind.asc(), CreativeAsset.usage_count.desc(), CreativeAsset.created_at.desc()).limit(limit)
    if kind:
        if kind not in ALL_KINDS:
            raise HTTPException(status_code=400, detail="Unsupported creative asset kind")
        query = query.where(CreativeAsset.kind == kind)
    if active is not None:
        query = query.where(CreativeAsset.active.is_(active))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(CreativeAsset.title.ilike(pattern), CreativeAsset.storage_url.ilike(pattern)))
    rows = (await db.execute(query)).scalars().all()
    return [serialize_creative_asset(row) for row in rows]


@router.post("/creative-assets/seed-builtins")
async def seed_creative_asset_builtins(
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    seeded = await seed_builtin_creative_assets(db)
    await record_audit_log(
        db,
        action="admin.creative_asset.seed_builtins",
        resource_type="creative_asset",
        actor=admin,
        request=request,
        metadata={"seeded": seeded},
    )
    await db.commit()
    return {"ok": True, "seeded": seeded}


@router.post("/creative-assets")
async def create_creative_asset_remote(
    payload: CreativeAssetRemoteCreate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.kind not in ALL_KINDS:
        raise HTTPException(status_code=400, detail="Unsupported creative asset kind")
    try:
        row = await create_asset_from_remote(
            db,
            kind=payload.kind,
            source_url=payload.source_url,
            title=payload.title,
            created_by_user_id=admin.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import asset: {exc}") from exc
    await record_audit_log(
        db,
        action="admin.creative_asset.create_remote",
        resource_type="creative_asset",
        resource_id=row.id,
        actor=admin,
        request=request,
        metadata={"kind": row.kind, "title": row.title, "source_url": payload.source_url},
    )
    await db.commit()
    await db.refresh(row)
    return serialize_creative_asset(row)


@router.post("/creative-assets/upload")
async def upload_creative_asset(
    request: Request,
    kind: str = Form(...),
    title: str = Form(""),
    file: UploadFile = File(...),
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if kind not in ALL_KINDS:
        raise HTTPException(status_code=400, detail="Unsupported creative asset kind")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded asset is empty")
    if len(data) > 300 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Creative asset is too large. Maximum is 300 MB.")
    row = await create_asset_from_bytes(
        db,
        kind=kind,
        title=title or file.filename or kind,
        filename=file.filename or f"{kind}.bin",
        data=data,
        content_type=file.content_type,
        created_by_user_id=admin.id,
    )
    await record_audit_log(
        db,
        action="admin.creative_asset.upload",
        resource_type="creative_asset",
        resource_id=row.id,
        actor=admin,
        request=request,
        metadata={"kind": row.kind, "title": row.title, "content_type": row.content_type},
    )
    await db.commit()
    await db.refresh(row)
    return serialize_creative_asset(row)


@router.patch("/creative-assets/{asset_id}")
async def update_creative_asset(
    asset_id: str,
    payload: CreativeAssetUpdate,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(CreativeAsset, asset_id)
    if not row:
        raise HTTPException(status_code=404, detail="Creative asset not found")
    before = serialize_creative_asset(row)
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.tags is not None:
        row.tags = [str(item).strip()[:60] for item in payload.tags if str(item).strip()][:30]
    if payload.use_cases is not None:
        row.use_cases = [str(item).strip()[:80] for item in payload.use_cases if str(item).strip()][:30]
    if payload.classification is not None:
        row.classification = payload.classification
    if payload.active is not None:
        row.active = payload.active
    await record_audit_log(
        db,
        action="admin.creative_asset.update",
        resource_type="creative_asset",
        resource_id=row.id,
        actor=admin,
        request=request,
        metadata={"before": before, "after": serialize_creative_asset(row)},
    )
    await db.commit()
    await db.refresh(row)
    return serialize_creative_asset(row)


@router.delete("/creative-assets/{asset_id}")
async def deactivate_creative_asset(
    asset_id: str,
    request: Request,
    admin: User = Depends(_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(CreativeAsset, asset_id)
    if not row:
        raise HTTPException(status_code=404, detail="Creative asset not found")
    row.active = False
    await record_audit_log(
        db,
        action="admin.creative_asset.deactivate",
        resource_type="creative_asset",
        resource_id=row.id,
        actor=admin,
        request=request,
        metadata={"kind": row.kind, "title": row.title},
    )
    await db.commit()
    return {"ok": True, "deactivated": True}


def _audit_log_out(log: AuditLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "actor_user_id": log.actor_user_id,
        "actor_email": log.actor_email,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "suite_id": log.suite_id,
        "target_user_id": log.target_user_id,
        "metadata": log.metadata_json or {},
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "created_at": log.created_at,
    }


def _provider_usage_out(event: ProviderUsageEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "provider": event.provider,
        "model": event.model,
        "endpoint": event.endpoint,
        "operation": event.operation,
        "status": event.status,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "total_tokens": event.total_tokens,
        "actual_cost_usd": event.actual_cost_usd,
        "suite_id": event.suite_id,
        "user_id": event.user_id,
        "generation_job_id": event.generation_job_id,
        "latency_ms": event.latency_ms,
        "request_id": event.request_id,
        "metadata": event.metadata_json or {},
        "created_at": event.created_at,
    }


def _billing_usage_out(event: UsageEvent, suite_name: str | None = None, owner_email: str | None = None) -> dict[str, Any]:
    provider = infer_provider_usage_from_billing_event(
        event.event_type,
        actual_cost_usd=event.actual_cost_usd,
        metadata=event.event_data,
    )
    return {
        "id": event.id,
        "suite_id": event.suite_id,
        "suite_name": suite_name,
        "owner_email": owner_email,
        "event_type": event.event_type,
        "ledger_account": event.ledger_account.value if hasattr(event.ledger_account, "value") else str(event.ledger_account),
        "billing_event_type": event.billing_event_type.value if hasattr(event.billing_event_type, "value") else str(event.billing_event_type),
        "amount_tokens": event.amount_tokens,
        "balance_after_tokens": event.balance_after_tokens,
        "amount_usd": event.amount_usd,
        "balance_after_usd": event.balance_after_usd,
        "actual_cost_usd": event.actual_cost_usd,
        "billed_amount": event.billed_amount,
        "external_ref": event.external_ref,
        "idempotency_key": event.idempotency_key,
        "event_data": event.event_data or {},
        "provider": provider["provider"],
        "model": provider.get("model"),
        "operation": provider["operation"],
        "cost_basis": provider["metadata"].get("cost_basis"),
        "created_at": event.created_at,
    }
