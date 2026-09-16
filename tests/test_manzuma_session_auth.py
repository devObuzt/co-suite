import pytest
from fastapi import HTTPException

from api.core import security
from api.core.config import settings
from api.models.user import User
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSession, ManzumaSub


class _Request:
    def __init__(self, cookie=None, path="/api/v1/suites/"):
        self.headers = {"cookie": cookie} if cookie else {}
        self.method = "GET"
        self.url = type("U", (), {"path": path})()


SESSION = ManzumaSession(
    user_id="u1", email="w@example.com", phone=None, name="Wisam",
    organizations=(
        ManzumaOrg(
            id="o1", name="Afkar", role="owner",
            subscriptions=(ManzumaSub(module="cosuite", plan="pro", status="active"),),
        ),
    ),
)


@pytest.mark.asyncio
async def test_session_branch_is_off_while_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", False)
    called = False

    async def _verify(cookie=None, bearer=None):
        nonlocal called
        called = True
        return SESSION

    monkeypatch.setattr(security, "verify_session", _verify)

    assert await security.manzuma_user_or_none(_Request("manzuma.session=abc"), db=None) is None
    assert called is False


@pytest.mark.asyncio
async def test_session_branch_resolves_a_user_when_the_flag_is_on(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)
    user = User(id="local1", email="w@example.com", hashed_password="", full_name="Wisam")

    async def _verify(cookie=None, bearer=None):
        assert cookie == "manzuma.session=abc"
        return SESSION

    async def _resolve(_db, session, org):
        assert session.user_id == "u1"
        assert org.id == "o1"
        return user

    monkeypatch.setattr(security, "verify_session", _verify)
    monkeypatch.setattr(security, "resolve_user", _resolve)

    assert await security.manzuma_user_or_none(_Request("manzuma.session=abc"), db=None) is user


@pytest.mark.asyncio
async def test_a_cookie_that_is_not_ours_is_not_sent_to_accounts(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)
    called = False

    async def _verify(cookie=None, bearer=None):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(security, "verify_session", _verify)

    assert await security.manzuma_user_or_none(_Request("ga=123"), db=None) is None
    assert called is False


@pytest.mark.asyncio
async def test_a_request_without_a_session_falls_through(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)

    async def _verify(cookie=None, bearer=None):
        return None

    monkeypatch.setattr(security, "verify_session", _verify)

    assert await security.manzuma_user_or_none(_Request(), db=None) is None


def test_a_frozen_user_is_still_blocked_on_a_product_path():
    frozen = User(id="local2", email="x@example.com", hashed_password="", full_name="X")
    frozen.approval_status = "frozen"

    with pytest.raises(HTTPException) as err:
        security.enforce_status(frozen, "GET", "/api/v1/suites/")

    assert err.value.status_code == 403
    assert err.value.detail == "account_frozen"


def test_an_approved_user_passes_the_gate():
    ok = User(id="local3", email="y@example.com", hashed_password="", full_name="Y")
    ok.approval_status = "approved"

    assert security.enforce_status(ok, "GET", "/api/v1/suites/") is ok
