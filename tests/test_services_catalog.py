from api.models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)


def test_service_item_serialization_roundtrip():
    item = ServiceItem(
        id="s1",
        name={"ar": "موقع تعريفي", "he": "אתר תדמיתי"},
        description={"ar": "وصف", "he": "תיאור"},
        category={"ar": "مواقع وتطبيقات", "he": "אתרים ואפליקציות"},
        billing_cycle="one_time",
        price_min=3500,
        price_max=None,
        unit=None,
        is_active=True,
        sort_order=1,
    )
    out = serialize_service_item(item)
    assert out["name"]["he"] == "אתר תדמיתי"
    assert out["billing_cycle"] == "one_time"
    assert out["price_max"] is None


def test_lead_defaults():
    lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.com", phone="050")
    out = serialize_lead(lead)
    assert out["status"] == "new"
    assert out["source"] == "startbyconnec"
    assert out["suite_id"] is None


def test_service_request_serialization():
    req = ServiceRequest(
        id="r1", lead_id="l1",
        items=[{"service_id": "s1", "qty": 2}],
        totals={"monthly": {"min": 800.0, "max": 800.0}},
        customer_notes="ملاحظات",
    )
    out = serialize_service_request(req)
    assert out["status"] == "new"
    assert out["totals"]["monthly"]["min"] == 800.0


from api.services.service_pricing import compute_totals


def test_compute_totals_mixed_cycles_and_ranges():
    totals = compute_totals([
        {"billing_cycle": "one_time", "price_min": 3500, "price_max": None, "qty": 1},
        {"billing_cycle": "one_time", "price_min": 5500, "price_max": 8500, "qty": 1},
        {"billing_cycle": "monthly", "price_min": 800, "price_max": None, "qty": 1},
        {"billing_cycle": "monthly", "price_min": 2200, "price_max": None, "qty": 1},
        {"billing_cycle": "yearly", "price_min": 69, "price_max": 90, "qty": 1},
    ])
    assert totals["one_time"] == {"min": 9000.0, "max": 12000.0}
    assert totals["monthly"] == {"min": 3000.0, "max": 3000.0}
    assert totals["yearly"] == {"min": 69.0, "max": 90.0}


def test_compute_totals_quantity_and_bad_input():
    # unknown cycle is coerced to one_time, qty floors at 1
    totals = compute_totals([
        {"billing_cycle": "one_time", "price_min": 1200, "price_max": None, "qty": 3},
        {"billing_cycle": "bogus-cycle", "price_min": 10, "price_max": None, "qty": 0},
    ])
    assert totals["one_time"] == {"min": 3610.0, "max": 3610.0}
    assert "bogus-cycle" not in totals


def test_compute_totals_empty():
    assert compute_totals([]) == {}


from api.services.service_catalog_seed import SEED_ITEMS


def test_seed_items_are_complete_and_bilingual():
    assert len(SEED_ITEMS) >= 12
    for item in SEED_ITEMS:
        assert item["name"]["ar"] and item["name"]["he"]
        assert item["description"]["ar"] and item["description"]["he"]
        assert item["category"]["ar"] and item["category"]["he"]
        assert item["billing_cycle"] in ("one_time", "monthly", "yearly")
        assert item["price_min"] > 0
        if item["price_max"] is not None:
            assert item["price_max"] >= item["price_min"]


import pytest

from api.services import telegram_notify


@pytest.mark.asyncio
async def test_send_company_message_skips_without_config(monkeypatch):
    monkeypatch.setattr(telegram_notify.settings, "telegram_bot_token", "")
    monkeypatch.setattr(telegram_notify.settings, "telegram_company_chat_id", "")
    assert await telegram_notify.send_company_message("hi") is False


@pytest.mark.asyncio
async def test_send_company_message_survives_network_errors(monkeypatch):
    monkeypatch.setattr(telegram_notify.settings, "telegram_bot_token", "t")
    monkeypatch.setattr(telegram_notify.settings, "telegram_company_chat_id", "c")

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("network down")

    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", BoomClient)
    assert await telegram_notify.send_company_message("hi") is False
