"""Erasing a person's co-Suite side, on the word of accounts and nobody else."""
import httpx
import pytest

from api.core.database import get_db
from api.core.service_auth import require_module
from api.main import app
from api.routers import internal as internal_router


class FakeDB:
    pass


def _client(module: str, eraser=None, monkeypatch=None):
    app.dependency_overrides[get_db] = lambda: FakeDB()
    app.dependency_overrides[require_module] = lambda: module
    if eraser is not None:
        monkeypatch.setattr(internal_router, "erase_manzuma_user", eraser)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_accounts_may_erase_a_person(monkeypatch):
    asked = {}

    async def eraser(_db, manzuma_user_id):
        asked["id"] = manzuma_user_id
        return {"erased": True, "suites": 3}

    async with _client("accounts", eraser, monkeypatch) as client:
        res = await client.post("/internal/v1/erase-user", json={"manzuma_user_id": "mu1"})

    assert res.status_code == 200
    assert res.json() == {"erased": True, "suites": 3}
    assert asked["id"] == "mu1"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_reading_module_cannot_erase(monkeypatch):
    """OneShare's key reads strategies. It must not be able to delete one."""

    async def eraser(*_args):  # pragma: no cover - must never run
        raise AssertionError("nothing may be erased for this caller")

    async with _client("oneshare", eraser, monkeypatch) as client:
        res = await client.post("/internal/v1/erase-user", json={"manzuma_user_id": "mu1"})

    assert res.status_code == 403
    assert res.json()["detail"] == "not_allowed"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_person_who_never_opened_cosuite_is_already_erased(monkeypatch):
    async def eraser(_db, _id):
        return {"erased": False, "suites": 0}

    async with _client("accounts", eraser, monkeypatch) as client:
        res = await client.post("/internal/v1/erase-user", json={"manzuma_user_id": "ghost"})

    # Not an error: the promise is "nothing of mine is left", and it holds.
    assert res.status_code == 200
    assert res.json()["erased"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_missing_user_id_is_refused(monkeypatch):
    async def eraser(*_args):  # pragma: no cover - must never run
        raise AssertionError("nothing may be erased without an id")

    async with _client("accounts", eraser, monkeypatch) as client:
        res = await client.post("/internal/v1/erase-user", json={})

    assert res.status_code == 422
    app.dependency_overrides.clear()
