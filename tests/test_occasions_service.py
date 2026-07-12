import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_get_occasions_uses_cache():
    from api.services import occasions_service as svc
    cached = [{"title": "عيد الأضحى", "type": "religious", "date_or_window": "2026-08",
               "confidence": "high", "verified_by": "web"}]
    with patch.object(svc, "get_cached", AsyncMock(return_value=cached)):
        out = await svc.get_occasions(db=None, country="israel", language="ar", period="2026-08")
    assert out and out[0]["title"] == "عيد الأضحى"


@pytest.mark.asyncio
async def test_get_occasions_fetches_on_miss_and_verifies():
    from api.services import occasions_service as svc
    llm_json = ('{"occasions":[{"title":"المونديال 2026","type":"sports",'
                '"date_or_window":"2026-06..2026-07","confidence":"low"}]}')
    with patch.object(svc, "get_cached", AsyncMock(return_value=None)), \
         patch.object(svc, "upsert_cached", AsyncMock()) as up, \
         patch.object(svc, "call_text_ai", AsyncMock(return_value=llm_json)), \
         patch.object(svc, "search_web", AsyncMock(return_value=[
             {"title": "World Cup 2026", "url": "x", "snippet": "June 11 – July 19, 2026", "platform": "web"}])):
        out = await svc.get_occasions(db=object(), country="israel", language="ar", period="2026-08")
    assert any("المونديال" in o["title"] for o in out)
    occ = out[0]
    assert occ["verified_by"] == "web"      # web verification ran
    assert occ["confidence"] == "medium"    # low upgraded to medium after web hit
    up.assert_awaited_once()                # cached the fetched result


@pytest.mark.asyncio
async def test_get_occasions_coerces_unknown_type():
    from api.services import occasions_service as svc
    llm_json = '{"occasions":[{"title":"X","type":"weird"}]}'
    with patch.object(svc, "get_cached", AsyncMock(return_value=None)), \
         patch.object(svc, "upsert_cached", AsyncMock()), \
         patch.object(svc, "call_text_ai", AsyncMock(return_value=llm_json)), \
         patch.object(svc, "search_web", AsyncMock(return_value=[])):
        out = await svc.get_occasions(db=object(), country="x", language="ar", period="2026-08")
    assert out[0]["type"] == "seasonal"


@pytest.mark.asyncio
async def test_get_occasions_never_raises_on_failure():
    from api.services import occasions_service as svc
    with patch.object(svc, "get_cached", AsyncMock(return_value=None)), \
         patch.object(svc, "call_text_ai", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await svc.get_occasions(db=None, country="x", language="ar", period="2026-08")
    assert out == []
