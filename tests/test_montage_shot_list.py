import pytest

from api.core.config import settings
from api.models.suite import Suite
from api.services import montage_shot_list
from api.services.montage_shot_list import generate_shot_list, validate_shot_list_beats


def make_suite() -> Suite:
    return Suite(
        id="suite-shot-list",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك", "industry": "marketing", "colors": {"primary": "#e6aa3b"}},
    )


def test_validate_beats_repairs_gaps_and_overlaps_into_exact_tiling():
    raw = [
        {"start": 0.4, "end": 2.0, "text": "مقدمة", "beat_type": "narrative", "visual_prompt": "city skyline at dusk", "keyword": "مقدمة"},
        # Overlaps the previous beat and leaves a gap before the next one.
        {"start": 1.6, "end": 3.1, "text": "استشارة", "beat_type": "enumeration", "visual_prompt": "open laptop showing a video call", "keyword": "استشارة", "prefer": "image"},
        {"start": 4.0, "end": 5.6, "text": "تصوير ومونتاج", "beat_type": "enumeration", "visual_prompt": "video editing timeline on a monitor", "keyword": "تصوير مونتاج وأكثر", "prefer": "video"},
    ]

    beats = validate_shot_list_beats(raw, range_start=0.0, range_end=6.0, max_beats=24)

    assert beats is not None
    # Exact tiling: first beat starts at the range start, each beat starts
    # where the previous ends, the last beat ends at the range end.
    assert beats[0]["start"] == 0.0
    assert beats[-1]["end"] == 6.0
    for previous, current in zip(beats, beats[1:]):
        assert previous["end"] == current["start"]
    # Keyword is clamped to two words; defaults hold.
    assert beats[2]["keyword"] == "تصوير مونتاج"
    assert beats[0]["prefer"] == "image"
    assert beats[1]["beat_type"] == "enumeration"


def test_validate_beats_rejects_unusable_output():
    # Not a list at all.
    assert validate_shot_list_beats({"nope": 1}, range_start=0.0, range_end=6.0, max_beats=24) is None
    # Fewer than two usable beats (missing visual_prompt kills the second).
    raw = [
        {"start": 0, "end": 3, "text": "أ", "visual_prompt": "desk with laptop"},
        {"start": 3, "end": 6, "text": "ب", "visual_prompt": ""},
    ]
    assert validate_shot_list_beats(raw, range_start=0.0, range_end=6.0, max_beats=24) is None
    # Range too short to hold two beats.
    raw = [
        {"start": 0, "end": 0.4, "text": "أ", "visual_prompt": "x"},
        {"start": 0.4, "end": 0.8, "text": "ب", "visual_prompt": "y"},
    ]
    assert validate_shot_list_beats(raw, range_start=0.0, range_end=0.8, max_beats=24) is None


def test_validate_beats_merges_tail_beyond_max_beats():
    raw = [
        {"start": float(i), "end": float(i + 1), "text": f"بيت {i}", "visual_prompt": f"scene {i}"}
        for i in range(6)
    ]

    beats = validate_shot_list_beats(raw, range_start=0.0, range_end=6.0, max_beats=4)

    assert beats is not None
    assert len(beats) == 4
    assert beats[-1]["end"] == 6.0
    # The tail beats' words are merged, not dropped.
    assert "بيت 3" in beats[-1]["text"] and "بيت 5" in beats[-1]["text"]


def test_validate_beats_folds_degenerate_windows_into_neighbours():
    raw = [
        {"start": 0.0, "end": 2.0, "text": "أول", "visual_prompt": "storefront exterior"},
        # Fully swallowed by the first beat after tiling repair.
        {"start": 1.8, "end": 2.1, "text": "ثاني", "visual_prompt": "coffee cup on desk"},
        {"start": 2.1, "end": 5.0, "text": "ثالث", "visual_prompt": "delivery van on a road"},
    ]

    beats = validate_shot_list_beats(raw, range_start=0.0, range_end=5.0, max_beats=24)

    assert beats is not None
    assert len(beats) == 2
    assert beats[0]["end"] == beats[1]["start"]
    assert "ثاني" in beats[1]["text"] and "ثالث" in beats[1]["text"]
    assert beats[-1]["end"] == 5.0


@pytest.mark.asyncio
async def test_generate_shot_list_parses_llm_beats(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    captured: dict = {}

    async def fake_call_claude(**kwargs):
        captured.update(kwargs)
        return """```json
{"beats": [
  {"start": 0.0, "end": 2.2, "text": "بدك تسويق حقيقي", "beat_type": "narrative",
   "visual_prompt": "modern marketing office desk with glowing analytics charts", "keyword": "تسويق", "prefer": "video"},
  {"start": 2.2, "end": 3.2, "text": "استشارة", "beat_type": "enumeration",
   "visual_prompt": "open laptop on a desk showing a video call interface", "keyword": "استشارة", "prefer": "image"},
  {"start": 3.2, "end": 5.8, "text": "احجز هلق", "beat_type": "cta",
   "visual_prompt": "smartphone on a stand with a glowing booking button shape", "keyword": "احجز", "prefer": "image"}
]}
```"""

    monkeypatch.setattr(montage_shot_list, "call_claude", lambda **kwargs: fake_call_claude(**kwargs))

    beats = await generate_shot_list(
        [
            {"start": 0.0, "end": 3.0, "text": "بدك تسويق حقيقي استشارة"},
            {"start": 3.0, "end": 5.8, "text": "احجز هلق"},
        ],
        suite=make_suite(),
        notes="بدي فيديو سريع",
    )

    assert beats is not None
    assert [beat["beat_type"] for beat in beats] == ["narrative", "enumeration", "cta"]
    assert beats[0]["start"] == 0.0
    assert beats[-1]["end"] == 5.8
    assert beats[1]["visual_prompt"].startswith("open laptop")
    assert captured["model"] == settings.anthropic_fast_model
    assert "visual_prompt" in captured["system"]


@pytest.mark.asyncio
async def test_generate_shot_list_returns_none_when_llm_fails(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def broken_call_claude(**_kwargs):
        raise RuntimeError("anthropic is down")

    monkeypatch.setattr(montage_shot_list, "call_claude", lambda **kwargs: broken_call_claude(**kwargs))

    beats = await generate_shot_list(
        [{"start": 0.0, "end": 6.0, "text": "نص الفيديو"}],
        suite=make_suite(),
    )

    assert beats is None


@pytest.mark.asyncio
async def test_generate_shot_list_returns_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def prose_call_claude(**_kwargs):
        return "Sure! Here is a nice shot list for your video."

    monkeypatch.setattr(montage_shot_list, "call_claude", lambda **kwargs: prose_call_claude(**kwargs))

    beats = await generate_shot_list(
        [{"start": 0.0, "end": 6.0, "text": "نص الفيديو"}],
        suite=make_suite(),
    )

    assert beats is None


@pytest.mark.asyncio
async def test_generate_shot_list_skips_without_api_key_or_transcript(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert await generate_shot_list([{"start": 0.0, "end": 6.0, "text": "نص"}], suite=make_suite()) is None

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def must_not_be_called(**_kwargs):  # pragma: no cover - guard
        raise AssertionError("LLM must not be called without a transcript")

    monkeypatch.setattr(montage_shot_list, "call_claude", lambda **kwargs: must_not_be_called(**kwargs))
    assert await generate_shot_list([], suite=make_suite()) is None
