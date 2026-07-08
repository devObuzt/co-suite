import pytest

from api.services import montage_notes_analyzer
from api.services.montage_notes_analyzer import (
    analyze_and_apply_montage_notes,
    analyze_montage_notes,
    apply_notes_directives,
)


def test_apply_notes_directives_user_text_forces_music_off():
    # "بدون موسيقى" must win over the music toggle being on.
    input_data = {"options": ["captions", "music", "titles"], "notes": "بدون موسيقى نهائيا"}
    directives = [
        {
            "request": "بدون موسيقى نهائيا",
            "supported": True,
            "action": {"type": "set_option", "option": "music", "enabled": False},
            "detail": "رح ننزع الموسيقى والمؤثرات.",
        }
    ]

    effective, analysis = apply_notes_directives(input_data, directives)

    assert "music" not in effective["options"]
    assert set(effective["options"]) == {"captions", "titles"}
    assert analysis["honored"] == [
        {"request": "بدون موسيقى نهائيا", "detail": "رح ننزع الموسيقى والمؤثرات."}
    ]
    assert analysis["unsupported"] == []
    # The original input must not be mutated.
    assert "music" in input_data["options"]


def test_apply_notes_directives_reports_unsupported_requests():
    directives = [
        {
            "request": "غيّر الخط لكوفي",
            "supported": False,
            "action": {"type": "none"},
            "detail": "تغيير نوع الخط غير مدعوم حاليًا.",
        },
        {
            "request": "فعّل خيار غير موجود",
            "supported": True,
            "action": {"type": "set_option", "option": "hologram", "enabled": True},
            "detail": "خيار غير معروف.",
        },
    ]

    effective, analysis = apply_notes_directives({"options": []}, directives)

    assert analysis["honored"] == []
    assert [item["request"] for item in analysis["unsupported"]] == [
        "غيّر الخط لكوفي",
        "فعّل خيار غير موجود",
    ]
    assert effective["options"] == []


def test_apply_notes_directives_zoom_offsets_mood_and_caption_style():
    directives = [
        {"request": "زوم أكثر", "supported": True, "action": {"type": "set_zoom", "value": 9}, "detail": "زوم للحد الأقصى."},
        {"request": "حرك الشخص يمين", "supported": True, "action": {"type": "set_offset", "x": 120, "y": -5}, "detail": "تحريك."},
        {"request": "موسيقى هادئة", "supported": True, "action": {"type": "music_mood", "mood": "هادئة"}, "detail": "مود هادي."},
        {"request": "خلي الكابتشن كبير", "supported": True, "action": {"type": "caption_style", "style": "large"}, "detail": "كابتشن أكبر."},
    ]

    effective, analysis = apply_notes_directives({"options": ["music"], "zoom": 1}, directives)

    assert effective["zoom"] == 3.0
    assert effective["subject_offset_x"] == 40.0
    assert effective["subject_offset_y"] == -5.0
    assert effective["music_mood"] == "هادئة"
    assert effective["caption_style"] == "large"
    assert len(analysis["honored"]) == 4
    assert analysis["unsupported"] == []


def test_apply_notes_directives_enables_option_from_text():
    directives = [
        {
            "request": "ضيف كابتشن",
            "supported": True,
            "action": {"type": "set_option", "option": "captions", "enabled": True},
            "detail": "رح نضيف كابتشن.",
        }
    ]

    effective, _analysis = apply_notes_directives({"options": []}, directives)

    assert effective["options"] == ["captions"]


@pytest.mark.asyncio
async def test_analyze_montage_notes_parses_fenced_json(monkeypatch):
    async def fake_call_claude(**_kwargs):
        return (
            "```json\n"
            '{"directives": [{"request": "بدون موسيقى", "supported": true,'
            ' "action": {"type": "set_option", "option": "music", "enabled": false},'
            ' "detail": "تمام"}]}\n```'
        )

    monkeypatch.setattr(montage_notes_analyzer, "call_claude", fake_call_claude)
    monkeypatch.setattr(montage_notes_analyzer.settings, "anthropic_api_key", "test-key")

    directives = await analyze_montage_notes("بدون موسيقى")

    assert directives is not None
    assert directives[0]["action"]["option"] == "music"


@pytest.mark.asyncio
async def test_analyze_montage_notes_survives_llm_failure(monkeypatch):
    async def broken_call_claude(**_kwargs):
        raise RuntimeError("anthropic is down")

    monkeypatch.setattr(montage_notes_analyzer, "call_claude", broken_call_claude)
    monkeypatch.setattr(montage_notes_analyzer.settings, "anthropic_api_key", "test-key")

    assert await analyze_montage_notes("بدون موسيقى") is None


@pytest.mark.asyncio
async def test_analyze_and_apply_montage_notes_returns_effective_input(monkeypatch):
    async def fake_analyze(_notes):
        return [
            {
                "request": "بدون موسيقى",
                "supported": True,
                "action": {"type": "set_option", "option": "music", "enabled": False},
                "detail": "رح ننزع الموسيقى.",
            },
            {
                "request": "ضيف مؤثرات ليزر",
                "supported": False,
                "action": {"type": "none"},
                "detail": "مؤثرات الليزر غير مدعومة.",
            },
        ]

    monkeypatch.setattr(montage_notes_analyzer, "analyze_montage_notes", fake_analyze)

    effective, analysis = await analyze_and_apply_montage_notes(
        job_id="job-1",
        suite_id="suite-1",
        input_data={"options": ["music", "captions"], "notes": "بدون موسيقى وضيف مؤثرات ليزر"},
    )

    assert "music" not in effective["options"]
    assert analysis is not None
    assert [item["request"] for item in analysis["honored"]] == ["بدون موسيقى"]
    assert [item["request"] for item in analysis["unsupported"]] == ["ضيف مؤثرات ليزر"]


@pytest.mark.asyncio
async def test_analyze_and_apply_montage_notes_skips_gracefully_on_failure(monkeypatch):
    async def fake_analyze(_notes):
        return None

    monkeypatch.setattr(montage_notes_analyzer, "analyze_montage_notes", fake_analyze)

    input_data = {"options": ["music"], "notes": "بدون موسيقى"}
    effective, analysis = await analyze_and_apply_montage_notes(
        job_id="job-1",
        suite_id="suite-1",
        input_data=input_data,
    )

    assert effective is input_data
    assert analysis is None


@pytest.mark.asyncio
async def test_analyze_and_apply_montage_notes_noop_without_notes():
    input_data = {"options": ["music"], "notes": "  "}
    effective, analysis = await analyze_and_apply_montage_notes(
        job_id="job-1",
        suite_id="suite-1",
        input_data=input_data,
    )

    assert effective is input_data
    assert analysis is None
