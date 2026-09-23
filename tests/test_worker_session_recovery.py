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


def test_the_three_plan_jobs_lock_the_suite_before_their_terminal_write():
    """Two jobs for one suite write the same `strategy` json column from two
    sessions. Without a row lock the second commit erases the first — measured
    2026-09-24: social ideas and the paid plan both reported "completed" at the
    same second and only the social ideas survived."""
    import inspect

    from api.services import durable_generation_queue as q

    source = inspect.getsource(q.execute_claimed_job)
    for saver in (
        "_save_suite_paid_content_plan(suite, plan)",
        "_save_suite_social_ideas_plan(suite, plan)",
        "_save_suite_social_content_plan(suite, plan)",
    ):
        assert saver in source, saver
        before = source.split(saver)[0]
        tail = before.rsplit("\n", 3)[-3:]
        assert any("lock_suite_for_write" in line for line in tail), (
            f"{saver} writes the shared strategy column without re-reading it under a lock"
        )


def test_the_lock_helper_actually_locks_the_row():
    import inspect

    from api.services import durable_generation_queue as q

    source = inspect.getsource(q.lock_suite_for_write)
    assert "with_for_update()" in source, "a plain re-read still loses the other job's write"
