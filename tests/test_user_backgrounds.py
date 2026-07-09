"""User-uploaded montage backgrounds: vocabulary, analysis parsing, priority, modes."""
import json

import pytest
from fastapi import HTTPException

from api.models.admin import CreativeAsset
from api.routers.video_montage import keep_valid_background_assets, parse_background_asset_ids
from api.services import user_backgrounds
from api.services.creative_assets import (
    filter_assets_for_backgrounds_mode,
    has_user_background_match,
    is_asset_unusable_for_background,
    pick_asset,
    user_background_matches_scene,
)
from api.services.user_backgrounds import (
    BACKGROUND_TAG_VOCAB,
    analyze_image_background,
    merge_vocab_tags,
    normalize_analysis_payload,
    normalize_analysis_tags,
    parse_analysis_json,
)
from api.services.video_montage import resolve_backgrounds_mode, selected_background_asset_ids


def make_asset(
    *,
    kind: str = "visual_image",
    tags: list[str] | None = None,
    suite_id: str | None = None,
    user_uploaded: bool = False,
    asset_id: str = "asset-1",
    analysis: dict | None = None,
    active: bool = True,
) -> CreativeAsset:
    metadata: dict = {}
    if suite_id:
        metadata["suite_id"] = suite_id
    if user_uploaded:
        metadata["user_uploaded"] = True
    if analysis is not None:
        metadata["analysis"] = analysis
    return CreativeAsset(
        id=asset_id,
        kind=kind,
        title=asset_id,
        storage_url=f"https://cdn.example/{asset_id}.png",
        tags=tags or [],
        use_cases=[],
        metadata_json=metadata,
        usage_count=0,
        last_used_at=None,
        active=active,
    )


# --- Vocabulary / tag merge ---------------------------------------------------


def test_vocabulary_has_around_forty_entries_with_arabic_and_hebrew_synonyms():
    assert len(BACKGROUND_TAG_VOCAB) >= 40
    for tag, entry in BACKGROUND_TAG_VOCAB.items():
        assert entry.get("ar"), f"{tag} is missing arabic synonyms"
        assert entry.get("he"), f"{tag} is missing hebrew synonyms"


def test_normalize_analysis_tags_filters_to_vocabulary_and_dedupes():
    raw = ["Coffee", "coffee", "REAL ESTATE", "spaceship", "  nature ", 42]
    assert normalize_analysis_tags(raw) == ["coffee", "real_estate", "nature"]


def test_merge_vocab_tags_adds_arabic_and_hebrew_synonyms():
    merged = merge_vocab_tags(["coffee", "nature"])
    assert "coffee" in merged
    assert "قهوة" in merged  # arabic transcript matching
    assert "קפה" in merged  # hebrew transcript matching
    assert "طبيعة" in merged
    assert len(merged) == len(set(merged))


def test_merge_vocab_tags_drops_unknown_tags():
    assert merge_vocab_tags(["spaceship", "unicorn"]) == []


# --- Analysis JSON parsing ----------------------------------------------------


def test_parse_analysis_json_accepts_fenced_markdown_reply():
    reply = "Sure! Here it is:\n```json\n{\"description\": \"a cafe\", \"tags\": [\"coffee\"]}\n```"
    assert parse_analysis_json(reply) == {"description": "a cafe", "tags": ["coffee"]}


def test_parse_analysis_json_rejects_garbage():
    assert parse_analysis_json("no json here") is None
    assert parse_analysis_json("") is None
    assert parse_analysis_json("[1, 2]") is None


def test_normalize_analysis_payload_coerces_types_and_filters_tags():
    payload = normalize_analysis_payload(
        {
            "description": "Latte art on a wooden table",
            "tags": ["coffee", "Food", "spaceship"],
            "dominant_colors": ["#8B5A2B", "#F5F0E8"],
            "has_people": "yes",
            "has_text": 0,
            "motion": "slow pan",
        }
    )
    assert payload == {
        "description": "Latte art on a wooden table",
        "tags": ["coffee", "food"],
        "dominant_colors": ["#8B5A2B", "#F5F0E8"],
        "has_people": True,
        "has_text": False,
        "motion": "slow pan",
    }


