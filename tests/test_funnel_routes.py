# tests/test_funnel_routes.py
import pytest
from fastapi import HTTPException

from api.models.services_catalog import Lead, ServiceItem
from api.routers import funnel


def test_register_requires_phone():
    with pytest.raises(Exception):
        funnel.FunnelRegisterRequest(email="a@b.com", password="x12345", full_name="A", phone="")


def test_snapshot_items_validates_and_prices():
    catalog = {
        "s1": ServiceItem(
            id="s1", name={"ar": "أ", "he": "א"}, description={"ar": "-", "he": "-"},
            category={"ar": "ت", "he": "ש"}, billing_cycle="monthly",
            price_min=800, price_max=None, unit=None, is_active=True, sort_order=1,
        )
    }
    items, totals = funnel.snapshot_selection(
        [{"service_id": "s1", "qty": 2}], catalog
    )
    assert items[0]["name"]["ar"] == "أ"
    assert items[0]["qty"] == 2
    assert totals["monthly"] == {"min": 1600.0, "max": 1600.0}


def test_snapshot_selection_rejects_unknown_ids():
    with pytest.raises(HTTPException) as exc:
        funnel.snapshot_selection([{"service_id": "ghost", "qty": 1}], {})
    assert exc.value.status_code == 400


def test_lead_telegram_message_contains_links_and_totals():
    lead = Lead(id="l1", user_id="u1", full_name="Test Person", email="t@p.com", phone="0501112222", suite_id="s9")
    text = funnel.lead_notification_text(
        lead,
        {"one_time": {"min": 9000.0, "max": 12000.0}, "monthly": {"min": 800.0, "max": 800.0}},
        frontend_url="https://cosuite.app",
    )
    assert "Test Person" in text
    assert "0501112222" in text
    assert "https://cosuite.app/admin/leads" in text
    assert "9,000" in text and "12,000" in text
