import pytest
from fastapi import HTTPException

from api.core import service_auth
from api.core.config import settings


class _Request:
    def __init__(self, authorization=None):
        self.headers = {"authorization": authorization} if authorization else {}


def test_calling_module_matches_one_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc,heartbeat:def")

    assert service_auth.calling_module("Bearer abc") == "oneshare"
    assert service_auth.calling_module("Bearer def") == "heartbeat"


def test_calling_module_rejects_everything_else(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")

    assert service_auth.calling_module("Bearer wrong") is None
    assert service_auth.calling_module("abc") is None
    assert service_auth.calling_module(None) is None
    assert service_auth.calling_module("Bearer ") is None


def test_a_prefix_of_the_key_is_not_enough(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abcdef")

    assert service_auth.calling_module("Bearer abc") is None


def test_no_keys_configured_means_no_access(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "")

    assert service_auth.calling_module("Bearer abc") is None


@pytest.mark.asyncio
async def test_dependency_raises_401_without_a_valid_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")

    assert await service_auth.require_module(_Request("Bearer abc")) == "oneshare"

    with pytest.raises(HTTPException) as err:
        await service_auth.require_module(_Request("Bearer nope"))
    assert err.value.status_code == 401
