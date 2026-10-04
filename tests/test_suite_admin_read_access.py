"""An admin may READ any suite — and must never gain a write by this door.

Support could not answer "where did this person get to, and what did they
see?": the admin leads screen linked to the suite, and the link answered 404
because every path ran through `require_suite_access`, which knows only owners
and members. Reading is now allowed for a super admin. Writing is not, and the
last test here is what keeps that true as the file grows.
"""
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.suite import Suite
from api.models.user import User
from api.services.suite_access import require_suite_read_access

API = Path(__file__).resolve().parents[1] / "api"


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeDB:
    """Answers each `execute` with the next queued row: suite, then member."""

    def __init__(self, *rows):
        self._rows = list(rows)

    async def execute(self, *_args, **_kwargs):
        return _Result(self._rows.pop(0) if self._rows else None)


SUITE = Suite(id="s1", owner_id="owner", name="lux gamer", slug="lux-gamer")


def _user(uid, *, admin=False, active=True, email="x@example.com") -> User:
    user = User(id=uid, email=email, hashed_password="", full_name=uid)
    user.is_super_admin = admin
    user.is_active = active
    user.approval_status = "approved"
    return user


@pytest.mark.asyncio
async def test_admin_reads_a_suite_they_do_not_own():
    suite = await require_suite_read_access(FakeDB(SUITE), "s1", _user("admin", admin=True))
    assert suite is SUITE


@pytest.mark.asyncio
async def test_owner_still_reads_their_own_suite():
    suite = await require_suite_read_access(FakeDB(SUITE), "s1", _user("owner"))
    assert suite is SUITE


@pytest.mark.asyncio
async def test_a_stranger_still_gets_nothing():
    # suite found, then no membership row.
    with pytest.raises(HTTPException) as err:
        await require_suite_read_access(FakeDB(SUITE, None), "s1", _user("someone-else"))
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_a_deactivated_admin_is_just_a_stranger():
    with pytest.raises(HTTPException) as err:
        await require_suite_read_access(
            FakeDB(SUITE, None), "s1", _user("admin", admin=True, active=False)
        )
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_a_missing_suite_is_still_missing_for_an_admin():
    with pytest.raises(HTTPException) as err:
        await require_suite_read_access(FakeDB(None), "nope", _user("admin", admin=True))
    assert err.value.status_code == 404


def _route_blocks(source: str):
    """Yield (http_method, body) for every router handler in a module."""
    parts = re.split(r"\n@router\.(get|post|patch|put|delete)\(", "\n" + source)
    for method, body in zip(parts[1::2], parts[2::2]):
        yield method, body


@pytest.mark.parametrize(
    "module, helper",
    [
        ("routers/marketing_plans.py", "get_viewable_suite("),
        ("routers/suites.py", "require_suite_read_access("),
    ],
)
def test_the_widened_check_is_only_ever_used_by_a_GET(module, helper):
    """A write that adopted this helper would hand admins someone's suite to edit."""
    offenders = [
        body.splitlines()[0]
        for method, body in _route_blocks((API / module).read_text(encoding="utf-8"))
        if helper in body and method != "get"
    ]
    assert offenders == [], (
        f"{module}: these non-GET handlers call {helper} — reading access must not back a write:\n"
        + "\n".join(f"  {line}" for line in offenders)
    )