def test_analyze_image_background_parses_faked_gemini_response(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "description": "A modern office desk",
                                            "tags": ["office", "tech"],
                                            "dominant_colors": ["#222222"],
                                            "has_people": False,
                                            "has_text": False,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(user_backgrounds.settings, "google_api_key", "test-key")
    monkeypatch.setattr(user_backgrounds.httpx, "post", fake_post)

    analysis = analyze_image_background(b"fake-image", "image/jpeg", suite_id="suite-1")

    assert analysis is not None
    assert analysis["tags"] == ["office", "tech"]
    assert analysis["description"] == "A modern office desk"
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    parts = captured["body"]["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"


def test_analyze_image_background_returns_none_on_provider_error(monkeypatch):
    def fake_post(url, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(user_backgrounds.settings, "google_api_key", "test-key")
    monkeypatch.setattr(user_backgrounds.httpx, "post", fake_post)

    assert analyze_image_background(b"fake-image", "image/jpeg") is None


# --- pick_asset priority ------------------------------------------------------


def test_pick_asset_prefers_user_upload_over_generated_and_library():
    suite_id = "suite-1"
    library = make_asset(asset_id="library", tags=["business"])
    generated = make_asset(asset_id="generated", suite_id=suite_id)
    user = make_asset(asset_id="user", suite_id=suite_id, user_uploaded=True)

    picked = pick_asset(
        [library, generated, user],
        kind="visual_image",
        scene_text="أهلا فيكم بالمقهى",
        suite_id=suite_id,
        variety_seed=0,
    )
    assert picked is not None and picked.id == "user"


def test_pick_asset_still_penalizes_foreign_suite_user_uploads():
    foreign_user = make_asset(asset_id="foreign", suite_id="other-suite", user_uploaded=True)
    library = make_asset(asset_id="library", tags=["business"])

    picked = pick_asset(
        [foreign_user, library],
        kind="visual_image",
        scene_text="any scene",
        suite_id="suite-1",
        variety_seed=0,
    )
    assert picked is not None and picked.id == "library"


# --- backgrounds_mode ---------------------------------------------------------


def test_resolve_backgrounds_mode_defaults_and_validates():
    assert resolve_backgrounds_mode({}) == "blend"
    assert resolve_backgrounds_mode({"backgrounds_mode": "user_only"}) == "user_only"
    assert resolve_backgrounds_mode({"backgrounds_mode": "USER_ONLY "}) == "user_only"
    assert resolve_backgrounds_mode({"backgrounds_mode": "nonsense"}) == "blend"


def test_user_only_mode_restricts_visuals_to_selected_and_disables_generation():
    suite_id = "suite-1"
    user_image = make_asset(asset_id="user-img", suite_id=suite_id, user_uploaded=True)
    generated = make_asset(asset_id="generated", suite_id=suite_id)
    library_video = make_asset(asset_id="lib-video", kind="visual_video")
    music = make_asset(asset_id="music", kind="music")

    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [user_image, generated, library_video, music],
        mode="user_only",
        suite_id=suite_id,
        selected_ids=["user-img"],
    )

    assert allow_generation is False
    ids = {asset.id for asset in filtered}
    assert ids == {"user-img", "music"}  # audio assets pass through untouched


def test_user_only_mode_falls_back_to_blend_without_user_uploads():
    generated = make_asset(asset_id="generated", suite_id="suite-1")
    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [generated], mode="user_only", suite_id="suite-1"
    )
    assert allow_generation is True
    assert filtered == [generated]


def test_blend_mode_keeps_selected_uploads_and_allows_generation():
    suite_id = "suite-1"
    user_image = make_asset(asset_id="user-img", suite_id=suite_id, user_uploaded=True)
    library_video = make_asset(asset_id="lib-video", kind="visual_video")
    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [user_image, library_video], mode="blend", suite_id=suite_id, selected_ids=["user-img"]
    )
    assert allow_generation is True
    assert filtered == [user_image, library_video]


