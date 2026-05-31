"""Unit tests for the strategy generator service."""
import pytest
from unittest.mock import AsyncMock, patch


# ── _is_arabic ────────────────────────────────────────────────────────────────

def test_is_arabic_detects_arabic_dialects():
    from api.services.strategy_generator import _is_arabic
    assert _is_arabic({"dialect": "Palestinian Arabic"}) is True
    assert _is_arabic({"dialect": "Gulf Arabic"}) is True
    assert _is_arabic({"dialect": "MSA"}) is True


def test_is_arabic_returns_false_for_english_and_null():
    from api.services.strategy_generator import _is_arabic
    assert _is_arabic({"dialect": "English"}) is False
    assert _is_arabic({"dialect": None}) is False
    assert _is_arabic({}) is False


# ── research_competitors ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_research_competitors_caps_at_four():
    with patch("api.services.strategy_generator.search_business", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = "some snippets"
        from api.services.strategy_generator import research_competitors
        result = await research_competitors(
            ["A", "B", "C", "D", "E"],  # 5 names
            "My Business",
        )
    assert len(result) == 4
    assert "E" not in result


@pytest.mark.asyncio
async def test_research_competitors_returns_empty_string_on_failure():
    with patch("api.services.strategy_generator.search_business", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = Exception("network error")
        from api.services.strategy_generator import research_competitors
        result = await research_competitors(["BadComp"], "My Business")
    assert result["BadComp"] == ""


@pytest.mark.asyncio
async def test_research_competitors_empty_list_returns_empty_dict():
    from api.services.strategy_generator import research_competitors
    result = await research_competitors([], "My Business")
    assert result == {}


# ── generate_strategy ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_strategy_returns_required_keys():
    mock_payload = {
        "marketing_plan": {
            "services": ["s1"],
            "keywords": ["k1"],
            "competitors": [],
            "audience": {
                "problem": "test problem",
                "demographics": {"age": "25-45", "gender": "all", "language": "English", "social_status": "middle"},
                "geography": {"countries": ["US"], "regions": [], "cities": []},
                "interests": ["tech"],
                "facebook_interests": ["Technology"],
                "digital_behavior": "active on Instagram",
                "personas": [],
            },
            "content_themes": ["t1"],
        },
        "marketing_message": "Test message",
    }
    with patch("api.services.strategy_generator.research_competitors", new_callable=AsyncMock) as mock_rc, \
         patch("api.services.strategy_generator.call_text_ai", new_callable=AsyncMock) as mock_call:
        mock_rc.return_value = {}
        mock_call.return_value = __import__("json").dumps(mock_payload)

        from api.services.strategy_generator import generate_strategy
        result = await generate_strategy({
            "name": "Test Co",
            "dialect": "English",
            "services": ["service"],
            "target_audience": "businesses",
            "how_they_help": "save time",
            "unique_value": "AI-powered",
            "esp": "feel confident",
            "competitors": [],
        })

    assert "marketing_plan" in result
    assert "marketing_message" in result
    assert "language" in result
    assert result["language"] == "en"


@pytest.mark.asyncio
async def test_generate_strategy_detects_arabic_language():
    mock_payload = {"marketing_plan": {}, "marketing_message": "رسالة"}

    with patch("api.services.strategy_generator.research_competitors", new_callable=AsyncMock) as mock_rc, \
         patch("api.services.strategy_generator.call_text_ai", new_callable=AsyncMock) as mock_call:
        mock_rc.return_value = {}
        mock_call.return_value = __import__("json").dumps(mock_payload)

        from api.services.strategy_generator import generate_strategy
        result = await generate_strategy({
            "name": "مشروع",
            "dialect": "Palestinian Arabic",
            "services": [],
            "competitors": [],
        })

    assert result["language"] == "ar"
