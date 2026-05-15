from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite
from ..services.analytics import fetch_suite_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/{suite_id}")
async def get_analytics(
    suite_id: str,
    days: int = Query(default=28, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    connections = suite.connections or {}
    if not connections.get("facebook") and not connections.get("instagram"):
        return {"error": "no_connections", "facebook": {}, "instagram": {}, "days": days}

    return await fetch_suite_analytics(connections, days=days)