# --- Per-job selection: uploads are a library, only selected ids participate ---


def test_only_selected_user_uploads_participate_in_blend():
    suite_id = "suite-1"
    selected = make_asset(asset_id="selected", suite_id=suite_id, user_uploaded=True)
    unselected = make_asset(asset_id="unselected", suite_id=suite_id, user_uploaded=True)
    library = make_asset(asset_id="library", kind="visual_video")

    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [selected, unselected, library], mode="blend", suite_id=suite_id, selected_ids=["selected"]
    )
    assert allow_generation is True
    assert {asset.id for asset in filtered} == {"selected", "library"}


def test_empty_selection_excludes_all_user_uploads_in_every_mode():
    suite_id = "suite-1"
    user_a = make_asset(asset_id="user-a", suite_id=suite_id, user_uploaded=True)
    user_b = make_asset(asset_id="user-b", kind="visual_video", suite_id=suite_id, user_uploaded=True)
    generated = make_asset(asset_id="generated", suite_id=suite_id)
    music = make_asset(asset_id="music", kind="music")

    for mode in ("blend", "user_only"):
        for selection in (None, []):
            filtered, allow_generation = filter_assets_for_backgrounds_mode(
                [user_a, user_b, generated, music], mode=mode, suite_id=suite_id, selected_ids=selection
            )
            assert allow_generation is True, f"mode={mode} selection={selection} must fall back to generated"
            assert {asset.id for asset in filtered} == {"generated", "music"}


def test_user_only_with_selection_of_unusable_upload_falls_back_to_generated():
    suite_id = "suite-1"
    screen = make_asset(
        asset_id="screen",
        suite_id=suite_id,
        user_uploaded=True,
        analysis={"description": "screenshot of a website", "tags": [], "has_text": False},
    )
    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [screen], mode="user_only", suite_id=suite_id, selected_ids=["screen"]
    )
    assert allow_generation is True
    assert filtered == []


def test_selected_background_asset_ids_parses_job_input():
    assert selected_background_asset_ids({}) == []
    assert selected_background_asset_ids({"background_asset_ids": None}) == []
    assert selected_background_asset_ids({"background_asset_ids": "not-a-list"}) == []
    assert selected_background_asset_ids({"background_asset_ids": ["a", "b", "a", " ", 3]}) == ["a", "b", "3"]
    many = [f"id-{index}" for index in range(30)]
    assert len(selected_background_asset_ids({"background_asset_ids": many})) == 20


# --- Router: selection parsing + validation helpers ----------------------------


def test_parse_background_asset_ids_accepts_json_list_and_dedupes():
    assert parse_background_asset_ids(None) == []
    assert parse_background_asset_ids("") == []
    assert parse_background_asset_ids("[]") == []
    assert parse_background_asset_ids('["a", " b ", "a", ""]') == ["a", "b"]
    many = json.dumps([f"id-{index}" for index in range(30)])
    assert len(parse_background_asset_ids(many)) == 20


def test_parse_background_asset_ids_rejects_bad_payloads():
    with pytest.raises(HTTPException):
        parse_background_asset_ids("{not json")
    with pytest.raises(HTTPException):
        parse_background_asset_ids('{"a": 1}')


def test_keep_valid_background_assets_silently_drops_invalid_ids():
    suite_id = "suite-1"
    valid = make_asset(asset_id="valid", suite_id=suite_id, user_uploaded=True)
    valid_video = make_asset(asset_id="valid-video", kind="visual_video", suite_id=suite_id, user_uploaded=True)
    inactive = make_asset(asset_id="inactive", suite_id=suite_id, user_uploaded=True, active=False)
    foreign = make_asset(asset_id="foreign", suite_id="other-suite", user_uploaded=True)
    generated = make_asset(asset_id="generated", suite_id=suite_id)  # not user_uploaded
    music = make_asset(asset_id="music", kind="music", suite_id=suite_id, user_uploaded=True)

    requested = ["valid", "missing", "inactive", "foreign", "generated", "music", "valid-video"]
    rows = [valid, valid_video, inactive, foreign, generated, music]
    assert keep_valid_background_assets(requested, rows, suite_id=suite_id) == ["valid", "valid-video"]


