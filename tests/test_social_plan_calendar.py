from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from api.models.suite import Suite
from api.models.user import User
from api.routers import marketing_plans as mp
from api.services import marketing_plan_generator as mpg


def make_suite(strategy: dict | None = None) -> Suite:
    return Suite(
        id="suite-1",
        owner_id="user-1",
        name="متجر",
        slug="matjar",
        brand={"name": "متجر", "services": ["خدمة"], "audience_languages": ["ar"]},
        strategy=strategy or {},
    )


def make_user() -> User:
    return User(id="user-1", email="owner@example.com", hashed_password="hash", full_name="Owner")


def _items(kind: str, count: int, provider: str = "anthropic", **extra) -> list[dict]:
    return [
        {
            "type": kind,
            "title": f"{kind} فكرة {i}",
            "idea": f"وصف فكرة {kind} {i}",
            "script": "نص جاهز",
            "provider": provider,
            **extra,
        }
        for i in range(1, count + 1)
    ]


def _payload() -> dict:
    return {"suite": {"id": "s1", "name": "متجر"}, "brand": {"name": "متجر"}, "strategy": {}, "planning_inputs": {}}


# ── Schema: production fields ─────────────────────────────────────────────────

def test_candidate_gets_production_fields_with_ai_default():
    item = mpg._normalize_social_content_candidate(
        {"type": "attraction", "title": "فكرة", "idea": "وصف", "format": "post"}, 1, "anthropic"
    )

    assert item["production_mode"] == "ai_image"
    assert item["ai_capability"] == "ai"
    assert item["user_intervention"] is None
    assert item["generation"] == {"status": "idle"}


def test_candidate_real_world_mode_forces_user_required():
    item = mpg._normalize_social_content_candidate(
        {
            "type": "trust",
            "title": "فكرة",
            "idea": "وصف",
            "format": "reel",
            "production_mode": "talking_head",
            "ai_capability": "ai",
            "user_instructions": "صوّر نفسك تشرح الخدمة",
        },
        1,
        "openai",
    )

    assert item["production_mode"] == "talking_head"
    assert item["ai_capability"] == "user_required"
    assert item["user_intervention"]["label"] == "شخص يتحدث للكاميرا"
    assert item["user_intervention"]["instructions"] == "صوّر نفسك تشرح الخدمة"
    assert item["user_intervention"]["required_assets"] == ["human_video"]


def test_candidate_video_format_defaults_to_ai_video():
    item = mpg._normalize_social_content_candidate(
        {"type": "attraction", "title": "فكرة", "idea": "وصف", "format": "reel"}, 1, "anthropic"
    )

    assert item["production_mode"] == "ai_video"
    assert item["ai_capability"] == "ai"


# ── Schedule ──────────────────────────────────────────────────────────────────

def test_weekly_plan_builds_seven_day_schedule():
    plan = mpg.normalize_social_content_plan(
        _items("attraction", 6) + _items("trust", 2) + _items("sales", 2),
        _payload(),
        "ar",
        4,
        plan_type="weekly",
    )

    assert plan["plan_type"] == "weekly"
    assert plan["version"] == "social_content_work_plan_v2"
    assert len(plan["schedule"]["days"]) == 7
    scheduled = [item_id for day in plan["schedule"]["days"] for item_id in day["item_ids"]]
    assert sorted(scheduled) == sorted(plan["selected_ids"])
    assert plan["schedule"]["start_date"] == date.today().isoformat()
    assert plan["schedule"]["end_date"] == (date.today() + timedelta(days=6)).isoformat()


def test_monthly_plan_spreads_items_across_thirty_days():
    plan = mpg.normalize_social_content_plan(
        _items("attraction", 24) + _items("trust", 8) + _items("sales", 4),
        _payload(),
        "ar",
        15,
        plan_type="monthly",
    )

    days = plan["schedule"]["days"]
    assert len(days) == 30
    scheduled = [item_id for day in days for item_id in day["item_ids"]]
    assert len(scheduled) == len(plan["selected_ids"]) == 15
    assert max(len(day["item_ids"]) for day in days) <= 2
    by_id = {
        item["id"]: item
        for group in plan["candidates"].values()
        for item in group
    }
    for day in days:
        for item_id in day["item_ids"]:
            assert by_id[item_id]["scheduled_date"] == day["date"]


def test_selection_update_reassigns_schedule():
    plan = mpg.normalize_social_content_plan(
        _items("attraction", 8) + _items("trust", 3) + _items("sales", 2),
        _payload(),
        "ar",
        4,
        plan_type="weekly",
    )
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    all_ids = [item["id"] for group in plan["candidates"].values() for item in group]
    new_selection = all_ids[:3]

    updated = mp._update_social_content_selection(suite, new_selection)

    scheduled = [item_id for day in updated["schedule"]["days"] for item_id in day["item_ids"]]
    assert sorted(scheduled) == sorted(new_selection)


# ── Item endpoints ────────────────────────────────────────────────────────────

class FakeDb:
    def __init__(self, jobs: list | None = None):
        self.committed = False
        self._jobs = jobs or []

    async def commit(self):
        self.committed = True

    async def execute(self, _query):
        jobs = self._jobs

        class Result:
            def scalars(self):
                return SimpleNamespace(all=lambda: jobs)

            def scalar_one_or_none(self):
                return jobs[0] if jobs else None

        return Result()


def _plan_with_items() -> dict:
    return mpg.normalize_social_content_plan(
        _items("attraction", 4)
        + _items("trust", 2)
        + [
            {
                "type": "sales",
                "title": "فكرة تصوير",
                "idea": "وصف",
                "script": "نص",
                "format": "reel",
                "production_mode": "store_video",
                "provider": "anthropic",
            }
        ],
        _payload(),
        "ar",
        3,
        plan_type="weekly",
    )


