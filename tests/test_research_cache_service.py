import pytest
from unittest.mock import AsyncMock

from api.services.research_cache import normalize_country, normalize_language, get_cached


def test_normalize_country():
    assert normalize_country("  Israel ") == "israel"
    assert normalize_country("") == "global"
    assert normalize_country(None) == "global"


def test_normalize_language():
    assert normalize_language("AR") == "ar"
    assert normalize_language("ar-EG") == "ar"
    assert normalize_language(None) == "en"
    assert normalize_language("") == "en"


@pytest.mark.asyncio
async def test_get_cached_returns_none_on_miss():
    db = AsyncMock()
    result = AsyncMock()
    result.scalar_one_or_none = lambda: None
    db.execute = AsyncMock(return_value=result)
    assert await get_cached(db, kind="occasions", country="x", language="ar", period="2026-08") is None
