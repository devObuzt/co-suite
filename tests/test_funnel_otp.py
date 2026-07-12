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
