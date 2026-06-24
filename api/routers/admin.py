from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user, hash_password
from ..models.admin import AuditLog, ProviderUsageEvent
from ..models.billing import UsageEvent
from ..models.generation_job import GenerationJob
from ..models.suite import Suite
from ..models.user import User
from ..services.admin_audit import (
    period_bounds,
    record_audit_log,
    require_super_admin,
    serialize_user_public,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    is_verified: bool | None = None
    is_super_admin: bool | None = None


class AdminPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=200)


async def _admin_user(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    return await require_super_admin(current_user, db)


def _apply_period(query, model, period: str, start: datetime | None, end: datetime | None):
    period_start, period_end = period_bounds(period, start, end)
    if period_start:
        query = query.where(model.created_at >= period_start)
    if period_end:
        query = query.where(model.created_at < period_end)
    return query


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


@router.get("/users")
async def users(
    q: str | None = None,
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
    rows = (await db.execute(query)).all()
    return [
        {
            **serialize_user_public(user),
            "suite_count": int(suite_count or 0),
        }
        for user, suite_count in rows
    ]


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
    for field in ("email", "full_name", "is_active", "is_verified", "is_super_admin"):
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
