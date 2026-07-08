from decimal import Decimal

from api.models.media_asset import MediaAsset
from api.models.suite import Suite
from api.services.media_library import (
    MONTAGE_TALKING_HEAD_LIBRARY,
    build_media_tree,
    library_label,
    montage_media_asset,
    serialize_media_asset,
)


def make_suite() -> Suite:
    return Suite(id="suite_1", owner_id="user_1", name="متجر الياسمين", slug="jasmine-store")


def rendered_montage_result(**overrides) -> dict:
    result = {
        "rendered": True,
        "output_url": "https://media.example.com/video_montage/job_1/final.mp4",
        "video_montage": {"render": {"rendered": True, "duration_seconds": 32.5}},
    }
    result.update(overrides)
    return result


def test_library_label_maps_montage_talking_head_to_arabic():
    assert library_label("montage_talking_head") == "مونتاج — شخصية أمام الكاميرا"
    assert library_label("unknown_library") == "unknown_library"


def test_build_media_tree_groups_by_library_year_month_newest_first():
    rows = [
        ("montage_talking_head", 2026, 6, 1),
        ("montage_talking_head", 2026, 7, 3),
        ("montage_talking_head", 2025, 12, 2),
    ]

    tree = build_media_tree(rows)

    assert len(tree) == 1
    library = tree[0]
    assert library["key"] == "montage_talking_head"
    assert library["label"] == "مونتاج — شخصية أمام الكاميرا"
    assert [year["year"] for year in library["years"]] == [2026, 2025]
    assert library["years"][0]["months"] == [
        {"month": "07", "count": 3},
        {"month": "06", "count": 1},
    ]
    assert library["years"][1]["months"] == [{"month": "12", "count": 2}]


def test_build_media_tree_coerces_postgres_decimal_extract_values():
    # Postgres EXTRACT(...) returns Decimal, not int.
    rows = [("montage_talking_head", Decimal("2026"), Decimal("7"), 2)]

    tree = build_media_tree(rows)

    assert tree[0]["years"][0]["year"] == 2026
    assert tree[0]["years"][0]["months"] == [{"month": "07", "count": 2}]


def test_build_media_tree_handles_no_rows():
    assert build_media_tree([]) == []


def test_montage_media_asset_files_rendered_output():
    suite = make_suite()

    asset = montage_media_asset(suite, "job_1", rendered_montage_result())

    assert isinstance(asset, MediaAsset)
    assert asset.suite_id == "suite_1"
    assert asset.library == MONTAGE_TALKING_HEAD_LIBRARY
    assert asset.url == "https://media.example.com/video_montage/job_1/final.mp4"
    assert asset.source_job_id == "job_1"
    assert asset.content_type == "video/mp4"
    assert asset.duration_seconds == 32.5
    assert "متجر الياسمين" in asset.title


def test_montage_media_asset_tolerates_missing_duration():
    suite = make_suite()
    result = rendered_montage_result(video_montage={"render": {"rendered": True}})

    asset = montage_media_asset(suite, "job_1", result)

    assert asset is not None
    assert asset.duration_seconds is None


def test_montage_media_asset_skips_unrendered_results():
    suite = make_suite()

    assert montage_media_asset(suite, "job_1", rendered_montage_result(rendered=False)) is None
    assert montage_media_asset(suite, "job_1", {}) is None
    assert montage_media_asset(suite, "job_1", None) is None


def test_montage_media_asset_skips_outputs_not_in_public_storage():
    suite = make_suite()

    local = rendered_montage_result(output_url="/static/video_montage/job_1/final.mp4")
    assert montage_media_asset(suite, "job_1", local) is None

    insecure = rendered_montage_result(output_url="http://media.example.com/final.mp4")
    assert montage_media_asset(suite, "job_1", insecure) is None

    missing = rendered_montage_result(output_url="")
    assert montage_media_asset(suite, "job_1", missing) is None


def test_serialize_media_asset_returns_frontend_contract():
    asset = montage_media_asset(make_suite(), "job_1", rendered_montage_result())
    assert asset is not None
    asset.id = "asset_1"

    payload = serialize_media_asset(asset)

    assert payload["id"] == "asset_1"
    assert payload["url"] == "https://media.example.com/video_montage/job_1/final.mp4"
    assert payload["thumbnail_url"] is None
    assert payload["content_type"] == "video/mp4"
    assert payload["duration_seconds"] == 32.5
    assert payload["created_at"] is None  # server default applies on insert
    assert set(payload) == {
        "id",
        "title",
        "url",
        "thumbnail_url",
        "content_type",
        "duration_seconds",
        "created_at",
    }


def _asset(kind="visual_video", suite_id=None, usage=0, asset_id="a1"):
    from api.models.admin import CreativeAsset

    return CreativeAsset(
        id=asset_id,
        kind=kind,
        title=asset_id,
        storage_url=f"https://cdn.example/{asset_id}.mp4",
        tags=[],
        use_cases=[],
        usage_count=usage,
        active=True,
        metadata_json={"suite_id": suite_id} if suite_id else {},
    )


def test_pick_asset_prefers_same_suite_visuals():
    from api.services.creative_assets import pick_asset

    own = _asset(suite_id="suite-a", asset_id="own")
    foreign = _asset(suite_id="suite-b", asset_id="foreign")
    picked = pick_asset([foreign, own], kind="visual_video", suite_id="suite-a", variety_seed=0)
    assert picked.id == "own"


def test_pick_asset_rotates_visual_candidates_by_seed():
    from api.services.creative_assets import pick_asset

    assets = [_asset(asset_id=f"v{i}") for i in range(3)]
    picked = {pick_asset(assets, kind="visual_video", variety_seed=seed).id for seed in range(3)}
    assert len(picked) == 3
