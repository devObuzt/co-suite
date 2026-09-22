"""Creating the business a suite belongs to, from inside co-Suite.

The guards here are the same ones linking has — the suite must be yours, the
business must be new, and the owner must be a Manzuma person — so they are
tested the same way, without a database in the way.
"""
import httpx
import pytest

from api.core.database import get_db
from api.core.security import get_current_user
from api.main import app
from api.models.suite import Suite
from api.models.user import User
from api.routers import suites as suites_router
from api.services.manzuma_accounts import ManzumaSession


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    def __init__(self, suite=None):
        self.suite = suite
        self.commits = 0

    async def execute(self, *_args, **_kwargs):
        return _Result([self.suite] if self.suite else [])

    async def commit(self):
        self.commits += 1


CALLER = User(id="u1", email="w@example.com", hashed_password="", full_name="Wisam")
SESSION = ManzumaSession(
    user_id="mu1", email="w@example.com", phone=None, name="Wisam", organizations=()
)


def _suite(suite_id="s1", name="Kinder Beands", organization_id=None) -> Suite:
    suite = Suite(id=suite_id, owner_id="u1", name=name, slug=f"{suite_id}-slug")
    suite.organization_id = organization_id
    return suite


def _client(db, monkeypatch, session=SESSION, creator=None):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER

    async def _session_or_none(_request):
        return session

    monkeypatch.setattr(suites_router, "manzuma_session_or_none", _session_or_none)
    if creator is not None:
        monkeypatch.setattr(suites_router, "create_organization", creator)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_creates_a_business_named_after_the_suite_and_links_it(monkeypatch):
    suite = _suite()
    db = FakeDB(suite)
    asked = {}

    async def creator(user_id, name):
        asked["user_id"], asked["name"] = user_id, name
        return {"id": "org-new", "name": name, "slug": "kinder-beands-ab12c"}

    async with _client(db, monkeypatch, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={})

    assert res.status_code == 200
    assert res.json()["organization"]["id"] == "org-new"
    assert suite.organization_id == "org-new"
    assert db.commits == 1
    # The owner comes from the verified session, never from the request body.
    assert asked == {"user_id": "mu1", "name": "Kinder Beands"}
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_chosen_name_wins_over_the_suite_name(monkeypatch):
    db = FakeDB(_suite())

    async def creator(_user_id, name):
        return {"id": "org-new", "name": name}

    async with _client(db, monkeypatch, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={"name": "Kinder Brands"})

    assert res.json()["organization"]["name"] == "Kinder Brands"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_suite_that_already_has_a_business_is_refused(monkeypatch):
    suite = _suite(organization_id="org-old")
    db = FakeDB(suite)

    async def creator(*_args):  # pragma: no cover - must never run
        raise AssertionError("accounts must not be asked")

    async with _client(db, monkeypatch, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={})

    assert res.status_code == 409
    assert res.json()["detail"] == "suite_already_linked"
    assert suite.organization_id == "org-old"
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_somebody_elses_suite_is_not_found(monkeypatch):
    db = FakeDB(_suite())
    db.suite.owner_id = "someone-else"

    async def creator(*_args):  # pragma: no cover - must never run
        raise AssertionError("accounts must not be asked")

    async with _client(db, monkeypatch, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={})

    assert res.status_code == 404
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_legacy_session_cannot_own_a_business(monkeypatch):
    suite = _suite()
    db = FakeDB(suite)

    async def creator(*_args):  # pragma: no cover - must never run
        raise AssertionError("accounts must not be asked")

    async with _client(db, monkeypatch, session=None, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={})

    assert res.status_code == 403
    assert res.json()["detail"] == "no_manzuma_session"
    assert suite.organization_id is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_nothing_is_linked_when_accounts_refuses(monkeypatch):
    suite = _suite()
    db = FakeDB(suite)

    async def creator(*_args):
        return None

    async with _client(db, monkeypatch, creator=creator) as client:
        res = await client.post("/api/v1/suites/s1/create-business", json={})

    assert res.status_code == 502
    assert suite.organization_id is None
    assert db.commits == 0
    app.dependency_overrides.clear()
