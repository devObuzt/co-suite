from api.routers.content import GenerateRequest, _effective_generation_count
from api.services import content_generator


def test_quick_mixed_request_generates_image_video_and_carousel_units():
    request = GenerateRequest(
        count=1,
        mode="quick",
        content_type="mixed",
        prompt="Create a mixed launch post",
    )

    assert _effective_generation_count(request) == 3


def test_quick_single_format_request_stays_single_unit():
    assert _effective_generation_count(
        GenerateRequest(count=1, mode="quick", content_type="image")
    ) == 1
    assert _effective_generation_count(
        GenerateRequest(count=1, mode="quick", content_type="video")
    ) == 1
    assert _effective_generation_count(
        GenerateRequest(count=1, mode="quick", content_type="carousel")
    ) == 1


def test_mixed_idea_counts_include_all_production_formats():
    assert content_generator._idea_format_counts("mixed", 3) == {
        "image_count": 1,
        "carousel_count": 1,
        "video_count": 1,
    }
