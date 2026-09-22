"""Reading Meta tokens from the vault instead of the suite's JSON column.

The rule the tests hold: a linked suite uses the vault, an unlinked one keeps
working on what it has, and nothing is ever written back.
"""
import pytest

from api.models.suite import Suite
from api.services import meta_tokens


def _suite(organization_id=None) -> Suite:
    suite = Suite(id="s1", owner_id="u1", name="Connec", slug="connec")
    suite.organization_id = organization_id
    suite.connections = {
        "facebook": {"connected": True, "page_id": "page1", "page_access_token": "stored-page"},
        "instagram": {"connected": True, "ig_user_id": "ig1", "page_access_token": "stored-page"},
        "meta_ads": {"connected": True, "ad_account_id": "act_1", "user_access_token": "stored-user"},
    }
    return suite


@pytest.mark.asyncio
async def test_a_linked_suite_uses_the_vault(monkeypatch):
    async def _vault(organization_id, provider, asset_id=None, transport=None):
        assert (organization_id, provider) == ("o1", "meta")
        return "vault-page" if asset_id == "page1" else "vault-user"

    monkeypatch.setattr(meta_tokens, "vault_token", _vault)
    out = await meta_tokens.connections_with_vault_tokens(_suite("o1"))

    assert out["facebook"]["page_access_token"] == "vault-page"
    assert out["instagram"]["page_access_token"] == "vault-page"  # IG posts through the Page
    assert out["meta_ads"]["user_access_token"] == "vault-user"


@pytest.mark.asyncio
async def test_a_suite_without_a_business_keeps_working(monkeypatch):
    called = False

    async def _vault(*_args, **_kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(meta_tokens, "vault_token", _vault)
    out = await meta_tokens.connections_with_vault_tokens(_suite(None))

    assert out["facebook"]["page_access_token"] == "stored-page"
    assert called is False  # nothing to ask the vault about


@pytest.mark.asyncio
async def test_the_vault_having_nothing_yet_does_not_break_publishing(monkeypatch):
    async def _vault(*_args, **_kwargs):
        return None

    monkeypatch.setattr(meta_tokens, "vault_token", _vault)
    out = await meta_tokens.connections_with_vault_tokens(_suite("o1"))

    assert out["facebook"]["page_access_token"] == "stored-page"
    assert out["meta_ads"]["user_access_token"] == "stored-user"


@pytest.mark.asyncio
async def test_nothing_is_written_back_to_the_suite(monkeypatch):
    async def _vault(organization_id, provider, asset_id=None, transport=None):
        return "vault-page" if asset_id else "vault-user"

    monkeypatch.setattr(meta_tokens, "vault_token", _vault)
    suite = _suite("o1")
    await meta_tokens.connections_with_vault_tokens(suite)

    assert suite.connections["facebook"]["page_access_token"] == "stored-page"
