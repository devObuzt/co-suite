"""Linking a suite to a Manzuma business: explicit, once, and never ambiguous."""
import httpx
import pytest

from api.core.database import get_db
from api.core.security import get_current_user
from api.main import app
from api.models.suite import Suite
from api.models.user import User


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


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _suite(suite_id: str) -> Suite:
    return Suite(id=suite_id, owner_id="u1", name="Afkar", slug=f"afkar-{suite_id}")


@pytest.mark.asyncio
async def test_links_the_single_unlinked_suite():
    mine = _suite("s1")
    db = FakeDB(owned=[mine])

    async with _client(db) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 200
    assert res.json() == {"ok": True, "suite_id": "s1"}
    assert mine.organization_id == "o1"
    assert db.commits == 1
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_business_that_already_has_a_suite_is_refused():
    db = FakeDB(taken=_suite("other"), owned=[_suite("s1")])

    async with _client(db) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 409
    assert res.json()["detail"] == "organization_already_linked"
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_two_unlinked_suites_is_a_choice_we_do_not_make():
    db = FakeDB(owned=[_suite("s1"), _suite("s2")])

    async with _client(db) as client:
        res = await client.post("/api/v1/suites/link-organization", json={"organization_id": "o1"})

    assert res.status_code == 409
    assert res.json()["detail"] == "ambiguous_suite"
    assert db.commits == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_missing_business_id_is_refused_by_validation():
    db = FakeDB(owned=[_suite("s1")])

    async with _client(db) as client:
        res = await client.post("/api/v1/suites/link-organization", json={})

    # FastAPI answers its own validation errors with 422; the endpoint never
    # runs, which is the point — nothing is linked without a business id.
    assert res.status_code == 422
    app.dependency_overrides.clear()
