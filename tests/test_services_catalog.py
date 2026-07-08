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