def test_has_user_background_match_gates_hero_generation():
    suite_id = "suite-1"
    user = make_asset(asset_id="user", suite_id=suite_id, user_uploaded=True, tags=["coffee", "قهوة"])
    generated = make_asset(asset_id="generated", suite_id=suite_id)

    # A same-suite user upload comfortably beats the minimal-match floor.
    assert has_user_background_match([user, generated], scene_text="أفضل قهوة بالبلد", suite_id=suite_id)
    # Suite-generated assets alone must NOT block hero generation.
    assert not has_user_background_match([generated], scene_text="أفضل قهوة بالبلد", suite_id=suite_id)
    # Foreign-suite uploads never count for this suite.
    foreign = make_asset(asset_id="foreign", suite_id="other", user_uploaded=True)
    assert not has_user_background_match([foreign], scene_text="أي مشهد", suite_id=suite_id)


# --- FIX A: cross-suite hard exclusion + no negative scores in rotation --------


def test_filter_hard_excludes_foreign_suite_user_uploads_in_every_mode():
    suite_id = "suite-1"
    foreign_user = make_asset(asset_id="foreign", suite_id="other-suite", user_uploaded=True)
    own_user = make_asset(asset_id="own", suite_id=suite_id, user_uploaded=True)
    library = make_asset(asset_id="library", tags=["business"])
    music = make_asset(asset_id="music", kind="music")

    for mode in ("blend", "user_only"):
        filtered, _ = filter_assets_for_backgrounds_mode(
            [foreign_user, own_user, library, music],
            mode=mode,
            suite_id=suite_id,
            selected_ids=["foreign", "own"],
        )
        ids = {asset.id for asset in filtered}
        assert "foreign" not in ids, f"foreign upload leaked through mode={mode}"
        assert "own" in ids
        assert "music" in ids


def test_filter_excludes_unattributed_user_uploads():
    # A user upload without suite metadata can't be proven to belong here,
    # even when a job explicitly selects it.
    orphan_user = make_asset(asset_id="orphan", user_uploaded=True)
    filtered, _ = filter_assets_for_backgrounds_mode(
        [orphan_user], mode="blend", suite_id="suite-1", selected_ids=["orphan"]
    )
    assert filtered == []


def test_pick_asset_never_returns_negative_score_visuals():
    # A foreign suite's generated background scores deeply negative (-20);
    # it must never surface — not even via the variety rotation pool.
    foreign_generated = make_asset(asset_id="foreign-gen", kind="visual_video", suite_id="other-suite")
    library = make_asset(asset_id="library", kind="visual_video")

    for seed in range(6):
        picked = pick_asset(
            [foreign_generated, library],
            kind="visual_video",
            scene_text="any scene",
            suite_id="suite-1",
            variety_seed=seed,
        )
        assert picked is not None and picked.id == "library"

    # When every candidate is negative there is no usable pick at all.
    assert (
        pick_asset([foreign_generated], kind="visual_video", scene_text="any", suite_id="suite-1", variety_seed=0)
        is None
    )


# --- FIX C: blend-mode quality gate + screen-recording exclusion ---------------


