from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.admin import AuditLog, ProviderUsageEvent
from ..models.user import User

Period = Literal["today", "yesterday", "week", "month", "all", "custom"]


def admin_email() -> str:
    return settings.admin_email.strip().lower()


def should_be_super_admin(user: User) -> bool:
    email = admin_email()
    return bool(email and user.email.strip().lower() == email)


def serialize_user_public(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": bool(user.is_active),
        "is_verified": bool(user.is_verified),
        "is_super_admin": bool(user.is_super_admin),
        "approval_status": user.approval_status or "frozen",
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


async def ensure_admin_flag(user: User, db: AsyncSession) -> User:
    if should_be_super_admin(user) and not user.is_super_admin:
        user.is_super_admin = True
        await db.commit()
        await db.refresh(user)
    return user


async def require_super_admin(user: User, db: AsyncSession) -> User:
    user = await ensure_admin_flag(user, db)
    if not user.is_active or not user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def request_context(request: Request | None) -> tuple[str | None, str | None]:
    if not request:
        return None, None
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip_address = forwarded or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


async def record_audit_log(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    actor: User | None = None,
    request: Request | None = None,
    resource_id: str | None = None,
    suite_id: str | None = None,
    target_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    ip_address, user_agent = request_context(request)
    event = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        suite_id=suite_id,
        target_user_id=target_user_id,
        metadata_json=metadata or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(event)
    if commit:
        await db.commit()
        await db.refresh(event)
    return event


async def record_provider_usage(
    db: AsyncSession,
    *,
    provider: str,
    operation: str,
    model: str | None = None,
    endpoint: str | None = None,
    status: str = "success",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int | None = None,
    actual_cost_usd: float = 0.0,
    suite_id: str | None = None,
    user_id: str | None = None,
    generation_job_id: str | None = None,
    latency_ms: int | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> ProviderUsageEvent:
    event = ProviderUsageEvent(
        provider=provider,
        model=model,
        endpoint=endpoint,
        operation=operation,
        status=status,
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        total_tokens=max(0, int(total_tokens if total_tokens is not None else (input_tokens or 0) + (output_tokens or 0))),
        actual_cost_usd=max(0.0, float(actual_cost_usd or 0.0)),
        suite_id=suite_id,
        user_id=user_id,
        generation_job_id=generation_job_id,
        latency_ms=latency_ms,
        request_id=request_id,
        metadata_json=metadata or {},
    )
    db.add(event)
    if commit:
        await db.commit()
        await db.refresh(event)
    return event


def period_bounds(period: str = "month", start: datetime | None = None, end: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "all":
        return None, None
    if period == "today":
        return today, today + timedelta(days=1)
    if period == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, today
    if period == "week":
        return today - timedelta(days=6), today + timedelta(days=1)
    if period == "custom":
        return start, end
    return today - timedelta(days=29), today + timedelta(days=1)
