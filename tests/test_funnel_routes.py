# tests/test_funnel_routes.py
import pytest
from fastapi import HTTPException

from api.models.services_catalog import Lead, ServiceItem, ServiceRequest
from api.models.user import User
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


class _Result:
    def __init__(self, value=None, *, many=None):
        self._value = value
        self._many = many or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self


class _ScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class SequenceDb:
    """Feeds a fixed sequence of execute() results; commit()/refresh() are no-ops."""

    def __init__(self, results):
        self._results = list(results)
        self.committed = False

    async def execute(self, _query):
        return self._results.pop(0)

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None


def _user(uid="u1", status="funnel"):
    return User(id=uid, email=f"{uid}@x.com", full_name=uid, hashed_password="h", approval_status=status)


@pytest.mark.asyncio
async def test_recommendations_returns_empty_list_on_llm_failure(monkeypatch):
    lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0", suite_id="s1")

    class _Rows:
        def scalars(self):
            return _ScalarsResult([])

    async def _boom(**kwargs):
        raise RuntimeError("LLM overloaded")

    monkeypatch.setattr(funnel, "call_text_ai", _boom)

    db = SequenceDb([
        _Result(lead),          # _require_lead
        _Result(None),          # suite lookup
        _Rows(),                # active ServiceItem rows
    ])

    result = await funnel.recommendations(current_user=_user(), db=db)

    assert result == {"recommended_service_ids": []}
    assert lead.recommendations is None  # not written, so a later retry can succeed
    assert not db.committed


@pytest.mark.asyncio
async def test_submit_service_request_coalesces_pending_request(monkeypatch):
    lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0", suite_id="s1", status="in_progress")
    item = ServiceItem(
        id="s1", name={"ar": "أ", "he": "א"}, description={"ar": "-", "he": "-"},
        category={"ar": "ت", "he": "ש"}, billing_cycle="monthly",
        price_min=800, price_max=None, unit=None, is_active=True, sort_order=1,
    )
    existing_req = ServiceRequest(
        id="r1", lead_id="l1", items=[], totals={}, customer_notes=None, status="new",
    )

    class _Rows:
        def scalars(self):
            return _ScalarsResult([item])

    calls = {"telegram": 0, "audit": 0}

    async def _audit(*args, **kwargs):
        calls["audit"] += 1

    async def _telegram(*args, **kwargs):
        calls["telegram"] += 1

    monkeypatch.setattr(funnel, "record_audit_log", _audit)
    monkeypatch.setattr(funnel, "send_company_message", _telegram)

    db = SequenceDb([
        _Result(lead),          # _require_lead
        _Rows(),                # active ServiceItem rows
        _Result(existing_req),  # pending "new" ServiceRequest lookup
    ])

    data = funnel.FunnelServiceRequestIn(items=[funnel.SelectionItem(service_id="s1", qty=3)])
    result = await funnel.submit_service_request(data, request=None, current_user=_user(), db=db)

    assert existing_req.items[0]["qty"] == 3
    assert result["id"] == "r1"
    assert calls["telegram"] == 0  # no new notification for a coalesced update
    assert calls["audit"] == 1  # audit call kept, tagged as coalesced
    assert db.committed
