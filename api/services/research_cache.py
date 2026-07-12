"""Read/write helpers for the shared ResearchCache table.

Keyed by (kind, country, language, period). ``period`` is NULL for general
market research and "YYYY-MM" for month-scoped occasions. Callers pass a real
country/language; normalization keeps the cache key stable across casing/spacing.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.research_cache import ResearchCache


def normalize_country(value) -> str:
    return (str(value or "")).strip().lower() or "global"


def normalize_language(value) -> str:
    return (str(value or "")).strip().lower().split("-")[0] or "en"


def _match(kind, country, language, period):
    conditions = [
        ResearchCache.kind == kind,
        ResearchCache.country == normalize_country(country),
        ResearchCache.language == normalize_language(language),
    ]
    conditions.append(ResearchCache.period.is_(None) if period is None else ResearchCache.period == period)
    return conditions


async def get_cached(db: AsyncSession, *, kind, country, language, period=None):
    """Return the cached ``data`` for the key, or None on miss/expiry."""
    row = (await db.execute(select(ResearchCache).where(*_match(kind, country, language, period)))).scalar_one_or_none()
    if not row:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        return None
    return row.data


async def upsert_cached(db: AsyncSession, *, kind, country, language, period, data, source="hybrid", ttl_days=None):
    """Insert or update the row for the key (idempotent on the unique key)."""
    country = normalize_country(country)
    language = normalize_language(language)
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days) if ttl_days else None
    row = (await db.execute(select(ResearchCache).where(*_match(kind, country, language, period)))).scalar_one_or_none()
    if row:
        row.data = data
        row.source = source
        row.expires_at = expires_at
    else:
        db.add(ResearchCache(
            kind=kind, country=country, language=language, period=period,
            data=data, source=source, expires_at=expires_at,
        ))
    await db.commit()
