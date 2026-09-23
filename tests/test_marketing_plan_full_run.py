"""The plan chain lives on the server now — a refresh must not abandon it.

The browser used to drive keywords → competitors → demand/supply → personas →
message itself. Reloading the page mid-run left a half-built plan that nothing
ever finished, because the page only restarted the chain when the plan was
COMPLETELY empty.
"""
from types import SimpleNamespace

import pytest

from api.models.suite import Suite
from api.models.user import User
from api.routers import marketing_plans
from api.services import marketing_plan_full_run as full_run


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


async def _async_value(value):
    return value


def _suite(strategy=None, suite_id="suite-full"):
    return Suite(
        id=suite_id,
        owner_id="user-full",
        name="Connec",
        slug=suite_id,
        brand={"name": "Connec", "audience_languages": ["ar"]},
        strategy=strategy or {},
    )


def test_stage_status_reads_a_half_built_plan_as_partial():
    suite = _suite({"marketing_intelligence": {"keywords": [{"text": "k"}], "competitors": []}})
    status = full_run.plan_stage_status(suite)
    assert status["keywords"] is True
    assert status["competitors"] is False
    # This is the exact state the old page treated as "done": some data exists.
    assert full_run.pending_plan_stages(suite) == ["competitors", "demand_supply", "personas", "message"]


def test_stage_status_is_complete_only_when_every_stage_has_data():
    suite = _suite(
        {
            "marketing_intelligence": {
                "keywords": [{"text": "k"}],
                "competitors": [{"name": "c"}],
                "demand_supply": {"summary": {}},
                "personas": [{"name": "p"}],
            },
            "marketing_message": "hello",
        }
    )
    assert full_run.pending_plan_stages(suite) == []


def test_blank_message_does_not_count_as_a_generated_message():
    suite = _suite({"marketing_message": "   "})
    assert full_run.plan_stage_status(suite)["message"] is False


@pytest.mark.asyncio
async def test_full_run_skips_finished_stages_and_builds_the_rest(monkeypatch):
    """Resume, not rebuild: an interrupted run must not redo paid research."""
    suite = _suite({"marketing_intelligence": {"keywords": [{"text": "k"}]}})
    db = FakeDb()
    ran = []
    progress = []

    async def stage(name):
        ran.append(name)

    monkeypatch.setattr(
        full_run,
        "_STAGE_RUNNERS",
        {
            "keywords": lambda _db, _s, _l: stage("keywords"),
            "competitors": lambda _db, s, _l: _fill(s, "competitors", [{"name": "c"}], ran),
            "demand_supply": lambda _db, s, _l: _fill(s, "demand_supply", {"summary": {}}, ran),
            "personas": lambda _db, s, _l: _fill(s, "personas", [{"name": "p"}], ran),
            "message": lambda _db, s, _l: _set_message(s, "hello", ran),
        },
    )

    async def fake_progress(_db, _job_id, event):
        progress.append(event)

    completed = {}

    async def fake_completed(_db, job_id, result):
        completed.update(result)
        return SimpleNamespace(id=job_id)

    monkeypatch.setattr(full_run, "mark_progress", fake_progress)
    monkeypatch.setattr(full_run, "mark_completed", fake_completed)

    await full_run.run_full_marketing_plan(db, SimpleNamespace(id="job-1"), suite, "ar")

    assert "keywords" not in ran, "a finished stage must not be regenerated"
    assert ran == ["competitors", "demand_supply", "personas", "message"]
    assert completed["failed"] == []
    # The page reads the live stage off these events.
    assert [event["stage"] for event in progress][0] == "competitors"
    # The reveal contract: the page shows a section only once this map says the
    # stage is DONE, so a stage must read False while it is still running.
    starting = progress[0]["result"]["plan_stages"]
    assert starting["competitors"] is False
    assert starting["keywords"] is True
    assert completed["plan_stages"] == {
        "keywords": True,
        "competitors": True,
        "demand_supply": True,
        "personas": True,
        "message": True,
    }


