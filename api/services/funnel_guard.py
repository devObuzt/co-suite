"""Cost cap for startbyconnec: funnel users generate each stage exactly once."""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User


def block_funnel_regeneration(user: User, *, already_generated: bool) -> None:
    if (user.approval_status or "frozen") == "funnel" and already_generated:
        raise HTTPException(status_code=403, detail="funnel_regeneration_blocked")


async def enforce_funnel_call_limit(db: AsyncSession, user: User, key: str, limit: int) -> None:
    """Bounded cost for funnel leads: counts calls in lead.progress['calls'][key]."""
    if (user.approval_status or "frozen") != "funnel":
        return
    from sqlalchemy import select
    from ..models.services_catalog import Lead
    lead = (await db.execute(select(Lead).where(Lead.user_id == user.id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=403, detail="account_frozen")
    calls = dict((lead.progress or {}).get("calls") or {})
    count = int(calls.get(key) or 0)
    if count >= limit:
        raise HTTPException(status_code=429, detail="funnel_call_limit")
    calls[key] = count + 1
    lead.progress = {**(lead.progress or {}), "calls": calls}
    await db.commit()