@pytest.mark.asyncio
async def test_update_social_content_item_edits_fields(monkeypatch):
    plan = _plan_with_items()
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    target_id = plan["selected_ids"][0]
    db = FakeDb()

    async def fake_get_owned_suite(_db, _sid, _user):
        return suite

    async def fake_audit(_db, **_kwargs):
        return None

    monkeypatch.setattr(mp, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(mp, "record_audit_log", fake_audit)

    await mp.update_marketing_social_content_item(
        "suite-1",
        target_id,
        mp.UpdateSocialContentItemRequest(title="عنوان معدل", script="نص معدل"),
        make_user(),
        db,
    )

    stored = suite.strategy["marketing_action_plan"]["social_content_plan"]
    item = mp._find_social_plan_item(stored, target_id)
    assert item["title"] == "عنوان معدل"
    assert item["script"] == "نص معدل"
    assert item["edited_by_user"] is True
    assert db.committed


@pytest.mark.asyncio
async def test_generate_item_blocks_user_required(monkeypatch):
    plan = _plan_with_items()
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    user_required_item = next(
        item
        for group in plan["candidates"].values()
        for item in group
        if item["ai_capability"] == "user_required"
    )

    async def fake_get_owned_suite(_db, _sid, _user):
        return suite

    monkeypatch.setattr(mp, "get_owned_suite", fake_get_owned_suite)

    with pytest.raises(Exception) as exc:
        await mp.generate_marketing_social_content_item("suite-1", user_required_item["id"], make_user(), FakeDb())

    assert getattr(exc.value, "status_code", None) == 409
    assert exc.value.detail["code"] == "user_assets_required"


@pytest.mark.asyncio
async def test_generate_item_queues_job_for_ai_item(monkeypatch):
    plan = _plan_with_items()
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    ai_item_id = next(
        item["id"]
        for group in plan["candidates"].values()
        for item in group
        if item["ai_capability"] == "ai"
    )
    created = {}

    async def fake_get_owned_suite(_db, _sid, _user):
        return suite

    async def fake_gate(*_args, **_kwargs):
        return None

    async def fake_create_job(_db, suite_id, job_type, user_id, input_data):
        created.update({"suite_id": suite_id, "type": job_type, "input": input_data})
        return SimpleNamespace(id="job-1", status="queued")

    def fake_serialize_job(job, suite_id=None):
        return {"job_id": job.id, "suite_id": suite_id, "status": "queued"}

    async def fake_audit(_db, **_kwargs):
        return None

    monkeypatch.setattr(mp, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(mp, "enforce_generation_gate", fake_gate)
    monkeypatch.setattr(mp, "create_job", fake_create_job)
    monkeypatch.setattr(mp, "serialize_job", fake_serialize_job)
    monkeypatch.setattr(mp, "record_audit_log", fake_audit)

    response = await mp.generate_marketing_social_content_item("suite-1", ai_item_id, make_user(), FakeDb())

    assert response["job_id"] == "job-1"
    assert created["input"]["plan_item_id"] == ai_item_id
    assert created["input"]["count"] == 1
    assert "Execute this planned content idea" in created["input"]["prompt"]
    stored = suite.strategy["marketing_action_plan"]["social_content_plan"]
    item = mp._find_social_plan_item(stored, ai_item_id)
    assert item["generation"]["status"] == "queued"
    assert item["generation"]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_generate_items_batch_skips_user_required(monkeypatch):
    plan = _plan_with_items()
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    jobs = iter(["job-1", "job-2", "job-3", "job-4", "job-5"])

    async def fake_get_owned_suite(_db, _sid, _user):
        return suite

    async def fake_gate(*_args, **_kwargs):
        return None

    async def fake_create_job(_db, _suite_id, _job_type, _user_id, input_data):
        return SimpleNamespace(id=next(jobs), status="queued")

    async def fake_audit(_db, **_kwargs):
        return None

    monkeypatch.setattr(mp, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(mp, "enforce_generation_gate", fake_gate)
    monkeypatch.setattr(mp, "create_job", fake_create_job)
    monkeypatch.setattr(mp, "record_audit_log", fake_audit)

    response = await mp.generate_marketing_social_content_items("suite-1", None, make_user(), FakeDb())

    selected = suite.strategy["marketing_action_plan"]["social_content_plan"]["selected_ids"]
    user_required_selected = [
        item_id
        for item_id in selected
        if mp._find_social_plan_item(
            suite.strategy["marketing_action_plan"]["social_content_plan"], item_id
        )["ai_capability"]
        == "user_required"
    ]
    assert len(response["queued_job_ids"]) == len(selected) - len(user_required_selected)
    assert all(entry["reason"] == "user_assets_required" for entry in response["skipped"])
    assert response["payment_required"] is False


@pytest.mark.asyncio
async def test_sync_social_plan_generation_marks_ready(monkeypatch):
    plan = _plan_with_items()
    ai_item_id = next(
        item["id"]
        for group in plan["candidates"].values()
        for item in group
        if item["ai_capability"] == "ai"
    )
    item = mp._find_social_plan_item(plan, ai_item_id)
    item["generation"] = {"status": "queued", "job_id": "job-9"}
    suite = make_suite({"marketing_action_plan": {"social_content_plan": plan}})
    job = SimpleNamespace(id="job-9", status="completed", result={"post_ids": ["post-7"]}, error=None)
    db = FakeDb(jobs=[job])

    await mp._sync_social_plan_generation(db, suite)

    stored = suite.strategy["marketing_action_plan"]["social_content_plan"]
    synced = mp._find_social_plan_item(stored, ai_item_id)
    assert synced["generation"]["status"] == "ready"
    assert synced["generation"]["post_id"] == "post-7"
    assert db.committed
