"""Deleting a suite, and deleting everything one person has.

Erasure lives here rather than in a route because two callers need the exact
same thing: the owner pressing delete in co-Suite, and Manzuma accounts closing
somebody's account across every product. A second implementation of this would
be a second chance to forget a table.

What survives on purpose: audit and provider-usage rows, with their suite
reference nulled. They record what our own system did — spend, provider calls —
and none of them carry the customer's content.
"""
import logging
from typing import Any, Optional

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.admin import AuditLog, ProviderUsageEvent
from ..models.billing import Subscription, UsageEvent
from ..models.content import ContentPost
from ..models.generation_job import GenerationJob
from ..models.media_asset import MediaAsset
from ..models.product_bulk import (
    ProductBulkAsset,
    ProductBulkBatch,
    ProductBulkItem,
    ProductTemplateDirection,
)
from ..models.services_catalog import Lead
from ..models.suite import Suite, SuiteMember
from ..models.user import User

log = logging.getLogger(__name__)


async def erase_suite(db: AsyncSession, suite: Suite) -> None:
    """Delete a suite and everything that belongs to it. Does not commit."""
    suite_id = suite.id
    batch_ids = select(ProductBulkBatch.id).where(ProductBulkBatch.suite_id == suite_id)
    await db.execute(sa_delete(ProductBulkAsset).where(ProductBulkAsset.batch_id.in_(batch_ids)))
    await db.execute(sa_delete(ProductBulkItem).where(ProductBulkItem.batch_id.in_(batch_ids)))
    await db.execute(
        sa_delete(ProductTemplateDirection).where(ProductTemplateDirection.batch_id.in_(batch_ids))
    )
    await db.execute(sa_delete(ProductBulkBatch).where(ProductBulkBatch.suite_id == suite_id))
    await db.execute(sa_delete(ContentPost).where(ContentPost.suite_id == suite_id))
    await db.execute(sa_delete(GenerationJob).where(GenerationJob.suite_id == suite_id))
    await db.execute(sa_delete(MediaAsset).where(MediaAsset.suite_id == suite_id))
    await db.execute(sa_delete(UsageEvent).where(UsageEvent.suite_id == suite_id))
    await db.execute(sa_delete(Subscription).where(Subscription.suite_id == suite_id))
    await db.execute(sa_delete(SuiteMember).where(SuiteMember.suite_id == suite_id))
    await db.execute(sa_update(AuditLog).where(AuditLog.suite_id == suite_id).values(suite_id=None))
    await db.execute(
        sa_update(ProviderUsageEvent)
        .where(ProviderUsageEvent.suite_id == suite_id)
        .values(suite_id=None)
    )
    await db.delete(suite)


async def erase_manzuma_user(db: AsyncSession, manzuma_user_id: str) -> dict[str, Any]:
    """Erase the co-Suite side of one Manzuma person, suites and all.

    Accounts calls this when somebody deletes their Manzuma account. A person
    who never opened co-Suite has nothing here, and that is a success, not a
    404 — the promise being kept is "my data is gone", which is already true.
    """
    user: Optional[User] = (
        await db.execute(select(User).where(User.manzuma_user_id == manzuma_user_id))
    ).scalar_one_or_none()
    if not user:
        return {"erased": False, "suites": 0}

    suites = (await db.execute(select(Suite).where(Suite.owner_id == user.id))).scalars().all()
    for suite in suites:
        await erase_suite(db, suite)

    # Memberships of suites somebody else owns: the suite stays, this person
    # leaves it.
    await db.execute(sa_delete(SuiteMember).where(SuiteMember.user_id == user.id))
    await db.delete(user)
    await db.commit()

    log.info("[erase] manzuma user %s — %s suites", manzuma_user_id, len(suites))
    return {"erased": True, "suites": len(suites)}

async def reset_funnel_lead(db: AsyncSession, user: User) -> bool:
    """Put a funnel visitor back at the start after their suite is erased.

    Erasing the suite is not enough on its own. The funnel keeps two things on
    the LEAD, not the suite: `suite_id`, which sends the visitor back to a
    suite that no longer exists, and `progress.calls`, the per-stage cost caps
    that would otherwise still be spent. Clearing both is what makes "delete"
    actually mean "start over".
    """
    lead = (await db.execute(select(Lead).where(Lead.user_id == user.id))).scalar_one_or_none()
    if not lead:
        return False
    progress = dict(lead.progress or {})
    # All of these pin the visitor in place, not just the cost caps:
    # `request_submitted` sends them straight to /done forever and `step`
    # holds them at the last screen they reached. Clearing only `calls` reset
    # the budgets and left the person exactly where they were — which is what
    # "delete and start over" looked like doing nothing on 2026-09-24.
    for key in ("calls", "step", "suite_created", "request_submitted"):
        progress.pop(key, None)
    lead.progress = progress
    lead.suite_id = None
    return True
