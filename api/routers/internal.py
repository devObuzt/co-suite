"""The internal API other Manzuma products call. Service keys only, read only.

A product asks by Manzuma organization id — the business — because that is the
identifier every product already has. `404` means the business has no suite
yet, which the caller turns into an invitation, not an error.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.service_auth import require_module
from ..models.suite import Suite
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