@pytest.mark.asyncio
async def test_one_dead_stage_does_not_block_the_rest(monkeypatch):
    suite = _suite()
    db = FakeDb()
    ran = []

    async def boom(*_args):
        raise RuntimeError("serpapi down")

    monkeypatch.setattr(
        full_run,
        "_STAGE_RUNNERS",
        {
            "keywords": lambda _db, s, _l: _fill(s, "keywords", [{"text": "k"}], ran),
            "competitors": lambda _db, _s, _l: boom(),
            "demand_supply": lambda _db, s, _l: _fill(s, "demand_supply", {"summary": {}}, ran),
            "personas": lambda _db, s, _l: _fill(s, "personas", [{"name": "p"}], ran),
            "message": lambda _db, s, _l: _set_message(s, "hello", ran),
        },
    )
    monkeypatch.setattr(full_run, "mark_progress", lambda *a, **k: _async_value(None))

    completed = {}

    async def fake_completed(_db, job_id, result):
        completed.update(result)
        return SimpleNamespace(id=job_id)

    monkeypatch.setattr(full_run, "mark_completed", fake_completed)

    await full_run.run_full_marketing_plan(db, SimpleNamespace(id="job-2"), suite, "ar")

    assert completed["failed"] == ["competitors"]
    assert ran == ["keywords", "demand_supply", "personas", "message"]


@pytest.mark.asyncio
async def test_a_run_where_everything_failed_is_a_failed_job(monkeypatch):
    suite = _suite()
    db = FakeDb()

    async def boom(*_args):
        raise RuntimeError("provider down")

    monkeypatch.setattr(full_run, "_STAGE_RUNNERS", {name: (lambda _db, _s, _l: boom()) for name in full_run.STAGE_ORDER})
    monkeypatch.setattr(full_run, "mark_progress", lambda *a, **k: _async_value(None))
    failed = {}

    async def fake_failed(_db, job_id, error, result=None):
        failed["error"] = error
        return SimpleNamespace(id=job_id)

    monkeypatch.setattr(full_run, "mark_failed", fake_failed)
    monkeypatch.setattr(full_run, "mark_completed", lambda *a, **k: pytest.fail("must not complete"))

    await full_run.run_full_marketing_plan(db, SimpleNamespace(id="job-3"), suite, "ar")
    assert "keywords" in failed["error"]


@pytest.mark.asyncio
async def test_full_generate_enqueues_one_job_and_reuses_it_on_refresh(monkeypatch):
    """The page re-posts this on every load; the second post must not fork a run."""
    suite = _suite()
    user = User(id="user-full", email="f@e.com", hashed_password="h", full_name="F")
    db = FakeDb()
    created = []
    active = {"job": None}

    async def fake_create_job(_db, **kwargs):
        created.append(kwargs)
        active["job"] = SimpleNamespace(id="job-full-1", status=SimpleNamespace(value="queued"))
        return active["job"]

    monkeypatch.setattr(marketing_plans, "get_owned_suite", lambda *a, **k: _async_value(suite))
    monkeypatch.setattr(marketing_plans, "_active_marketing_plan_job", lambda *a, **k: _async_value(active["job"]))
    monkeypatch.setattr(marketing_plans, "_latest_marketing_plan_job", lambda *a, **k: _async_value(active["job"]))
    monkeypatch.setattr(marketing_plans, "create_job", fake_create_job)
    monkeypatch.setattr(marketing_plans, "enforce_funnel_call_limit", lambda *a, **k: _async_value(None))
    monkeypatch.setattr(marketing_plans, "serialize_job", lambda job, **kw: {"id": getattr(job, "id", None)})

    first = await marketing_plans.generate_full_marketing_plan(suite.id, None, user, db)
    second = await marketing_plans.generate_full_marketing_plan(suite.id, None, user, db)

    assert len(created) == 1, "a refresh must attach to the running job, not start a new one"
    assert created[0]["input_data"]["section"] == "full"
    assert created[0]["input_data"]["stages"] == full_run.STAGE_ORDER
    assert first["generation_status"]["id"] == "job-full-1"
    assert second["generation_status"]["id"] == "job-full-1"


@pytest.mark.asyncio
async def test_full_generate_does_nothing_when_the_plan_is_already_complete(monkeypatch):
    suite = _suite(
        {
            "marketing_intelligence": {
                "keywords": [{"text": "k"}],
                "competitors": [{"name": "c"}],
                "demand_supply": {"summary": {}},
                "personas": [{"name": "p"}],
            },
            "marketing_message": "hello",
        }
    )
    user = User(id="user-full", email="f@e.com", hashed_password="h", full_name="F")
    db = FakeDb()
    created = []

    monkeypatch.setattr(marketing_plans, "get_owned_suite", lambda *a, **k: _async_value(suite))
    monkeypatch.setattr(marketing_plans, "_active_marketing_plan_job", lambda *a, **k: _async_value(None))
    monkeypatch.setattr(marketing_plans, "_latest_marketing_plan_job", lambda *a, **k: _async_value(None))
    monkeypatch.setattr(marketing_plans, "create_job", lambda *a, **k: created.append(k))
    monkeypatch.setattr(marketing_plans, "enforce_funnel_call_limit", lambda *a, **k: _async_value(None))
    monkeypatch.setattr(marketing_plans, "serialize_job", lambda job, **kw: {"id": getattr(job, "id", None)})

    response = await marketing_plans.generate_full_marketing_plan(suite.id, None, user, db)
    assert created == []
    assert response["status"] == "ready"
    assert response["plan_stages"]["personas"] is True


