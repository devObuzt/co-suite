"""Production AI route decisions and prompt metadata policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from ..core.config import settings

PromptPolicyVersion = "oneshare-ai-router-v1"

RTL_LANGUAGES = {"ar", "he"}
NATIVE_TEXT_LANGUAGES = {"ar", "he", "en", "fr", "es", "tr", "ru", "zh"}


class AiRoute(StrEnum):
    onboarding_extract = "onboarding_extract"
    onboarding_translate_repair = "onboarding_translate_repair"
    strategy_plan = "strategy_plan"
    idea_generation = "idea_generation"
    caption_generation = "caption_generation"
    image_generation = "image_generation"
    carousel_generation = "carousel_generation"
    video_generation = "video_generation"
    product_bulk_template = "product_bulk_template"
    product_bulk_asset = "product_bulk_asset"
    social_content_plan = "social_content_plan"
    safety_json_repair = "safety_json_repair"


@dataclass(frozen=True)
class AiRouteDecision:
    route: str
    provider: str
    model: str
    model_version: str
    prompt_policy_version: str
    tier: str
    max_retries: int
    fallback_chain: list[dict[str, str]]
    cost_estimate: dict[str, Any]
    language_policy: dict[str, Any]
    media_policy: dict[str, Any] | None = None

    def as_metadata(self) -> dict[str, Any]:
        return asdict(self)


def normalize_language(language: str | None) -> str:
    code = (language or "en").strip().lower()
    if not code:
        return "en"
    return code.split("-", 1)[0]


def text_rendering_mode_for_media(language: str | None, requested_mode: str | None = None, *, has_visible_text: bool = True) -> str:
    mode = (requested_mode or "").strip()
    if mode in {"native_text_design", "text_free_background", "local_overlay", "not_applicable"}:
        return mode
    if not has_visible_text:
        return "text_free_background"
    return "native_text_design" if normalize_language(language) in NATIVE_TEXT_LANGUAGES else "local_overlay"


def media_backend_for_urls(urls: list[str] | None) -> str:
    clean = [url for url in (urls or []) if isinstance(url, str) and url]
    if not clean:
        return "none"
    if all(url.startswith("http://") or url.startswith("https://") for url in clean):
        return "r2"
    if any(url.startswith("/static/") for url in clean):
        return "local_static"
    return "provider_file"


def public_url_ready(urls: list[str] | None) -> bool:
    clean = [url for url in (urls or []) if isinstance(url, str) and url]
    return bool(clean) and all(url.startswith("http://") or url.startswith("https://") for url in clean)


def language_prompt_rules(language: str | None) -> list[str]:
    code = normalize_language(language)
    rules = [
        f"Use exactly one output language for this post: {code}.",
        "Do not mix caption, visible text, hashtags, CTA, or slide text across languages.",
    ]
    if code in RTL_LANGUAGES:
        rules.extend(
            [
                "For visible Arabic or Hebrew text, render right-to-left text correctly.",
                "Keep letters connected and shaped correctly; do not reverse word or letter order.",
                "Prefer short, high-contrast text blocks with generous spacing.",
            ]
        )
    return rules


def _language_policy(language: str | None, *, visible_text: bool, media_route: bool) -> dict[str, Any]:
    code = normalize_language(language)
    supported = not media_route or not visible_text or code in NATIVE_TEXT_LANGUAGES
    return {
        "target_language": code,
        "single_language_required": True,
        "rtl": code in RTL_LANGUAGES,
        "text_in_media_supported": supported,
        "unsupported_fallback_reason": None if supported else "unsupported_language_media_mode",
        "prompt_rules": language_prompt_rules(code),
    }


def _estimate(route: AiRoute, request_context: dict[str, Any]) -> dict[str, Any]:
    count = int(request_context.get("count") or request_context.get("image_count") or 1)
    if route in {AiRoute.image_generation, AiRoute.product_bulk_template, AiRoute.product_bulk_asset}:
        return {"units": {"images": max(1, count)}, "estimated_cost_usd": round(0.039 * max(1, count), 4), "currency": "USD"}
    if route == AiRoute.carousel_generation:
        slides = int(request_context.get("slide_count") or count or 1)
        return {"units": {"slides": max(1, slides)}, "estimated_cost_usd": round(0.039 * max(1, slides), 4), "currency": "USD"}
    if route == AiRoute.video_generation:
        seconds = int(request_context.get("seconds") or 8)
        return {"units": {"seconds": seconds}, "estimated_cost_usd": round(0.15 * seconds, 4), "currency": "USD"}
    return {"units": {"requests": max(1, count)}, "estimated_cost_usd": 0.01, "currency": "USD"}


def resolve_ai_route(
    route: AiRoute | str,
    tenant_context: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> AiRouteDecision:
    route = AiRoute(route)
    tenant_context = tenant_context or {}
    request_context = request_context or {}
    language = normalize_language(
        request_context.get("language")
        or request_context.get("content_language")
        or tenant_context.get("language")
    )
    visible_text = bool(request_context.get("visible_text", True))
    media_route = route in {
        AiRoute.image_generation,
        AiRoute.carousel_generation,
        AiRoute.video_generation,
        AiRoute.product_bulk_template,
        AiRoute.product_bulk_asset,
    }

    provider = "anthropic"
    model = settings.anthropic_text_model
    tier = "standard"
    max_retries = 2
    fallback_chain: list[dict[str, str]] = [{"provider": "openai", "model": settings.openai_text_model}]
    media_policy = None

    if route in {AiRoute.onboarding_extract, AiRoute.strategy_plan}:
        provider = "openai"
        model = settings.openai_text_model
        fallback_chain = [{"provider": "anthropic", "model": settings.anthropic_text_model}]
    elif route in {AiRoute.onboarding_translate_repair, AiRoute.safety_json_repair}:
        provider = "openai"
        model = settings.openai_fast_model
        tier = "fast"
        max_retries = 1
        fallback_chain = []
    elif route in {AiRoute.caption_generation}:
        model = settings.anthropic_fast_model
        tier = "fast"
        fallback_chain = [{"provider": "openai", "model": settings.openai_fast_model}]
    elif route in {AiRoute.image_generation, AiRoute.carousel_generation, AiRoute.product_bulk_template, AiRoute.product_bulk_asset}:
        provider = "google"
        model = settings.google_image_model
        max_retries = 1
        fallback_chain = []
        if not visible_text and route in {AiRoute.image_generation, AiRoute.carousel_generation}:
            fallback_chain = [{"provider": "google", "model": "imagen-4.0-fast-generate-001", "mode": "text_free_background"}]
        media_policy = {
            "storage_backend": "r2_preferred",
            "public_url_required": True,
            "text_rendering_mode": text_rendering_mode_for_media(language, request_context.get("text_rendering_mode"), has_visible_text=visible_text),
        }
    elif route == AiRoute.video_generation:
        provider = "google"
        model = settings.google_video_model
        requested_tier = (request_context.get("model_tier") or request_context.get("tier") or "").strip()
        if requested_tier == "fast":
            model = "veo-3.1-lite-generate-preview"
            tier = "fast"
        elif requested_tier == "quality":
            model = "veo-3.1-generate-preview"
            tier = "quality"
        max_retries = 1
        fallback_chain = []
        media_policy = {
            "storage_backend": "r2_preferred",
            "public_url_required": True,
            "text_rendering_mode": "local_overlay" if language in RTL_LANGUAGES else "native_text_design",
        }

    return AiRouteDecision(
        route=route.value,
        provider=provider,
        model=model,
        model_version=model,
        prompt_policy_version=PromptPolicyVersion,
        tier=tier,
        max_retries=max_retries,
        fallback_chain=fallback_chain,
        cost_estimate=_estimate(route, request_context),
        language_policy=_language_policy(language, visible_text=visible_text, media_route=media_route),
        media_policy=media_policy,
    )
