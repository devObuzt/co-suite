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


def test_keyword_candidates_skip_existing_terms():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "industry": "Marketing", "services": ["Websites"]},
        strategy={},
    )

    first = marketing_plans._keyword_candidates(suite, "en")
    more = marketing_plans._keyword_candidates(suite, "en", [item["text"] for item in first], more=True)

    assert first
    assert more
    assert not {item["text"].casefold() for item in first} & {item["text"].casefold() for item in more}


def test_append_competitor_scratch_adds_more_mock_results():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "services": ["Websites"]},
        strategy={},
    )

    first = marketing_plans._save_competitor_scratch(suite, "ar")
    second = marketing_plans._append_competitor_scratch(suite, "ar")

    assert len(second["competitors"]) > len(first["competitors"])
    assert any(item["result_type"] == "maps" for item in second["competitors"])


def test_normalized_competitor_preserves_classification_tags():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "services": ["Websites"]},
        strategy={
            "marketing_intelligence": {
                "competitors": [
                    {
                        "id": "competitor-1",
                        "name": "Competitor",
                        "url": "https://example.com",
                        "result_type": "google_organic",
                        "classification_tags": ["good_competitor", "local_competitor"],
                    }
                ]
            }
        },
    )

    intelligence = marketing_plans._intelligence(suite)

    assert intelligence["competitors"][0]["classification_tags"] == ["good_competitor", "local_competitor"]


def test_suite_services_reads_strategy_marketing_plan_when_brand_services_missing():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec"},
        strategy={"marketing_plan": {"services": ["Landing pages", "SEO"]}},
    )

    assert marketing_plans._suite_services(suite) == ["Landing pages", "SEO"]


def test_audience_keyword_languages_prefer_selected_audience_languages():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={
            "name": "Connec",
            "audience_languages": ["ar"],
            "audience_language_names": ["Arabic"],
        },
        strategy={},
    )

    assert marketing_plans._audience_keyword_languages(suite, "en")[:2] == ["Arabic", "ar"]
