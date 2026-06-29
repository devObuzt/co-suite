from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.models.user import User
from api.models.billing import BillingEventType, LedgerAccountType, UsageEvent
from api.models.admin import AppTextOverride
from api.routers import admin
from api.routers import app_text
from api.services import admin_audit


class FakeDb:
    def __init__(self):
        self.committed = False
        self.refreshed = None

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        self.refreshed = value


@pytest.mark.asyncio
async def test_admin_email_promotes_super_admin(monkeypatch):
    monkeypatch.setattr(admin_audit.settings, "admin_email", "owner@example.com")
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="hash", is_super_admin=False)
    db = FakeDb()

    promoted = await admin_audit.ensure_admin_flag(user, db)

    assert promoted.is_super_admin is True
    assert db.committed is True
    assert db.refreshed is user


@pytest.mark.asyncio
async def test_require_super_admin_blocks_regular_users(monkeypatch):
    monkeypatch.setattr(admin_audit.settings, "admin_email", "owner@example.com")
    user = User(id="user-1", email="member@example.com", full_name="Member", hashed_password="hash", is_super_admin=False)

    with pytest.raises(HTTPException) as exc:
        await admin_audit.require_super_admin(user, FakeDb())

    assert exc.value.status_code == 403


def test_serialize_user_public_never_exposes_password_hash():
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="secret-hash", is_super_admin=True)

    payload = admin_audit.serialize_user_public(user)

    assert payload["email"] == "owner@example.com"
    assert payload["is_super_admin"] is True
    assert "hashed_password" not in payload
    assert "secret-hash" not in str(payload)


def test_period_bounds_cover_named_ranges():
    today_start, today_end = admin_audit.period_bounds("today")
    all_start, all_end = admin_audit.period_bounds("all")
    custom_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    custom_end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    assert today_start is not None
    assert today_end is not None
    assert today_end > today_start
    assert (all_start, all_end) == (None, None)
    assert admin_audit.period_bounds("custom", custom_start, custom_end) == (custom_start, custom_end)


def test_billing_usage_out_explains_billed_rows():
    event = UsageEvent(
        id="usage-1",
        subscription_id="sub-1",
        suite_id="suite-1",
        event_type="image_gen",
        ledger_account=LedgerAccountType.generation_tokens,
        billing_event_type=BillingEventType.generation_usage,
        amount_tokens=12,
        actual_cost_usd=0.48,
        billed_amount=1.44,
        event_data={"post_id": "post-1", "model": "image"},
    )

    payload = admin._billing_usage_out(event, "Suite One", "owner@example.com")

    assert payload["suite_name"] == "Suite One"
    assert payload["owner_email"] == "owner@example.com"
    assert payload["event_type"] == "image_gen"
    assert payload["amount_tokens"] == 12
    assert payload["actual_cost_usd"] == 0.48
    assert payload["billed_amount"] == 1.44
    assert payload["event_data"]["post_id"] == "post-1"


def test_app_text_language_codes_normalize_region_variants():
    assert admin._normalize_language_code("ar-IL") == "ar"
    assert app_text.normalize_language_code("he_IL") == "he"


def test_app_text_override_out_uses_admin_shape():
    row = AppTextOverride(
        id="text-1",
        language="ar",
        text_key="nav.dashboard",
        value="الرئيسية",
        updated_by_email="admin@example.com",
    )

    payload = admin._app_text_override_out(row)

    assert payload["language"] == "ar"
    assert payload["key"] == "nav.dashboard"
    assert payload["value"] == "الرئيسية"
    assert payload["updated_by_email"] == "admin@example.com"
