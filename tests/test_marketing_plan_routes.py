from api.models.suite import Suite
from api.routers import marketing_plans


def test_clear_marketing_plan_removes_generated_plan_data_only():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec"},
        strategy={
            "marketing_message": "Keep me",
            "marketing_plan": {"content_themes": ["Keep strategy"]},
            "marketing_plan_deck": {"cover": {"title": "Delete me"}},
            "marketing_intelligence": {"competitors": [{"name": "Delete me"}]},
            "marketing_action_plan": {"social_items": [{"title": "Delete me"}]},
        },
    )

    removed = marketing_plans._clear_marketing_plan_data(suite)

    assert removed == ["marketing_plan_deck", "marketing_intelligence", "marketing_action_plan"]
    assert suite.strategy["marketing_message"] == "Keep me"
    assert suite.strategy["marketing_plan"] == {"content_themes": ["Keep strategy"]}
    assert "marketing_plan_deck" not in suite.strategy
    assert "marketing_intelligence" not in suite.strategy
    assert "marketing_action_plan" not in suite.strategy


def test_empty_marketing_intelligence_has_no_generated_market_data():
    intelligence = marketing_plans._empty_marketing_intelligence("ar")

    assert intelligence["status"] == "missing"
    assert intelligence["competitors"] == []
    assert intelligence["demand_signals"] == []
    assert intelligence["supply_signals"] == []
    assert intelligence["opportunities"] == []


def test_save_competitor_scratch_writes_visible_competitors_without_deck():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "services": ["Websites"]},
        strategy={"marketing_message": "Keep me"},
    )

    intelligence = marketing_plans._save_competitor_scratch(suite, "ar")

    assert suite.strategy["marketing_message"] == "Keep me"
    assert suite.strategy["marketing_intelligence"]["status"] == "competitors_ready"
    assert intelligence["competitors"]
    assert intelligence["demand_signals"] == []
