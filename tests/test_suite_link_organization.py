"""Linking a suite to a Manzuma business: explicit, once, and never ambiguous."""
import httpx
import pytest

from api.core.database import get_db
from api.core.security import get_current_user
from api.main import app
from api.models.suite import Suite
from api.models.user import User
from api.routers import suites as suites_router
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSession


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return _Scalars(self._rows)


class FakeDB:
    """Two questions get asked here: is this business taken, and what do I own."""

    def __init__(self, taken=None, owned=()):
        self.taken = taken
        self.owned = list(owned)
        self.commits = 0

    async def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        if "suites.organization_id IS NULL" in sql:
            return _Result(self.owned)
        return _Result([self.taken] if self.taken else [])

    async def commit(self):
        self.commits += 1


CALLER = User(id="u1", email="w@example.com", hashed_password="", full_name="Wisam")


def _session(*orgs: ManzumaOrg) -> ManzumaSession:
    return ManzumaSession(
        user_id="mu1", email="w@example.com", phone=None, name="Wisam", organizations=orgs
    )


def _owner_of(org_id: str, role: str = "owner") -> ManzumaOrg:
    return ManzumaOrg(id=org_id, name="Afkar", role=role, subscriptions=())


def _client(db, monkeypatch, session=None):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER

    async def _session_or_none(_request):
        return session

    monkeypatch.setattr(suites_router, "manzuma_session_or_none", _session_or_none)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _suite(suite_id: str) -> Suite:
    return Suite(id=suite_id, owner_id="u1", name="Afkar", slug=f"afkar-{suite_id}")


@pytest.mark.asyncio
async def test_links_the_single_unlinked_suite(monkeypatch):
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 200
    assert res.json() == {"ok": True, "suite_id": "s1"}
    assert mine.organization_id == "o1"
    assert db.commits == 1
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_business_that_already_has_a_suite_is_refused(monkeypatch):
    db = FakeDB(taken=_suite("other"), owned=[_suite("s1")])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 409
    assert res.json()["detail"] == "organization_already_linked"
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_two_unlinked_suites_is_a_choice_we_do_not_make(monkeypatch):
    db = FakeDB(owned=[_suite("s1"), _suite("s2")])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 409
    assert res.json()["detail"] == "ambiguous_suite"
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_missing_business_id_is_refused_by_validation(monkeypatch):
    db = FakeDB(owned=[_suite("s1")])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={})

    # FastAPI answers its own validation errors with 422; the endpoint never
    # runs, which is the point — nothing is linked without a business id.
    assert res.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_business_that_is_not_yours_cannot_be_linked(monkeypatch):
    """The id in the body proves nothing — the caller's session decides."""
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, _session(_owner_of("my-own-org"))) as client:
        res = await client.post(
            "/api/v1/suites/link-organization", json={"organization_id": "someone-elses-org"}
        )

    assert res.status_code == 403
    assert res.json()["detail"] == "not_organization_admin"
    assert mine.organization_id is None
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_plain_member_cannot_bind_the_business(monkeypatch):
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, _session(_owner_of("o1", role="member"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 403
    assert mine.organization_id is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_an_admin_may_bind_the_business(monkeypatch):
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, _session(_owner_of("o1", role="admin"))) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 200
    assert mine.organization_id == "o1"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_without_a_manzuma_session_nothing_is_linked(monkeypatch):
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, None) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 403
    assert mine.organization_id is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_an_owner_with_several_suites_picks_one(monkeypatch):
    mine, other = _suite("s1"), _suite("s2")
    db = FakeDB(owned=[mine, other])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post(
            "/api/v1/suites/link-organization",
            json={"organization_id": "o1", "suite_id": "s2"},
        )

    assert res.status_code == 200
    assert res.json()["suite_id"] == "s2"
    assert other.organization_id == "o1"
    assert mine.organization_id is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_suite_that_is_not_yours_cannot_be_linked(monkeypatch):
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db, monkeypatch, _session(_owner_of("o1"))) as client:
        res = await client.post(
            "/api/v1/suites/link-organization",
            json={"organization_id": "o1", "suite_id": "somebody-elses"},
        )

    assert res.status_code == 404
    assert res.json()["detail"] == "suite_not_available"
    assert mine.organization_id is None
    assert db.commits == 0
    app.dependency_overrides.clear()
