import pytest

from api.services import meta_interests as mi


def test_demand_level_thresholds():
    assert mi._demand_level(0, 0, 0) == "UNKNOWN"
    assert mi._demand_level(0, 8, 0) == "LOW"
    assert mi._demand_level(1, 8, 100_000) == "LOW"
    assert mi._demand_level(3, 8, 1_000_000) == "MEDIUM"
    assert mi._demand_level(2, 8, 8_000_000) == "MEDIUM"
    assert mi._demand_level(5, 8, 1_000_000) == "HIGH"
    assert mi._demand_level(6, 10, 90_000_000) == "HIGH"


@pytest.mark.asyncio
async def test_match_meta_interests_without_credentials(monkeypatch):
    monkeypatch.setattr(mi.settings, "meta_app_id", "", raising=False)
    monkeypatch.setattr(mi.settings, "meta_app_secret", "", raising=False)

    snapshot = await mi.match_meta_interests(["healthy nutrition"])

    assert snapshot["level"] == "UNKNOWN"
    assert snapshot["matched"] == 0
    assert "internal_warning" in snapshot


@pytest.mark.asyncio
async def test_match_meta_interests_aggregates(monkeypatch):
    monkeypatch.setattr(mi.settings, "meta_app_id", "app", raising=False)
    monkeypatch.setattr(mi.settings, "meta_app_secret", "secret", raising=False)

    async def fake_search(client, token, term):
        if term == "missing":
            return None
        return {"query": term, "name": term.title(), "audience_size": 60_000_000}

    monkeypatch.setattr(mi, "_search_interest", fake_search)

    snapshot = await mi.match_meta_interests(["nutrition", "fitness", "detox", "missing"])

    assert snapshot["checked"] == 4
    assert snapshot["matched"] == 3
    assert snapshot["audience_size"] == 180_000_000
    assert snapshot["level"] == "HIGH"
    assert snapshot["matches"][0]["name"] == "Nutrition"
