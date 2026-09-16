"""The internal endpoint as a product sees it: key, contract, and 'no suite yet'."""
import httpx
import pytest

from api.core.config import settings
from api.core.database import get_db
from api.main import app
from api.models.suite import Suite


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeDB:
    def __init__(self, suite):
        self.suite = suite

    async def execute(self, *_args, **_kwargs):
        return _Result(self.suite)


def _client(suite):
    app.dependency_overrides[get_db] = lambda: FakeDB(suite)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _linked_suite() -> Suite:
    suite = Suite(id="s1", owner_id="u1", name="Afkar", slug="afkar")
    suite.organization_id = "o1"
    suite.brand = {"description": "healthy food", "tagline": "eat well", "services": []}
    suite.strategy = {"marketing_message": "eat well", "language": "ar", "marketing_plan": {}}
    suite.connections = {"meta_user_token": "EAA-secret"}
    return suite


@pytest.mark.asyncio
async def test_returns_the_contract_for_a_linked_business(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")
    async with _client(_linked_suite()) as client:
        res = await client.get(
            "/internal/v1/suite?organization_id=o1", headers={"authorization": "Bearer abc"}
        )

    assert res.status_code == 200
    body = res.json()
    assert body["suite"]["name"] == "Afkar"
    assert body["marketing_message"] == "eat well"
    assert "EAA-secret" not in res.text  # no token, ever
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_business_without_a_suite_reads_as_404(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")
    async with _client(None) as client:
        res = await client.get(
            "/internal/v1/suite?organization_id=o9", headers={"authorization": "Bearer abc"}
        )

    assert res.status_code == 404
    assert res.json()["detail"] == "no_suite"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_without_a_module_key_there_is_no_access(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")
    async with _client(_linked_suite()) as client:
        anonymous = await client.get("/internal/v1/suite?organization_id=o1")
        wrong = await client.get(
            "/internal/v1/suite?organization_id=o1", headers={"authorization": "Bearer nope"}
        )

    assert anonymous.status_code == 401
    assert wrong.status_code == 401
    app.dependency_overrides.clear()
