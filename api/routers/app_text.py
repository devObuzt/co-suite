from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from ..core.database import get_db
from ..models.admin import AppTextOverride

router = APIRouter(prefix="/app-text", tags=["app-text"])


def normalize_language_code(value: str) -> str:
    return re.split(r"[-_]", value.strip().lower(), maxsplit=1)[0][:12]


@router.get("/{language}")
async def public_app_text(language: str, db: AsyncSession = Depends(get_db)):
    lang = normalize_language_code(language)
    rows = (
        await db.execute(
            select(AppTextOverride)
            .where(AppTextOverride.language == lang)
            .order_by(AppTextOverride.text_key.asc())
        )
    ).scalars().all()
    return {
        "language": lang,
        "overrides": {row.text_key: row.value for row in rows},
        "updated_at": max((row.updated_at for row in rows), default=None),
    }
