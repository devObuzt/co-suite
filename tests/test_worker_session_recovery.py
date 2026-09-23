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
