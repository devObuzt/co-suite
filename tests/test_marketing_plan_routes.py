import json

import pytest

from api.models.suite import Suite
from api.models.user import User
from api.routers import marketing_plans


class FakeDb:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


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
    assert all(1 <= len(item["text"].split()) <= 3 for item in first + more)


def test_keyword_candidates_use_category_and_services_not_brand_name():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "One Clinic", "industry": "Dental clinic", "services": ["Teeth whitening"]},
        strategy={},
    )

    keywords = [item["text"].casefold() for item in marketing_plans._keyword_candidates(suite, "en")]

    assert "one clinic" not in keywords
    assert "best one" not in keywords
    assert "dental clinic" in keywords
    assert "teeth whitening" in keywords


@pytest.mark.asyncio
async def test_generate_keywords_filters_brand_name_from_ai_response(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "Academy", "services": ["Courses"]},
        strategy={},
    )

    async def fake_call_text_ai(**_kwargs):
        return json.dumps(
            {
                "keywords": [
                    {"text": "Smart Line Academy", "intent": "core"},
                    {"text": "أفضل Smart Line", "intent": "commercial"},
                    {"text": "دورات مهنية", "intent": "core"},
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(marketing_plans, "call_text_ai", fake_call_text_ai)

    keywords = [item["text"].casefold() for item in await marketing_plans._generate_keywords(suite, "ar")]

    assert "smart line academy" not in keywords
    assert "أفضل smart line".casefold() not in keywords
    assert "دورات مهنية" in keywords


def test_keyword_phase_does_not_auto_generate_competitors():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "industry": "Marketing", "services": ["Websites"]},
        strategy={},
    )

    intelligence = marketing_plans.normalize_marketing_intelligence(
        {"phase": "keywords", "keywords": [{"text": "Websites"}]},
        marketing_plans.suite_research_payload(suite),
        "en",
    )

    assert intelligence["keywords"]
    assert intelligence["competitors"] == []
    assert intelligence["demand_signals"] == []


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


def test_serpapi_results_are_grouped_by_source():
    organic_payload = {
        "organic_results": [
            {"title": "Clinic A", "link": "https://a.example", "snippet": "Dental clinic"},
            {"title": "Clinic B", "link": "https://b.example", "snippet": "Dental services"},
        ]
    }
    maps_payload = {
        "local_results": {
            "places": [
                {"title": "Clinic Map", "website": "https://maps.example", "address": "Main street"},
            ]
        }
    }

    organic = marketing_plans._serpapi_competitors_from_payload(organic_payload, "google_organic", 5)
    maps = marketing_plans._serpapi_competitors_from_payload(maps_payload, "maps", 5)

    assert [item["result_type"] for item in organic] == ["google_organic", "google_organic"]
    assert organic[0]["url"] == "https://a.example"
    assert maps[0]["result_type"] == "maps"
    assert maps[0]["url"] == "https://maps.example"


def test_serpapi_error_message_redacts_api_key():
    class FakeResponse:
        status_code = 400
        text = "Bad request https://serpapi.com/search.json?api_key=secret&engine=google"

        def json(self):
            return {"error": "Invalid location"}

    class FakeError(Exception):
        response = FakeResponse()

    message = marketing_plans._serpapi_error_message("Google organic", FakeError("boom api_key=secret"))

    assert "Invalid location" in message
    assert "secret" not in message
    assert "api_key" not in message


def test_marketing_intelligence_redacts_stored_serpapi_keys():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "industry": "Marketing", "services": ["Websites"]},
        strategy={
            "marketing_intelligence": {
                "phase": "competitors",
                "warnings": [
                    "SerpAPI failed: https://serpapi.com/search.json?api_key=secret-key&engine=google"
                ],
                "competitors": [
                    {
                        "name": "Search result",
                        "url": "https://serpapi.com/search.json?engine=google&api_key=secret-key&q=x",
                    }
                ],
            }
        },
    )

    intelligence = marketing_plans._intelligence(suite)
    serialized = json.dumps(intelligence)

    assert "secret-key" not in serialized
    assert "api_key" not in serialized
    assert "[redacted]" in serialized


@pytest.mark.asyncio
async def test_serpapi_failures_return_source_warnings(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "industry": "Marketing", "services": ["Websites"]},
        strategy={},
    )

    monkeypatch.setattr(marketing_plans.settings, "serpapi_api_key", "key")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            raise RuntimeError("SerpAPI unavailable")

    monkeypatch.setattr(marketing_plans.httpx, "AsyncClient", FakeClient)

    competitors, warnings = await marketing_plans._serpapi_competitors(suite, "en")

    assert competitors == []
    assert warnings
    assert "Google organic" in warnings[0]


@pytest.mark.asyncio
async def test_competitor_generation_preserves_existing_keywords(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "industry": "Marketing", "services": ["Websites"]},
        strategy={
            "marketing_intelligence": {
                "phase": "keywords",
                "status": "keywords_ready",
                "keywords": [{"id": "kw-1", "text": "digital marketing", "intent": "core"}],
                "competitors": [],
                "demand_signals": [],
                "supply_signals": [],
                "opportunities": [],
                "source_links": [],
                "warnings": [],
            }
        },
    )

    async def fake_serpapi_competitors(*_args, **_kwargs):
        return (
            [
                {
                    "id": "serpapi-google-a",
                    "name": "Competitor A",
                    "title": "Competitor A",
                    "platform": "google",
                    "result_type": "google_organic",
                    "url": "https://competitor.example",
                    "snippet": "Direct competitor",
                }
            ],
            [],
        )

    monkeypatch.setattr(marketing_plans, "_serpapi_competitors", fake_serpapi_competitors)

    intelligence = await marketing_plans._save_competitor_scratch_from_search(suite, "en")

    assert [item["text"] for item in intelligence["keywords"]] == ["digital marketing"]
    assert intelligence["competitors"][0]["url"] == "https://competitor.example"


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


@pytest.mark.asyncio
async def test_generate_keywords_route_saves_keywords_and_records_usage(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "Academy", "services": ["Trading courses"]},
        strategy={},
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()
    usage_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_generate_keywords(*_args, **_kwargs):
        return [{"id": "kw-1", "text": "دورات تداول", "intent": "core"}]

    async def fake_record_provider_usage(_db, **kwargs):
        usage_calls.append(kwargs)

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "_generate_keywords", fake_generate_keywords)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fake_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.generate_marketing_keywords(
        "suite-1",
        marketing_plans.MarketingStageRequest(language="ar"),
        user,
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert suite.strategy["marketing_intelligence"]["keywords"][0]["text"] == "دورات تداول"
    assert response["intelligence"]["keywords"][0]["text"] == "دورات تداول"
    assert usage_calls[0]["operation"] == "marketing_keywords.generate"
    assert usage_calls[0]["metadata"]["keywords"] == 1


@pytest.mark.asyncio
async def test_update_competitor_route_does_not_record_provider_usage(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "services": ["Websites"]},
        strategy={
            "marketing_intelligence": {
                "competitors": [
                    {"id": "competitor-1", "name": "Competitor", "classification_tags": []}
                ]
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fail_record_provider_usage(*_args, **_kwargs):
        raise AssertionError("competitor classification should not create provider usage")

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fail_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.update_marketing_competitor(
        "suite-1",
        "competitor-1",
        marketing_plans.CompetitorClassificationRequest(classification_tags=["good_competitor"]),
        user,
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert response["intelligence"]["competitors"][0]["classification_tags"] == ["good_competitor"]
