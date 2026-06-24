from api.services.provider_pricing import (
    estimate_text_cost_usd,
    estimate_serpapi_cost_usd,
    infer_provider_usage_from_billing_event,
)


def test_estimate_text_cost_uses_input_and_output_prices():
    cost = estimate_text_cost_usd(
        "openai",
        "gpt-5.1",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert cost > 0
    assert cost == round(cost, 6)


def test_infer_provider_usage_maps_legacy_billing_events():
    payload = infer_provider_usage_from_billing_event(
        "video_gen_fast",
        actual_cost_usd=0.4,
        metadata={"count": 1},
    )

    assert payload["provider"] == "google"
    assert payload["model"]
    assert payload["operation"] == "video_gen_fast"
    assert payload["actual_cost_usd"] == 0.4
    assert payload["metadata"]["cost_basis"] == "legacy_billing_actual"


def test_serpapi_cost_uses_configurable_per_search_price(monkeypatch):
    from api.services import provider_pricing

    monkeypatch.setattr(provider_pricing.settings, "serpapi_cost_per_search_usd", 0.01)

    assert estimate_serpapi_cost_usd(5) == 0.05
