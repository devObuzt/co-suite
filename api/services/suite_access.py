"""Owner-or-member access to a suite, with funnel users pinned to their lead suite."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.services_catalog import Lead
from ..models.suite import Suite, SuiteMember
from ..models.user import User
from .admin_audit import should_be_super_admin


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


def _is_super_admin(user: User) -> bool:
    """The admin flag is written lazily the first time an admin route is hit.

    Reading the configured admin e-mail as well means a fresh admin session can
    look at a suite without a write happening inside a GET.
    """
    return bool(user.is_active) and (bool(user.is_super_admin) or should_be_super_admin(user))


async def require_suite_read_access(db: AsyncSession, suite_id: str, user: User) -> Suite:
    """Owner, member — or a super admin, **for reading only**.

    Support cannot answer "where did this person get to, and what did they
    see?" without seeing the suite. The admin leads screen has always linked to
    the suite; the link returned 404 because every path went through
    `require_suite_access`, which knows only owners and members.

    This is deliberately a second function rather than a flag on the first one:
    every write keeps calling `require_suite_access`, where an admin is still a
    stranger. A widening that lives in one place cannot leak into a write by
    someone later passing the wrong argument.
    """
    if _is_super_admin(user):
        suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one_or_none()
        if not suite:
            raise HTTPException(status_code=404, detail="Suite not found")
        return suite
    return await require_suite_access(db, suite_id, user)
