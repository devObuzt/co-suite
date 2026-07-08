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


from unittest.mock import AsyncMock

from fastapi import HTTPException

from api.services.suite_access import require_suite_access


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class AccessDb:
    """Feeds require_suite_access's three sequential queries: suite, member, lead."""

    def __init__(self, suite=None, member=None, lead=None):
        self._answers = [suite, member, lead]
        self._i = 0

    async def execute(self, _query):
        value = self._answers[min(self._i, len(self._answers) - 1)]
        self._i += 1
        return _Result(value)


def _user(uid="u1", status="approved"):
    from api.models.user import User
    return User(id=uid, email=f"{uid}@x.com", full_name=uid, hashed_password="h", approval_status=status)


def _suite(owner="owner-1", sid="s1"):
    from api.models.suite import Suite
    return Suite(id=sid, owner_id=owner, name="S", slug="s")


@pytest.mark.asyncio
async def test_member_gets_access_when_not_owner():
    from api.models.suite import SuiteMember
    db = AccessDb(suite=_suite(), member=SuiteMember(id="m1", suite_id="s1", user_id="u1"))
    suite = await require_suite_access(db, "s1", _user())
    assert suite.id == "s1"


@pytest.mark.asyncio
async def test_stranger_gets_404():
    db = AccessDb(suite=_suite(), member=None)
    with pytest.raises(HTTPException) as exc:
        await require_suite_access(db, "s1", _user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_funnel_user_restricted_to_lead_suite():
    from api.models.suite import SuiteMember
    from api.models.services_catalog import Lead
    member = SuiteMember(id="m1", suite_id="s1", user_id="u1")
    other_lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0", suite_id="different-suite")
    db = AccessDb(suite=_suite(), member=member, lead=other_lead)
    with pytest.raises(HTTPException) as exc:
        await require_suite_access(db, "s1", _user(status="funnel"))
    assert exc.value.status_code == 403


from api.services.funnel_guard import block_funnel_regeneration


def test_funnel_user_blocked_when_output_exists():
    with pytest.raises(HTTPException) as exc:
        block_funnel_regeneration(_user(status="funnel"), already_generated=True)
    assert exc.value.status_code == 403
    assert exc.value.detail == "funnel_regeneration_blocked"


def test_funnel_user_allowed_first_time_and_approved_always():
    block_funnel_regeneration(_user(status="funnel"), already_generated=False)
    block_funnel_regeneration(_user(status="approved"), already_generated=True)


def test_funnel_explicit_allowlist_blocks_cost_holes():
    assert not frozen_path_allowed("funnel", "DELETE", "/api/v1/suites/abc/marketing-plan")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/competitors/generate")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/social-content-plan/generate-items")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/visuals/generate")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/onboarding/anything-else")


def test_funnel_explicit_allowlist_keeps_wizard_open():
    assert frozen_path_allowed("funnel", "POST", "/api/v1/onboarding/extract-brand")
    assert frozen_path_allowed("funnel", "POST", "/api/v1/onboarding/generate-strategy")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/abc")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/abc/marketing-plan/pdf")
    assert frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/generate")
    assert frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/social-content-plan/selection")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/funnel/catalog")


from api.services.funnel_guard import enforce_funnel_call_limit


class CallLimitDb:
    """Feeds enforce_funnel_call_limit's single Lead lookup + commit tracking."""

    def __init__(self, lead):
        self._lead = lead
        self.committed = False

    async def execute(self, _query):
        return _Result(self._lead)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_funnel_call_limit_blocks_at_limit():
    from api.models.services_catalog import Lead
    lead = Lead(
        id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0",
        progress={"calls": {"extract_brand": 5}},
    )
    db = CallLimitDb(lead)
    with pytest.raises(HTTPException) as exc:
        await enforce_funnel_call_limit(db, _user(status="funnel"), "extract_brand", 5)
    assert exc.value.status_code == 429
    assert exc.value.detail == "funnel_call_limit"
    assert not db.committed


@pytest.mark.asyncio
async def test_funnel_call_limit_increments_and_commits_below_limit():
    from api.models.services_catalog import Lead
    lead = Lead(
        id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0",
        progress={"calls": {"extract_brand": 2}},
    )
    db = CallLimitDb(lead)
    await enforce_funnel_call_limit(db, _user(status="funnel"), "extract_brand", 5)
    assert lead.progress["calls"]["extract_brand"] == 3
    assert db.committed


@pytest.mark.asyncio
async def test_funnel_call_limit_noop_for_approved_users():
    db = CallLimitDb(lead=None)
    await enforce_funnel_call_limit(db, _user(status="approved"), "extract_brand", 5)
    assert not db.committed
