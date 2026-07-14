"""Unit tests for the OneShare Magic per-scene director (pure functions)."""
from api.services.montage_magic_director import (
    apply_camera_restraint,
    heuristic_magic_direction,
    montage_template,
    validate_magic_directions,
)


def _beats(count: int) -> list[dict]:
    return [
        {
            "start": float(index),
            "end": float(index + 1),
            "text": f"beat {index}",
            "beat_type": "enumeration" if 0 < index < count - 1 else "narrative",
            "keyword": f"كلمة{index}",
            "visual_prompt": "an office desk",
        }
        for index in range(count)
    ]


def test_montage_template_defaults_unknown_values():
    assert montage_template({}) == "default"
    assert montage_template({"template": "OneShare_Magic"}) == "oneshare_magic"
    assert montage_template({"template": "fancy_new"}) == "default"
    assert montage_template({"template": None}) == "default"


def test_heuristic_hook_and_close():
    beats = _beats(4)
    first = heuristic_magic_direction(index=0, beat=beats[0], scene_count=4)
    assert first["layout"] == "split"
    assert first["camera"] == "zoom_in"
    last = heuristic_magic_direction(index=3, beat=beats[3], scene_count=4)
    assert last["background"] == "solid"
    assert last["camera"] == "zoom_out"
    middle = heuristic_magic_direction(index=1, beat=beats[1], scene_count=4)
    assert middle["background"] == "video"
    assert middle["camera"] == "punch_in"
    assert middle["title"] == "كلمة1"


def test_validate_fills_missing_beats_with_heuristics():
    beats = _beats(3)
    raw = [
        {
            "index": 1,
            "layout": "full",
            "background": "video",
            "title": "تسويق رقمي",
            "subtitle": "كل شي بمكان واحد",
            "icons": ["📣", "logo", "🎯"],
            "emphasis": "OneShare",
            "camera": "punch_in",
            "sfx": "camera",
        }
    ]
    directions, llm_count = validate_magic_directions(raw, beats)
    assert len(directions) == 3
    assert llm_count == 1
    assert directions[1]["title"] == "تسويق رقمي"
    # Alphanumeric tokens are not icons.
    assert directions[1]["icons"] == ["📣", "🎯"]
    assert directions[1]["sfx"] == "camera"
    # Unstaged beats fall back to the heuristic grammar.
    assert directions[0]["layout"] == "split"
    assert directions[2]["camera"] == "zoom_out"


def test_validate_rejects_bad_enums_and_long_titles():
    beats = _beats(2)
    raw = [
        {
            "index": 0,
            "layout": "diagonal",
            "background": "hologram",
            "title": "عنوان طويل جدا من خمس كلمات كاملة، مع فاصلة!",
            "camera": "dolly",
            "sfx": "airhorn",
        },
        {"index": 5, "layout": "full"},
    ]
    directions, llm_count = validate_magic_directions(raw, beats)
    assert llm_count == 1
    hook = heuristic_magic_direction(index=0, beat=beats[0], scene_count=2)
    assert directions[0]["layout"] == hook["layout"]
    assert directions[0]["background"] == hook["background"]
    assert directions[0]["camera"] == hook["camera"]
    assert directions[0]["sfx"] is None
    # Punctuation stripped, capped at 4 words.
    assert len(directions[0]["title"].split()) == 4
    assert "!" not in directions[0]["title"]


def test_icon_keywords_and_emoji_mix():
    beats = _beats(1)
    raw = [
        {
            "index": 0,
            "icons": ["Instagram", "phone", "🧩", "not-an-icon", "email", "location"],
        }
    ]
    directions, _ = validate_magic_directions(raw, beats)
    assert directions[0]["icons"] == ["instagram", "phone", "🧩", "email"]


def test_new_camera_vocabulary_accepted():
    beats = _beats(3)
    raw = [
        {"index": 0, "camera": "zoom_in_out"},
        {"index": 1, "camera": "triple_punch"},
        {"index": 2, "camera": "punch_in"},
    ]
    directions, _ = validate_magic_directions(raw, beats)
    assert directions[0]["camera"] == "zoom_in_out"
    assert directions[1]["camera"] == "triple_punch"


def test_camera_restraint_no_consecutive_moves_and_budget():
    directions = [{"camera": camera} for camera in
                  ["zoom_in", "punch_in", "triple_punch", "punch_in", "zoom_out", "punch_in"]]
    apply_camera_restraint(directions)
    cameras = [d["camera"] for d in directions]
    # Never two moves in a row.
    for left, right in zip(cameras, cameras[1:]):
        assert not (left != "none" and right != "none")
    # Budget: at most half the scenes move.
    assert sum(1 for c in cameras if c != "none") <= 3
    # The first move survives untouched.
    assert cameras[0] == "zoom_in"


def test_camera_restraint_demotes_second_triple_punch():
    directions = [{"camera": c} for c in ["triple_punch", "none", "triple_punch", "none", "none", "none"]]
    apply_camera_restraint(directions)
    assert directions[0]["camera"] == "triple_punch"
    assert directions[2]["camera"] == "punch_in"


def test_heuristic_cta_contact_icons():
    beat = {"beat_type": "cta", "keyword": "تواصلوا", "text": "تواصلوا معنا اليوم"}
    direction = heuristic_magic_direction(index=3, beat=beat, scene_count=4)
    assert direction["icons"] == ["phone", "email", "location"]


def test_validate_handles_garbage_payloads():
    beats = _beats(2)
    for garbage in (None, "nope", 42, [{"index": "x"}], [None, []]):
        directions, _ = validate_magic_directions(garbage, beats)
        assert len(directions) == 2
        assert all(d["layout"] in {"split", "full"} for d in directions)
        assert all(d["camera"] in {"zoom_in", "zoom_out", "punch_in", "none"} for d in directions)
