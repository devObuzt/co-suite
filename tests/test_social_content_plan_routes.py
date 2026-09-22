"""The social-content plan route used to run generation inside the request.

Six parallel provider calls with a 240s ceiling meant a user who closed the tab
during a four-minute wait lost everything — the only write happened at the end.
"""
from types import SimpleNamespace

import pytest

from api.models.suite import Suite
from api.models.user import User
from api.routers import marketing_plans


class FakeDb:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


async def _noop_async(*_args, **_kwargs):
    return None


async def _async_value(value):
    return value


def _suite():
    return Suite(
        id="suite-scp",
        owner_id="user-scp",
        name="Connec",
        slug="connec-scp",
        brand={"name": "Connec", "audience_languages": ["ar"]},
        strategy={"marketing_action_plan": {"social_ideas_plan": {"selected_ids": ["social-1"]}}},
    )


def _user():
    return User(id="user-scp", email="scp@example.com", hashed_password="h", full_name="SCP")


@pytest.mark.asyncio
async def test_generate_enqueues_a_job_instead_of_running_inline(monkeypatch):
    suite, user, db = _suite(), _user(), FakeDb()
    created, generator_ran = [], []

    async def fake_generate(*_a, **_k):
        generator_ran.append(True)
        return {}

    async def fake_create_job(_db, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="job-scp-1", user_id=user.id)

    monkeypatch.setattr(marketing_plans, "get_owned_suite", lambda *a, **k: _async_value(suite))
    monkeypatch.setattr(marketing_plans, "generate_social_content_work_plan", fake_generate)
    monkeypatch.setattr(marketing_plans, "get_active_job", lambda *a, **k: _async_value(None))
    monkeypatch.setattr(marketing_plans, "create_job", fake_create_job)
    monkeypatch.setattr(marketing_plans, "record_audit_log", _noop_async)
    monkeypatch.setattr(marketing_plans, "serialize_job", lambda job, **kw: {"id": getattr(job, "id", None)})

    response = await marketing_plans.generate_marketing_social_content_plan(
        suite.id, marketing_plans.GenerateSocialContentPlanRequest(language="ar"), user, db
    )

    assert not generator_ran, "the request must not run six provider calls inline"
    assert created and created[0]["job_type"].value == "social_content_plan"
    assert response["status"] == "generating"
    action = suite.strategy["marketing_action_plan"]
    assert action["social_content_plan"]["status"] == "generating"
    # Queueing must not wipe the sibling plans on the same blob.
    assert action["social_ideas_plan"] == {"selected_ids": ["social-1"]}
    assert db.committed is True


@pytest.mark.asyncio
async def test_generate_does_not_queue_a_second_job(monkeypatch):
    suite, user, db = _suite(), _user(), FakeDb()
    created = []

    async def fake_create_job(_db, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="job-scp-2", user_id=user.id)

    monkeypatch.setattr(marketing_plans, "get_owned_suite", lambda *a, **k: _async_value(suite))
    monkeypatch.setattr(
        marketing_plans, "get_active_job",
        lambda *a, **k: _async_value(SimpleNamespace(id="already-running", user_id=user.id)),
    )
    monkeypatch.setattr(marketing_plans, "create_job", fake_create_job)
    monkeypatch.setattr(marketing_plans, "serialize_job", lambda job, **kw: {"id": getattr(job, "id", None)})

    response = await marketing_plans.generate_marketing_social_content_plan(
        suite.id, marketing_plans.GenerateSocialContentPlanRequest(language="ar"), user, db
    )

    assert created == [], "an impatient second click must not duplicate the job"
    assert response["status"] == "generating"
