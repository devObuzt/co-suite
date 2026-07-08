import pytest

from api.models.user import User
from api.services import admin_audit


def test_new_user_defaults_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    # Column default applies on INSERT; the model-level default must also be frozen
    assert User.approval_status.default.arg == "frozen"


def test_serialize_user_public_includes_approval_and_phone():
    user = User(
        id="u1", email="a@b.com", full_name="A", hashed_password="h",
        approval_status="approved", phone="0501234567",
    )
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "approved"
    assert payload["phone"] == "0501234567"


def test_serialize_user_public_defaults_missing_status_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "frozen"


from api.core.security import frozen_path_allowed


def test_approved_user_passes_everywhere():
    assert frozen_path_allowed("approved", "POST", "/api/v1/suites/")
    assert frozen_path_allowed("approved", "GET", "/api/v1/billing/x")


def test_frozen_user_only_reaches_auth_and_funnel():
    assert frozen_path_allowed("frozen", "GET", "/api/v1/auth/me")
    assert frozen_path_allowed("frozen", "POST", "/api/v1/funnel/enroll")
    assert not frozen_path_allowed("frozen", "GET", "/api/v1/suites/")
    assert not frozen_path_allowed("frozen", "POST", "/api/v1/onboarding/extract-brand")
    assert not frozen_path_allowed("frozen", "GET", "/api/v1/billing/x")


def test_funnel_user_reaches_wizard_paths_but_not_billing():
    assert frozen_path_allowed("funnel", "POST", "/api/v1/onboarding/extract-brand")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/abc")
    assert frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/generate")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/auth/me")
    assert not frozen_path_allowed("funnel", "GET", "/api/v1/billing/x")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/connections/meta/connect")


def test_funnel_user_cannot_create_suites_directly_or_generate_more():
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites/")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites")
    assert not frozen_path_allowed(
        "funnel", "POST", "/api/v1/suites/abc/marketing-plan/competitors/generate-more"
    )
    # GET on the suites collection stays allowed
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/")


def test_admin_user_update_accepts_approval_status():
    from api.routers.admin import AdminUserUpdate
    payload = AdminUserUpdate(approval_status="approved")
    assert payload.approval_status == "approved"
    with pytest.raises(Exception):
        AdminUserUpdate(approval_status="nonsense")


def test_prefix_matching_respects_path_segments():
    assert not frozen_path_allowed("frozen", "GET", "/api/v1/authentication-bypass")
    assert not frozen_path_allowed("funnel", "GET", "/api/v1/suitescoped")
    assert not frozen_path_allowed("funnel", "GET", "/api/v1/onboardingv2/x")
    assert frozen_path_allowed("frozen", "GET", "/api/v1/auth/me")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites")
