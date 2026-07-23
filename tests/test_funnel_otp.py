# tests/test_funnel_otp.py
from api.core.phone import normalize_phone
from api.models.services_catalog import Lead
from api.routers import funnel


# ── normalization ────────────────────────────────────────────────────────────

def test_normalize_local_israeli_mobile():
    assert normalize_phone("0521234567") == "+972521234567"
    assert normalize_phone("052-123-4567") == "+972521234567"
    assert normalize_phone("052 123 4567") == "+972521234567"


def test_normalize_international_forms_dedupe_to_same():
    assert normalize_phone("+972521234567") == "+972521234567"
    assert normalize_phone("972521234567") == "+972521234567"
    assert normalize_phone("00972521234567") == "+972521234567"
    assert normalize_phone("+972 52-123-4567") == "+972521234567"


def test_normalize_972_with_leading_zero_after_cc():
    assert normalize_phone("9720521234567") == "+972521234567"


def test_normalize_nine_digit_local_without_zero():
    assert normalize_phone("521234567") == "+972521234567"


def test_normalize_other_international_kept():
    assert normalize_phone("+14155551234") == "+14155551234"


def test_normalize_rejects_garbage():
    assert normalize_phone("") is None
    assert normalize_phone(None) is None
    assert normalize_phone("12345") is None
    assert normalize_phone("abc") is None


# ── resume step derivation ───────────────────────────────────────────────────

def _lead(**kw):
    base = dict(id="l1", phone="+972521234567", full_name=None, email=None,
                suite_id=None, progress=None)
    base.update(kw)
    return Lead(**base)


def test_resume_fresh_lead_goes_to_name():
    assert funnel.resume_step_for(_lead(progress={"step": "phone"})) == "name"


def test_resume_respects_stored_step():
    assert funnel.resume_step_for(_lead(progress={"step": "services"})) == "services"


def test_resume_floor_from_name():
    assert funnel.resume_step_for(_lead(full_name="Test", progress={"step": "phone"})) == "suite"


def test_resume_floor_from_suite():
    assert funnel.resume_step_for(_lead(full_name="Test", suite_id="s1", progress={"step": "name"})) == "plans"


def test_resume_done_when_request_submitted():
    lead = _lead(full_name="T", suite_id="s1",
                 progress={"step": "services", "request_submitted": True})
    assert funnel.resume_step_for(lead) == "done"


def test_resume_invalid_stored_step_falls_back():
    assert funnel.resume_step_for(_lead(progress={"step": "bogus"})) == "name"


def test_step_index_monotonic_helper():
    assert funnel._step_index("phone") < funnel._step_index("name") < funnel._step_index("suite")
    assert funnel._step_index("suite") < funnel._step_index("plans") < funnel._step_index("services")
    assert funnel._step_index("services") < funnel._step_index("done")
    assert funnel._step_index(None) == 0
    assert funnel._step_index("bogus") == 0


# ── notification text with phone-only lead ───────────────────────────────────

def test_notification_text_without_name_or_email():
    lead = _lead()
    text = funnel.lead_notification_text(
        lead, {"monthly": {"min": 800.0, "max": 800.0}}, frontend_url="https://cosuite.app"
    )
    assert "+972521234567" in text
    assert "None" not in text


# ── WhatsApp delivery flag ───────────────────────────────────────────────────

import pytest

from api.core.config import settings
from api.services import otp_sender


@pytest.fixture
def whatsapp_credentials(monkeypatch):
    """Credentials present — only the flag decides whether a message goes out."""
    monkeypatch.setattr(settings, "whatsapp_access_token", "token", raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "12345", raising=False)


@pytest.fixture
def no_http(monkeypatch):
    """Any outbound HTTP attempt fails the test."""
    def explode(*args, **kwargs):
        raise AssertionError("otp_sender must not open an HTTP client while frozen")
    monkeypatch.setattr(otp_sender.httpx, "AsyncClient", explode)


def test_flag_off_keeps_static_code(monkeypatch, whatsapp_credentials):
    monkeypatch.setattr(settings, "whatsapp_otp_enabled", False, raising=False)
    assert otp_sender.whatsapp_delivery_enabled() is False
    assert otp_sender.generate_code() == settings.funnel_otp_code == "123456"


async def test_flag_off_sends_nothing(monkeypatch, whatsapp_credentials, no_http):
    monkeypatch.setattr(settings, "whatsapp_otp_enabled", False, raising=False)
    await otp_sender.send_otp("+972521234567", "123456")


async def test_flag_on_without_credentials_sends_nothing(monkeypatch, no_http):
    monkeypatch.setattr(settings, "whatsapp_otp_enabled", True, raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "", raising=False)
    assert otp_sender.generate_code() == "123456"
    await otp_sender.send_otp("+972521234567", "123456")


def test_flag_on_with_credentials_generates_random_code(monkeypatch, whatsapp_credentials):
    monkeypatch.setattr(settings, "whatsapp_otp_enabled", True, raising=False)
    assert otp_sender.whatsapp_delivery_enabled() is True
    codes = {otp_sender.generate_code() for _ in range(30)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 1  # random, not the static code


async def test_flag_on_with_credentials_does_deliver(monkeypatch, whatsapp_credentials, no_http):
    """The mirror of the frozen tests: flipping the flag back on reaches WhatsApp.

    Without this the "sends nothing" tests could pass for the wrong reason.
    """
    monkeypatch.setattr(settings, "whatsapp_otp_enabled", True, raising=False)
    with pytest.raises(AssertionError, match="must not open an HTTP client"):
        await otp_sender.send_otp("+972521234567", "123456")


def test_flag_defaults_to_off():
    """Shipping without the env var set must leave WhatsApp frozen."""
    assert type(settings).model_fields["whatsapp_otp_enabled"].default is False
