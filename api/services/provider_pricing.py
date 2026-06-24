from __future__ import annotations

from typing import Any

from ..core.config import settings

# Prices are stored per 1M tokens. Keep values conservative and expose the
# cost_basis metadata so finance can distinguish measured usage from estimates.
TEXT_MODEL_PRICES_PER_1M: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-5.1"): (1.25, 10.0),
    ("openai", "gpt-4.1"): (2.0, 8.0),
    ("anthropic", "claude-sonnet-4-6"): (3.0, 15.0),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.8, 4.0),
}


def estimate_text_cost_usd(provider: str, model: str, *, input_tokens: int = 0, output_tokens: int = 0) -> float:
    key = ((provider or "").strip().lower(), (model or "").strip())
    input_price, output_price = TEXT_MODEL_PRICES_PER_1M.get(key, (0.0, 0.0))
    cost = (max(0, input_tokens) / 1_000_000 * input_price) + (max(0, output_tokens) / 1_000_000 * output_price)
    return round(cost, 6)


def infer_provider_usage_from_billing_event(
    event_type: str,
    *,
    actual_cost_usd: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    event = (event_type or "").strip()
    if event in {"image_gen"}:
        provider = "google"
        model = settings.google_image_model or "google_image"
    elif event in {"video_gen_fast", "video_gen_hq"}:
        provider = "google"
        model = settings.google_video_model or "google_video"
    elif event in {"llm_idea_gen", "brand_extract"}:
        provider = settings.ai_text_provider or "anthropic"
        model = settings.openai_text_model if provider == "openai" else settings.anthropic_text_model
    else:
        provider = str(metadata.get("provider") or "unknown")
        model = str(metadata.get("model") or "") or None

    inferred = {
        "provider": provider,
        "model": model,
        "operation": event or "usage_event",
        "actual_cost_usd": round(float(actual_cost_usd or 0.0), 6),
        "input_tokens": int(metadata.get("input_tokens") or 0),
        "output_tokens": int(metadata.get("output_tokens") or 0),
        "total_tokens": int(metadata.get("total_tokens") or metadata.get("tokens") or 0),
        "metadata": {**metadata, "cost_basis": metadata.get("cost_basis") or "legacy_billing_actual"},
    }
    return inferred


def estimate_serpapi_cost_usd(search_count: int) -> float:
    return round(max(0, int(search_count or 0)) * max(0.0, float(settings.serpapi_cost_per_search_usd or 0.0)), 6)


def estimate_google_ads_keyword_planner_cost_usd(request_count: int = 1) -> float:
    return round(max(0, int(request_count or 0)) * max(0.0, float(settings.google_ads_keyword_planner_cost_usd or 0.0)), 6)
