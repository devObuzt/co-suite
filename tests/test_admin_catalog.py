# tests/test_admin_catalog.py
import pytest

from api.routers import admin_catalog


def test_service_item_create_model_requires_bilingual_fields():
    with pytest.raises(Exception):
        admin_catalog.ServiceItemIn(
            name={"ar": "فقط عربي"}, description={"ar": "-", "he": "-"},
            category={"ar": "-", "he": "-"}, billing_cycle="monthly", price_min=10,
        )
    ok = admin_catalog.ServiceItemIn(
        name={"ar": "أ", "he": "א"}, description={"ar": "-", "he": "-"},
        category={"ar": "-", "he": "-"}, billing_cycle="monthly", price_min=10,
    )
    assert ok.price_max is None


def test_lead_patch_model_limits_status():
    with pytest.raises(Exception):
        admin_catalog.LeadPatch(status="everything-is-fine")
    assert admin_catalog.LeadPatch(status="won").status == "won"
