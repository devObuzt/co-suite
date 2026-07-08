"""User-uploaded montage backgrounds: vocabulary, analysis parsing, priority, modes."""
import json

from api.models.admin import CreativeAsset
from api.services import user_backgrounds
from api.services.creative_assets import (
    filter_assets_for_backgrounds_mode,
    has_user_background_match,
    pick_asset,
)
from api.services.user_backgrounds import (
    BACKGROUND_TAG_VOCAB,
    analyze_image_background,
    merge_vocab_tags,
    normalize_analysis_payload,
    normalize_analysis_tags,
    parse_analysis_json,
)
from api.services.video_montage import resolve_backgrounds_mode


def make_asset(
    *,
    kind: str = "visual_image",
    tags: list[str] | None = None,
    suite_id: str | None = None,
    user_uploaded: bool = False,
    asset_id: str = "asset-1",
) -> CreativeAsset:
    metadata: dict = {}
    if suite_id:
        metadata["suite_id"] = suite_id
    if user_uploaded:
        metadata["user_uploaded"] = True
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
        active=True,
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


def test_user_only_mode_restricts_visuals_and_disables_generation():
    suite_id = "suite-1"
    user_image = make_asset(asset_id="user-img", suite_id=suite_id, user_uploaded=True)
    generated = make_asset(asset_id="generated", suite_id=suite_id)
    library_video = make_asset(asset_id="lib-video", kind="visual_video")
    music = make_asset(asset_id="music", kind="music")

    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [user_image, generated, library_video, music], mode="user_only", suite_id=suite_id
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


def test_blend_mode_keeps_everything_and_allows_generation():
    suite_id = "suite-1"
    user_image = make_asset(asset_id="user-img", suite_id=suite_id, user_uploaded=True)
    library_video = make_asset(asset_id="lib-video", kind="visual_video")
    filtered, allow_generation = filter_assets_for_backgrounds_mode(
        [user_image, library_video], mode="blend", suite_id=suite_id
    )
    assert allow_generation is True
    assert filtered == [user_image, library_video]


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
