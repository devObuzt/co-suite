"""Owner-or-member access to a suite, with funnel users pinned to their lead suite."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.services_catalog import Lead
from ..models.suite import Suite, SuiteMember
from ..models.user import User


async def require_suite_access(db: AsyncSession, suite_id: str, user: User) -> Suite:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if suite.owner_id != user.id:
        member = (
            await db.execute(
                select(SuiteMember).where(
                    SuiteMember.suite_id == suite_id, SuiteMember.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Suite not found")
    if (user.approval_status or "frozen") == "funnel":
        lead = (
            await db.execute(select(Lead).where(Lead.user_id == user.id))
        ).scalar_one_or_none()
        if not lead or lead.suite_id != suite_id:
            raise HTTPException(status_code=403, detail="account_frozen")
    return suite
