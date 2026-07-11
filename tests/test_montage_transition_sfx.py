"""Unit tests for scene-boundary sound-effect selection in the video montage.

Regression: the boundary loop filtered ``kind == "transition"`` creative assets,
but the library only ships audio ``sfx`` and visual ``transition_video`` assets —
no audio ``transition`` asset is ever seeded. So the loop always fell through to a
single generated ``soft-whoosh.wav`` and every scene boundary of every video got
the identical sound. These tests pin the fix: boundaries draw varied,
transition-flavoured sounds from the sfx pool.
"""
from types import SimpleNamespace

from api.services.video_montage import transition_sound_pool, varied_index_sequence


def _sfx(asset_id: str, tags: list[str]):
    return SimpleNamespace(id=asset_id, tags=tags, storage_url=f"/static/{asset_id}.mp3")


# ── transition_sound_pool ─────────────────────────────────────────────────────

def test_pool_prefers_transition_flavoured_sfx():
    swoosh = _sfx("swoosh", ["impact", "transition", "whoosh"])
    pop = _sfx("pop", ["energy", "pop"])
    impact = _sfx("impact", ["impact"])
    shutter = _sfx("shutter", ["camera", "shutter"])
    pool = transition_sound_pool([swoosh, pop, impact, shutter])
    assert swoosh in pool and pop in pool and impact in pool
    assert shutter not in pool  # a camera ping is not a scene-cut accent


def test_pool_falls_back_to_full_library_when_too_few_flavoured():
    # Only shutters available: still return them so boundaries can vary at all.
    shutters = [_sfx("a", ["camera", "shutter"]), _sfx("b", ["camera", "shutter"])]
    assert transition_sound_pool(shutters) == shutters


def test_pool_empty_for_empty_input():
    assert transition_sound_pool([]) == []


# ── varied_index_sequence ─────────────────────────────────────────────────────

def test_sequence_covers_all_indices_and_is_seed_deterministic():
    seq = varied_index_sequence(6, 3, seed=123)
    assert len(seq) == 6
    assert set(seq) == {0, 1, 2}
    assert seq == varied_index_sequence(6, 3, seed=123)


def test_sequence_order_changes_with_seed():
    a = varied_index_sequence(8, 5, seed=1)
    b = varied_index_sequence(8, 5, seed=999)
    assert a != b  # different render -> different boundary sound order


def test_sequence_handles_degenerate_inputs():
    assert varied_index_sequence(0, 3, seed=1) == []
    assert varied_index_sequence(5, 0, seed=1) == []


# ── end-to-end selection behaviour ────────────────────────────────────────────

def test_boundaries_are_not_all_the_same_sound():
    sfx = [_sfx("a", ["whoosh"]), _sfx("b", ["impact"]), _sfx("c", ["pop"])]
    pool = transition_sound_pool(sfx)
    chosen = [pool[i].id for i in varied_index_sequence(4, len(pool), seed=42)]
    assert len(set(chosen)) >= 2  # not the single-whoosh-forever regression
