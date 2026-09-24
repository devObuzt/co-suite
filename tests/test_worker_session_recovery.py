"""A job must always reach a terminal state, even when its session is broken.

On 2026-09-23 a cache write failed mid-run. Nothing rolled back, so every later
query on that session raised, the job never finished, the exception escaped to
the worker loop, and the stale sweeper retried the same crash every 30 minutes.
The user just saw a spinner for a quarter of an hour at a time.
"""
import pytest

from api.services import research_cache


class BrokenCommitDb:
    """Commits fail; everything else works — the shape of a poisoned session."""

    def __init__(self):
        self.rolled_back = False
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        class Result:
            @staticmethod
            def scalar_one_or_none():
                return None
        return Result()

    def add(self, _row):
        pass

    async def commit(self):
        raise RuntimeError("duplicate key value violates unique constraint")

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_cache_write_failure_rolls_back_instead_of_poisoning_the_session():
    db = BrokenCommitDb()
    # Must not raise: this is a cache, the caller's work is what matters.
    await research_cache.upsert_cached(
        db, kind="occasions", country="Israel", language="he", period="2026-10", data=[]
    )
    assert db.rolled_back is True, (
        "a failed commit leaves the session unusable until it is rolled back; "
        "skipping that is what turned one cache miss into a crash loop"
    )


@pytest.mark.asyncio
async def test_occasions_rolls_back_when_its_cache_write_fails(monkeypatch):
    from api.services import occasions_service

    db = BrokenCommitDb()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("cache exploded")

    monkeypatch.setattr(occasions_service, "get_cached", boom)
    result = await occasions_service.get_occasions(db, country="Israel", language="he", period="2026-10")
    assert result == []
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_market_research_rolls_back_when_its_cache_write_fails(monkeypatch):
    from api.services import market_research

    db = BrokenCommitDb()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("cache exploded")

    monkeypatch.setattr(market_research, "get_cached", boom)
    result = await market_research.get_market_research(db, country="Israel", language="he", brand={})
    assert result["competitors_summary"] == ""
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_deleting_the_suite_also_puts_the_funnel_lead_back_to_the_start():
    """Erasing the suite alone is not «start over»: the funnel reads the suite
    link and the spent stage budgets off the LEAD, so the visitor would return
    to a suite that no longer exists with their caps already used."""
    from types import SimpleNamespace

    from api.services.suite_erase import reset_funnel_lead

    lead = SimpleNamespace(
        user_id="u1",
        suite_id="suite-1",
        progress={"step": "plans", "suite_created": True, "calls": {"marketing_personas": 5}},
    )

    class Db:
        async def execute(self, *_a, **_k):
            class R:
                @staticmethod
                def scalar_one_or_none():
                    return lead
            return R()

    assert await reset_funnel_lead(Db(), SimpleNamespace(id="u1")) is True
    assert lead.suite_id is None
    assert "calls" not in lead.progress
    assert lead.progress["step"] == "name"
    assert lead.progress["suite_created"] is False


@pytest.mark.asyncio
async def test_a_second_strategy_job_for_the_same_suite_is_held_back(monkeypatch):
    """Two jobs writing one `strategy` column is the whole bug. Row locks were
    tried twice and the paid plan still vanished while its job said
    "completed" — so the claim itself refuses the overlap."""
    from types import SimpleNamespace

    from api.models.generation_job import GenerationJobType
    from api.services import durable_generation_queue as q

    social = SimpleNamespace(id="j-social", suite_id="s1", type=GenerationJobType.social_ideas)
    paid = SimpleNamespace(id="j-paid", suite_id="s1", type=GenerationJobType.paid_content_plan)
    other = SimpleNamespace(id="j-other", suite_id="s2", type=GenerationJobType.social_ideas)
    running = {"s1"}
    claimed = []

    class Db:
        async def execute(self, *_a, **_k):
            class R:
                @staticmethod
                def scalars():
                    return SimpleNamespace(all=lambda: [paid, other])
            return R()

    async def fake_running(_db, suite_id, _exclude):
        return suite_id in running

    async def fake_mark_running(_db, job_id, *_a, **_k):
        claimed.append(job_id)

    monkeypatch.setattr(q, "suite_has_strategy_job_running", fake_running)
    monkeypatch.setattr(q, "mark_running", fake_mark_running)

    job = await q.claim_next_job(Db())
    assert job is other, "the held suite must not block a different suite's job"
    assert claimed == ["j-other"]
    assert social.id not in claimed and paid.id not in claimed


def test_plan_sections_are_merged_by_postgres_not_by_python():
    """Read-modify-write on the whole `strategy` json is what kept losing
    plans: paid wrote 10 ideas at 11:55:14 and social erased them at 11:55:51,
    with both jobs reporting "completed". Row locks were tried twice and did
    not hold. The merge belongs in the database, touching one key only."""
    import inspect

    from api.services import durable_generation_queue as q

    writer = inspect.getsource(q.write_action_plan_section)
    assert "jsonb_set" in writer, "the whole column is still being rewritten"
    assert "marketing_action_plan" in writer

    branch = inspect.getsource(q.execute_claimed_job)
    for section in ("paid_content_plan", "social_ideas_plan", "social_content_plan"):
        assert f'write_action_plan_section(db, suite, "{section}"' in branch, section
    # No terminal write may go back to rewriting the whole blob.
    for old in (
        "_save_suite_paid_content_plan(suite, plan)",
        "_save_suite_social_ideas_plan(suite, plan)",
        "_save_suite_social_content_plan(suite, plan)",
    ):
        assert old not in branch, f"{old} rewrites the entire strategy column"
