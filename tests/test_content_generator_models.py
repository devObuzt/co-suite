import sys
import types

from api.services import content_generator
from api.services.ai_router import AiRoute, PromptPolicyVersion, resolve_ai_route


def test_generate_image_can_disable_imagen_fallback_for_native_text(monkeypatch):
    monkeypatch.setattr(content_generator.settings, "google_api_key", "test-google-key")
    monkeypatch.setattr(content_generator.settings, "google_image_model", "gemini-3.1-flash-preview-image-generation")

    calls = {"generate_images": 0}

    class FakeModels:
        def generate_content(self, **_kwargs):
            raise RuntimeError("gemini unavailable")

        def generate_images(self, **_kwargs):
            calls["generate_images"] += 1
            raise AssertionError("Imagen fallback should not run for native text")

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

    fake_genai = types.SimpleNamespace(Client=FakeClient)
    fake_types = types.SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: kwargs,
        ImageConfig=lambda **kwargs: kwargs,
        GenerateImagesConfig=lambda **kwargs: kwargs,
    )
    google_module = types.ModuleType("google")
    google_module.genai = fake_genai
    genai_module = types.ModuleType("google.genai")
    genai_module.types = fake_types

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    result = content_generator._generate_image(
        "EXACT VISIBLE TEXT TO RENDER: مرحبا بالعالم",
        "4:5",
        allow_imagen_fallback=False,
    )

    assert result is None
    assert calls["generate_images"] == 0


def test_image_route_uses_google_policy_and_blocks_rtl_fallback_text():
    decision = resolve_ai_route(
        AiRoute.image_generation,
        request_context={"language": "ar", "visible_text": "عرض اليوم"},
    )

    assert decision.provider == "google"
    assert decision.model == content_generator.settings.google_image_model
    assert decision.model_version == content_generator.settings.google_image_model
    assert decision.prompt_policy_version == PromptPolicyVersion
    assert decision.language_policy["target_language"] == "ar"
    assert decision.language_policy["single_language_required"] is True
    assert decision.language_policy["text_in_media_supported"] is True
    assert decision.language_policy["unsupported_fallback_reason"] is None
    assert decision.fallback_chain == []


def test_content_output_metadata_records_route_model_language_and_text_mode():
    decision = resolve_ai_route(
        AiRoute.carousel_generation,
        request_context={"language": "he", "visible_text": "מבצע חדש"},
    )

    metadata = content_generator._output_ai_metadata(
        {
            "content_language": "he",
            "text_rendering_mode": "native_text_design",
            "platform_media": {"instagram": ["https://cdn.example/slide-1.png"]},
        },
        decision,
        media_urls=["https://cdn.example/slide-1.png"],
    )

    assert metadata["ai_route"] == "carousel_generation"
    assert metadata["provider"] == "google"
    assert metadata["model"] == content_generator.settings.google_image_model
    assert metadata["model_version"] == content_generator.settings.google_image_model
    assert metadata["prompt_policy_version"] == PromptPolicyVersion
    assert metadata["language"] == "he"
    assert metadata["text_rendering_mode"] == "native_text_design"
    assert metadata["media_backend"] == "r2"
    assert metadata["public_url_ready"] is True
    assert metadata["fallback_chain_used"] == []



def test_quick_creative_brief_reference_urls_are_collected_for_image_generation():
    urls = content_generator._quick_reference_urls(
        {
            "generation_request": {
                "creative_brief": {
                    "logo": {"enabled": True, "source": "uploaded", "url": "https://cdn.example/logo.png"},
                    "reference_assets": [
                        {"kind": "product", "urls": ["https://cdn.example/product.png"]},
                        {"kind": "style", "urls": ["https://cdn.example/style.webp"]},
                    ],
                }
            }
        }
    )

    assert urls == [
        "https://cdn.example/logo.png",
        "https://cdn.example/product.png",
        "https://cdn.example/style.webp",
    ]



def test_quick_image_required_sizes_expand_to_production_variants():
    specs = content_generator._image_variant_specs(
        {
            "generation_request": {
                "creative_brief": {
                    "required_sizes": {"ids": ["image_all", "google_ads_all"]}
                }
            }
        }
    )

    keys = [key for key, _aspect, _label in specs]
    assert "instagram" in keys
    assert "meta_square_1_1" in keys
    assert "story_9_16" in keys
    assert "facebook" in keys
    assert "google_square_1_1" in keys
    assert "google_landscape_1_91_1" in keys
    assert len(keys) == len(set(keys))


def test_quick_video_required_sizes_expand_to_video_variants():
    specs = content_generator._video_variant_specs(
        {
            "generation_request": {
                "creative_brief": {
                    "required_sizes": {"ids": ["video_story_reel_9_16", "video_wide_16_9"]}
                }
            }
        }
    )

    assert specs == [
        ("video_story_reel_9_16", "9:16", "Vertical story/reel video"),
        ("video_wide_16_9", "16:9", "Wide landscape video"),
    ]
