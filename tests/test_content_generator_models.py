import sys
import types

from api.services import content_generator


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