async def _fill(suite, key, value, ran):
    ran.append("demand_supply" if key == "demand_supply" else key)
    strategy = dict(suite.strategy or {})
    intel = dict(strategy.get("marketing_intelligence") or {})
    intel[key] = value
    strategy["marketing_intelligence"] = intel
    suite.strategy = strategy


async def _set_message(suite, message, ran):
    ran.append("message")
    suite.strategy = {**(suite.strategy or {}), "marketing_message": message}


def test_extraction_asks_for_city_and_country_separately():
    """The old prompt returned one free string and the page split it on a
    comma — so a town named alone ("Yarka") landed in the COUNTRY field and
    became the ad-targeting country."""
    from api.services.brand_ai import EXTRACTION_PROMPT

    assert '"location_city"' in EXTRACTION_PROMPT
    assert '"location_country"' in EXTRACTION_PROMPT
    assert "a town alone is never a country" in EXTRACTION_PROMPT


def test_serialize_job_exposes_the_plan_stage_map():
    from types import SimpleNamespace

    from api.models.generation_job import GenerationJobStatus, GenerationJobType
    from api.services.generation_jobs import serialize_job

    job = SimpleNamespace(
        id="job-x",
        suite_id="suite-x",
        type=GenerationJobType.marketing_plan,
        status=GenerationJobStatus.running,
        stage="competitors",
        message="",
        progress=25,
        error=None,
        provider=None,
        model=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        rate_limit_reset_at=None,
        estimated_wait_seconds=None,
        created_at=None,
        updated_at=None,
        started_at=None,
        finished_at=None,
        result={"plan_stages": {"keywords": True, "competitors": False}},
    )
    payload = serialize_job(job)
    assert payload["plan_stages"] == {"keywords": True, "competitors": False}


@pytest.mark.asyncio
async def test_no_whatsapp_message_when_the_visitor_did_not_ask(monkeypatch):
    from api.services import plan_notify

    suite = _suite()
    sent = []
    monkeypatch.setattr(plan_notify, "whatsapp_notify_available", lambda: True)
    monkeypatch.setattr(full_run, "send_plan_ready", lambda *a, **k: sent.append(a) or _async_value(True))
    await full_run._notify_if_asked(FakeDb(), suite)
    assert sent == []


@pytest.mark.asyncio
async def test_the_message_goes_out_once_and_is_not_repeated_on_retry(monkeypatch):
    """The job can be retried; the visitor must not be messaged twice."""
    from api.services import plan_notify

    suite = _suite()
    plan_notify.save_preference(suite, whatsapp=True, language="he", phone="+972500000000")
    calls = []

    async def fake_send(phone, language, name):
        calls.append((phone, language, name))
        return True

    monkeypatch.setattr(full_run, "send_plan_ready", fake_send)
    db = FakeDb()
    await full_run._notify_if_asked(db, suite)
    await full_run._notify_if_asked(db, suite)
    assert len(calls) == 1, "a retried job must not message the visitor again"
    assert calls[0][1] == "he"


def test_arabic_and_hebrew_have_their_own_template_english_covers_the_rest():
    from api.services import plan_notify

    assert plan_notify.template_language_code("ar") == "ar"
    assert plan_notify.template_language_code("he") == "he"
    for other in ("en", "fr", "es", "tr", "ru", "zh", ""):
        assert plan_notify.template_language_code(other) == "en", other
    assert plan_notify.template_for_language("ar") != plan_notify.template_for_language("he")
    assert plan_notify.template_for_language("zh") == plan_notify.template_for_language("en")


@pytest.mark.asyncio
async def test_nothing_is_sent_while_whatsapp_is_not_configured():
    """The page hides the button off the same check, so this is belt and braces."""
    from api.services import plan_notify

    assert plan_notify.whatsapp_notify_available() is False
    assert await plan_notify.send_plan_ready("+972500000000", "ar", "Connec") is False
