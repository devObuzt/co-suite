import httpx
import pytest

from api.services import manzuma_accounts as ma


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_verify_session_maps_the_accounts_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/session"
        assert request.headers["cookie"] == "manzuma.session=abc"
        return httpx.Response(200, json={
            "authenticated": True,
            "user": {"id": "u1", "email": "W@Example.com", "phone": "+972501234567", "name": "Wisam"},
            "organizations": [
                {
                    "id": "org1", "name": "Afkar", "slug": "afkar", "role": "owner",
                    "subscriptions": [
                        {"organizationId": "org1", "module": "cosuite", "plan": "pro", "status": "active"}
                    ],
                }
            ],
        })

    session = await ma.verify_session(cookie="manzuma.session=abc", bearer=None, transport=_transport(handler))

    assert session.user_id == "u1"
    assert session.email == "W@Example.com"
    assert session.organizations[0].id == "org1"
    assert session.organizations[0].role == "owner"
    assert session.organizations[0].subscriptions[0].module == "cosuite"
    assert session.organizations[0].subscriptions[0].status == "active"


@pytest.mark.asyncio
async def test_verify_session_returns_none_when_not_authenticated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"authenticated": False})

    assert await ma.verify_session(cookie="x=1", bearer=None, transport=_transport(handler)) is None


@pytest.mark.asyncio
async def test_verify_session_returns_none_when_accounts_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    assert await ma.verify_session(cookie="x=2", bearer=None, transport=_transport(handler)) is None


@pytest.mark.asyncio
async def test_subscribes_to_ignores_a_dead_subscription():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "authenticated": True,
            "user": {"id": "u2"},
            "organizations": [
                {"id": "org2", "name": "Old", "role": "owner", "subscriptions": [
                    {"module": "cosuite", "plan": "pro", "status": "cancelled"}
                ]}
            ],
        })

    session = await ma.verify_session(cookie="x=3", bearer=None, transport=_transport(handler))

    assert session.organizations[0].subscribes_to("cosuite") is False


def test_cache_key_never_contains_the_credential():
    key = ma._cache_key("manzuma.session=supersecret", None)
    assert "supersecret" not in key
    assert len(key) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_create_organization_asks_accounts_with_the_service_key(monkeypatch):
    monkeypatch.setattr(ma.settings, "manzuma_service_key", "k", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/organizations"
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(201, json={"organization": {"id": "org1", "name": "Kinder"}})

    org = await ma.create_organization("mu1", "Kinder", transport=_transport(handler))
    assert org == {"id": "org1", "name": "Kinder"}


@pytest.mark.asyncio
async def test_create_organization_returns_none_when_accounts_refuses(monkeypatch):
    monkeypatch.setattr(ma.settings, "manzuma_service_key", "k", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "unauthorized"})

    assert await ma.create_organization("mu1", "Kinder", transport=_transport(handler)) is None


@pytest.mark.asyncio
async def test_create_organization_without_a_service_key_does_nothing(monkeypatch):
    monkeypatch.setattr(ma.settings, "manzuma_service_key", "", raising=False)

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("accounts must not be called without a key")

    assert await ma.create_organization("mu1", "Kinder", transport=_transport(handler)) is None
