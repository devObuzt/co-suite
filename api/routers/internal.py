"""The internal API other Manzuma products call. Service keys only, read only.

A product asks by Manzuma organization id — the business — because that is the
identifier every product already has. `404` means the business has no suite
yet, which the caller turns into an invitation, not an error.
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.service_auth import require_module
from ..models.suite import Suite
from ..services.suite_erase import erase_manzuma_user
from ..services.suite_summary import suite_summary

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.get("/suite")
async def read_suite(
    organization_id: str = Query(..., min_length=1),
    module: str = Depends(require_module),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.organization_id == organization_id))
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_suite")

    log.info("[internal] %s read suite %s for org %s", module, suite.id, organization_id)
    return suite_summary(suite)


# Accounts owns identity, so accounts is the only product allowed to end one.
ERASING_MODULE = "accounts"


@router.post("/erase-user")
async def erase_user(
    manzuma_user_id: str = Body(..., embed=True, min_length=1),
    module: str = Depends(require_module),
    db: AsyncSession = Depends(get_db),
):
    """Delete this person's co-Suite side. Called when they close their account.

    Read access is shared with every product; this is not. A key that may read
    a strategy must not be able to delete one, so the module is checked by name
    on top of the key being valid.
    """
    if module != ERASING_MODULE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_allowed")

    result = await erase_manzuma_user(db, manzuma_user_id)
    log.info("[internal] %s erased user %s (%s suites)", module, manzuma_user_id, result["suites"])
    return result
