from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.media_asset import MediaAsset
from ..models.user import User
from ..services.media_library import build_media_tree, serialize_media_asset
from .video_montage import get_owned_suite

router = APIRouter(prefix="/suites/{suite_id}/media", tags=["media"])


@router.get("/tree")
async def get_media_tree(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    year = func.extract("year", MediaAsset.created_at)
    month = func.extract("month", MediaAsset.created_at)
    result = await db.execute(
        select(
            MediaAsset.library,
            year.label("year"),
            month.label("month"),
            func.count(MediaAsset.id).label("count"),
        )
        .where(MediaAsset.suite_id == suite_id)
        .group_by(MediaAsset.library, year, month)
    )
    return {"libraries": build_media_tree(result.all())}


@router.get("")
async def list_media_assets(
    suite_id: str,
    library: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    stmt = select(MediaAsset).where(MediaAsset.suite_id == suite_id)
    if library:
        stmt = stmt.where(MediaAsset.library == library)
    if year is not None:
        stmt = stmt.where(func.extract("year", MediaAsset.created_at) == year)
    if month is not None:
        stmt = stmt.where(func.extract("month", MediaAsset.created_at) == month)
    stmt = stmt.order_by(MediaAsset.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    return [serialize_media_asset(asset) for asset in result.scalars().all()]
