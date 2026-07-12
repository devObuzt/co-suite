import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_market_research_cache_hit():
    from api.services import market_research as mr
    cached = {"audience_behavior": "x", "local_trends": [], "competitors_summary": "c"}
    with patch.object(mr, "get_cached", AsyncMock(return_value=cached)):
        out = await mr.get_market_research(db=None, country="israel", language="ar", brand={})
    assert out["audience_behavior"] == "x"


@pytest.mark.asyncio
async def test_market_research_fetches_and_shapes():
    from api.services import market_research as mr
    with patch.object(mr, "get_cached", AsyncMock(return_value=None)), \
         patch.object(mr, "upsert_cached", AsyncMock()) as up, \
         patch.object(mr, "research_competitors", AsyncMock(return_value={"CompA": "great agency"})):
        out = await mr.get_market_research(
            db=object(), country="israel", language="ar",
            brand={"competitors": ["CompA"], "name": "Me", "audience_notes": "young"},
        )
    assert out["audience_behavior"] == "young"
    assert "CompA" in out["competitors_summary"]
    up.assert_awaited_once()


@pytest.mark.asyncio
async def test_market_research_never_raises():
    from api.services import market_research as mr
    with patch.object(mr, "get_cached", AsyncMock(return_value=None)), \
         patch.object(mr, "research_competitors", AsyncMock(side_effect=RuntimeError())):
        out = await mr.get_market_research(db=object(), country="x", language="ar", brand={"competitors": ["a"]})
    assert set(out.keys()) == {"audience_behavior", "local_trends", "competitors_summary"}