def test_is_asset_unusable_for_background_flags_text_and_screen_recordings():
    has_text = make_asset(
        asset_id="text",
        suite_id="suite-1",
        user_uploaded=True,
        analysis={"description": "A poster", "tags": [], "has_text": True},
    )
    screen = make_asset(
        asset_id="screen",
        suite_id="suite-1",
        user_uploaded=True,
        analysis={"description": "Screen recording of an app dashboard", "tags": [], "has_text": False},
    )
    clean = make_asset(
        asset_id="clean",
        suite_id="suite-1",
        user_uploaded=True,
        tags=["mountain", "جبل"],
        analysis={"description": "A mountain landscape at sunset", "tags": ["mountain"], "has_text": False},
    )
    assert is_asset_unusable_for_background(has_text)
    assert is_asset_unusable_for_background(screen)
    assert not is_asset_unusable_for_background(clean)


def test_filter_quality_excludes_screen_recording_uploads_even_in_user_only():
    suite_id = "suite-1"
    screen = make_asset(
        asset_id="screen",
        suite_id=suite_id,
        user_uploaded=True,
        analysis={"description": "screenshot of a website", "tags": [], "has_text": False},
    )
    clean = make_asset(asset_id="clean", suite_id=suite_id, user_uploaded=True, tags=["nature"])

    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [screen, clean], mode="user_only", suite_id=suite_id, selected_ids=["screen", "clean"]
    )
    assert allow_generation is False
    assert {asset.id for asset in filtered} == {"clean"}

    # When ALL selected uploads are unusable, user_only falls back to generation.
    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [screen], mode="user_only", suite_id=suite_id, selected_ids=["screen"]
    )
    assert allow_generation is True
    assert filtered == []


def test_user_background_matches_scene_requires_real_tag_match():
    suite_id = "suite-1"
    # Fresh upload: flat kind+suite+user bonuses clear the score floor,
    # but with no tag match it still must NOT win a scene.
    unrelated = make_asset(asset_id="unrelated", suite_id=suite_id, user_uploaded=True, tags=["mountain", "جبل"])
    assert not user_background_matches_scene(unrelated, "أفضل قهوة بالبلد", suite_id)
    assert user_background_matches_scene(unrelated, "رحلة إلى الجبل الأخضر", suite_id)
    # has_text/screen uploads never match, regardless of tags.
    texty = make_asset(
        asset_id="texty",
        suite_id=suite_id,
        user_uploaded=True,
        tags=["mountain", "جبل"],
        analysis={"description": "mountain", "tags": ["mountain"], "has_text": True},
    )
    assert not user_background_matches_scene(texty, "رحلة إلى الجبل", suite_id)


def test_has_user_background_match_ignores_bonus_only_uploads():
    suite_id = "suite-1"
    unrelated = make_asset(asset_id="unrelated", suite_id=suite_id, user_uploaded=True, tags=["mountain"])
    # Bonuses alone (18+) used to clear the floor and block hero generation.
    assert not has_user_background_match([unrelated], scene_text="أفضل قهوة بالبلد", suite_id=suite_id)


def test_pick_asset_blend_gate_demotes_unmatched_user_uploads():
    suite_id = "suite-1"
    user = make_asset(asset_id="user", suite_id=suite_id, user_uploaded=True, tags=["mountain", "جبل"])
    generated = make_asset(asset_id="generated", suite_id=suite_id)

    # Blend: unmatched user upload loses the scene to suite-generated media.
    picked = pick_asset(
        [user, generated],
        kind="visual_image",
        scene_text="عرض خاص على القهوة",
        suite_id=suite_id,
        variety_seed=0,
        user_match_required=True,
    )
    assert picked is not None and picked.id == "generated"

    # Blend: a real match restores the user upload's priority.
    picked = pick_asset(
        [user, generated],
        kind="visual_image",
        scene_text="رحلة إلى الجبل",
        suite_id=suite_id,
        variety_seed=0,
        user_match_required=True,
    )
    assert picked is not None and picked.id == "user"

    # user_only keeps absolute priority: no scene-match gate.
    picked = pick_asset(
        [user, generated],
        kind="visual_image",
        scene_text="عرض خاص على القهوة",
        suite_id=suite_id,
        variety_seed=0,
        user_match_required=False,
    )
    assert picked is not None and picked.id == "user"
