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


@pytest.mark.asyncio
async def test_paid_plan_routes_generate_save_and_refetch_without_erasing_social_data(monkeypatch):
    suite = Suite(
        id="suite-paid-route",
        owner_id="user-paid-route",
        name="Connec",
        slug="connec-paid-route",
        brand={"name": "Connec", "audience_languages": ["ar"]},
        strategy={"marketing_action_plan": {"social_ideas_plan": {"selected_ids": ["social-1"]}}},
    )
    user = User(
        id="user-paid-route",
        email="paid@example.com",
        hashed_password="hash",
        full_name="Paid Owner",
    )
    db = FakeDb()
    provider_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_generate_paid_content_work_plan(*_args, **_kwargs):
        return {
            "version": "paid_content_work_plan_v2",
            "status": "ready",
            "stages": [{"key": "awareness", "required_count": 1}],
            "candidates": {
                "awareness": [
                    {
                        "id": "awareness-1",
                        "stage": "awareness",
                        "title": "فكرة الوعي",
                        "description": "وصف مختصر",
                        "recommended_format": "ai_video",
                        "provider": "openai",
                    },
                    {
                        "id": "awareness-2",
                        "stage": "awareness",
                        "title": "فكرة وعي ثانية",
                        "description": "وصف مختصر ثانٍ",
                        "recommended_format": "carousel",
                        "provider": "anthropic",
                    },
                ]
            },
            "selected_ids": ["awareness-1"],
            "warnings": [],
        }

    async def fake_record_provider_usage(_db, **kwargs):
        provider_calls.append(kwargs)

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "generate_paid_content_work_plan", fake_generate_paid_content_work_plan)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fake_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    generated = await marketing_plans.generate_marketing_paid_content_plan(
        suite.id,
        marketing_plans.GeneratePaidContentPlanRequest(language="ar"),
        user,
        db,
    )
    saved = await marketing_plans.update_marketing_paid_content_plan_selection(
        suite.id,
        marketing_plans.PaidContentPlanSelectionRequest(selected_ids=["awareness-2"]),
        user,
        db,
    )
    refetched = marketing_plans._marketing_plan_response(suite, suite.id, None, "action_plan_ready")

    assert generated["action_plan"]["paid_content_plan"]["version"] == "paid_content_work_plan_v2"
    assert saved["action_plan"]["paid_content_plan"]["selected_ids"] == ["awareness-2"]
    assert refetched["action_plan"]["paid_content_plan"]["selected_ids"] == ["awareness-2"]
    assert refetched["action_plan"]["social_ideas_plan"] == {"selected_ids": ["social-1"]}
    assert provider_calls[0]["metadata"]["candidate_count"] == 2
    assert db.committed is True


@pytest.mark.asyncio
async def test_download_marketing_plan_pdf_returns_attachment(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "services": ["دورات تداول"]},
        strategy={
            "marketing_intelligence": {
                "language": "ar",
                "keywords": [{"id": "kw-1", "text": "دورات تداول"}],
                "competitors": [],
                "demand_signals": [],
                "supply_signals": [],
                "opportunities": [],
                "personas": [{"id": "p-1", "name": "ليان", "challenge": "تحتاج خطة واضحة."}],
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", hashed_password="hash", full_name="Owner")
    db = FakeDb()
    audit_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_record_audit_log(_db, **kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.download_marketing_plan_pdf("suite-1", user, db)

    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF")
    assert "smart-line-academy-marketing-plan.pdf" in response.headers["content-disposition"]
    assert response.headers["access-control-expose-headers"] == "Content-Disposition"
    assert db.committed is True
    assert audit_calls[0]["action"] == "marketing.pdf.download"


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


def test_paid_selection_keeps_one_idea_per_stage_and_preserves_social_plan():
    suite = Suite(
        id="suite-paid-selection",
        owner_id="user-1",
        name="Connec",
        slug="connec-paid-selection",
        brand={"name": "Connec"},
        strategy={
            "marketing_action_plan": {
                "social_ideas_plan": {"selected_ids": ["social-1"]},
                "paid_content_plan": {
                    "stages": [
                        {"key": "awareness", "required_count": 1},
                        {"key": "conversion", "required_count": 1},
                    ],
                    "candidates": {
                        "awareness": [
                            {"id": "awareness-1", "stage": "awareness"},
                            {"id": "awareness-2", "stage": "awareness"},
                        ],
                        "conversion": [{"id": "conversion-1", "stage": "conversion"}],
                    },
                    "selected_ids": [],
                },
            }
        },
    )

    plan = marketing_plans._update_paid_content_selection(
        suite,
        ["awareness-1", "awareness-2", "conversion-1"],
    )

    assert plan["selected_ids"] == ["awareness-1", "conversion-1"]
    assert suite.strategy["marketing_action_plan"]["social_ideas_plan"] == {"selected_ids": ["social-1"]}


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


def test_competitor_search_terms_clean_structured_location():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={
            "name": "Smart Line Academy",
            "industry": "تعليم تداول",
            "services": ["دورات تداول"],
            "audience_location": {"scope": "custom", "countries": ["إسرائيل"], "cities": []},
        },
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )

    terms = marketing_plans._competitor_search_terms(suite, "ar")

    assert terms
    assert any("إسرائيل" in term for term in terms)
    assert "scope" not in " ".join(terms)
    assert "{" not in " ".join(terms)
    assert any("קורס" in term or "מסחר" in term for term in terms)


def test_competitor_source_coverage_adds_one_lead_only_for_empty_sources():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"]},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    competitors = [
        {
            "id": "serpapi-google-a",
            "title": "Competitor A",
            "result_type": "google_organic",
            "platform": "google",
            "url": "https://competitor.example",
        }
    ]

    filled = marketing_plans._ensure_competitor_source_coverage(suite, "ar", competitors)
    counts: dict[str, int] = {}
    leads: dict[str, int] = {}
    for item in filled:
        source = item["result_type"]
        counts[source] = counts.get(source, 0) + 1
        if item.get("research_lead"):
            leads[source] = leads.get(source, 0) + 1

    # A source that already has a real result gets NO lead cards.
    assert leads.get("google_organic", 0) == 0
    assert counts["google_organic"] == 1
    # Empty sources get exactly one manual-review lead.
    for source in ["maps", "instagram", "facebook", "tiktok"]:
        assert counts[source] == 1
        assert leads[source] == 1


def test_normalize_can_suppress_starter_warning_after_real_search():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول"},
        strategy={},
    )

    intelligence = marketing_plans.normalize_marketing_intelligence(
        {
            "phase": "competitors",
            "suppress_starter_warnings": True,
            "competitors": [
                {
                    "id": "fallback-instagram-a",
                    "title": "مصدر بحث: دورات تداول",
                    "result_type": "instagram",
                    "platform": "instagram",
                    "url": "https://www.google.com/search?q=site%3Ainstagram.com+trading",
                    "research_lead": True,
                }
            ],
        },
        marketing_plans.suite_research_payload(suite),
        "ar",
    )

    assert intelligence["warnings"] == []


def test_social_competitor_filter_removes_unrelated_results():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={
            "name": "Smart Line Academy",
            "industry": "تعليم تداول",
            "services": ["دورات تداول", "تعليم الاستثمار", "تحليل الأسهم"],
        },
        strategy={
            "marketing_intelligence": {
                "keywords": [
                    {"id": "kw-1", "text": "دورات تداول"},
                    {"id": "kw-2", "text": "تعليم الأسهم"},
                ]
            }
        },
    )
    unrelated = {
        "id": "serpapi-instagram-story",
        "title": "#شهريزاد",
        "snippet": "في هذا المشهد التخيلي المولد بالذكاء الاصطناعي سرب هجومي من طائرات اليعسوب.",
        "url": "https://www.instagram.com/p/story/",
        "result_type": "instagram",
    }
    relevant = {
        "id": "serpapi-instagram-trading",
        "title": "أكاديمية تداول وأسهم",
        "snippet": "دورات تداول وتحليل الأسهم للمبتدئين.",
        "url": "https://www.instagram.com/tradingacademy/",
        "result_type": "instagram",
    }

    filtered = marketing_plans._filter_relevant_competitors(suite, "ar", "instagram", [unrelated, relevant])

    assert filtered == [relevant]


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


@pytest.mark.asyncio
async def test_demand_supply_saves_clear_warning_state_when_google_ads_unavailable(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"]},
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )

    async def fake_fetch_keyword_planner_ideas(*_args, **_kwargs):
        raise AssertionError("Google Ads should not be called when platform config is missing")

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_login_customer_id", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)

    intelligence = await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    demand_supply = intelligence["demand_supply"]
    assert "GOOGLE_ADS_CUSTOMER_ID" in demand_supply["warning"]
    assert "Railway" in demand_supply["warning"]
    assert "Google Ads account is not connected" not in demand_supply["warning"]
    assert demand_supply["credential_source"] == "platform_missing"
    assert "GOOGLE_ADS_REFRESH_TOKEN" in demand_supply["missing_config"]
    assert demand_supply["request"]["attempts"] == 0
    assert demand_supply["summary"]["analyzed_keywords"] == 0
    assert intelligence["demand_signals"]
    assert intelligence["supply_signals"]
    assert intelligence["opportunities"]
    assert intelligence["warnings"] == []


@pytest.mark.asyncio
async def test_demand_supply_uses_platform_google_ads_credentials(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"], "location": "الأردن"},
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, *_args, **_kwargs):
        calls.append((customer_id, refresh_token))
        return {
            "keyword_metrics": [{"keyword": "دورات تداول", "average_monthly_searches": 500, "competition_index": 44}],
            "suggested_keywords": [],
            "summary": {
                "analyzed_keywords": 1,
                "average_monthly_searches": 500,
                "competition_level": "MEDIUM",
                "average_competition_index": 44,
                "market_pressure_score": 35,
                "suggested_keywords": 0,
            },
        }

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "123-456-7890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)

    intelligence = await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    assert calls == [("123-456-7890", "platform-refresh-token")]
    assert intelligence["demand_supply"]["credential_source"] == "platform"
    assert intelligence["demand_supply"]["warning"] is None
    assert intelligence["demand_supply"]["summary"]["average_monthly_searches"] == 500


@pytest.mark.asyncio
async def test_demand_supply_uses_login_customer_id_as_customer_fallback(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"], "location": "الأردن"},
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, *_args, **_kwargs):
        calls.append((customer_id, refresh_token))
        return {
            "keyword_metrics": [{"keyword": "دورات تداول", "average_monthly_searches": 500, "competition_index": 44}],
            "suggested_keywords": [],
            "summary": {},
        }

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_login_customer_id", "1520081637")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)

    intelligence = await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    assert calls == [("1520081637", "platform-refresh-token")]
    assert intelligence["demand_supply"]["credential_source"] == "platform"
    assert intelligence["demand_supply"]["missing_config"] == []
    assert intelligence["demand_supply"]["warning"] is None


def test_public_demand_supply_warning_localizes_google_ads_permission_error():
    warning = (
        "The caller does not have permission Details: "
        "authorizationError: USER_PERMISSION_DENIED"
    )

    public = marketing_plans._public_demand_supply_warning(warning, "ar", "platform")

    assert "حساب Google Ads المركزي" in public
    assert "GOOGLE_ADS_CUSTOMER_ID" in public


@pytest.mark.asyncio
async def test_demand_supply_queries_hebrew_for_arabic_israel_market(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={
            "name": "Smart Line Academy",
            "industry": "تعليم تداول",
            "services": ["دورات تداول"],
            "audience_location": {"scope": "custom", "countries": ["إسرائيل"], "cities": []},
        },
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, keywords, language, location, *_args, **_kwargs):
        calls.append({"customer_id": customer_id, "refresh_token": refresh_token, "keywords": keywords, "language": language, "location": location})
        keyword = keywords[0]
        return {
            "keyword_metrics": [{"keyword": keyword, "average_monthly_searches": 300 if language == "he" else 200, "competition_index": 40}],
            "suggested_keywords": [],
            "summary": {},
            "request": {"language": language, "keyword_count": len(keywords)},
        }

    async def fake_call_text_ai(**_kwargs):
        return json.dumps({"keywords": ["קורס מסחר", "לימוד מסחר"]}, ensure_ascii=False)

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "1234567890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)
    monkeypatch.setattr(marketing_plans, "call_text_ai", fake_call_text_ai)

    intelligence = await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    assert [call["language"] for call in calls] == ["ar", "he"]
    assert calls[0]["location"] == "إسرائيل"
    assert "קורס מסחר" in calls[1]["keywords"]
    assert intelligence["demand_supply"]["summary"]["analyzed_keywords"] == 2
    assert intelligence["demand_supply"]["summary"]["total_monthly_searches"] == 500


@pytest.mark.asyncio
async def test_demand_supply_queries_hebrew_with_ai_translation_for_unmapped_keywords(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Hummus House",
        slug="hummus-house",
        brand={
            "name": "Hummus House",
            "industry": "مطاعم",
            "services": ["مطعم حمص"],
            "audience_location": {"scope": "custom", "countries": ["إسرائيل"], "cities": []},
        },
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "مطعم حمص"}]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, keywords, language, location, *_args, **_kwargs):
        calls.append({"keywords": keywords, "language": language})
        return {
            "keyword_metrics": [{"keyword": keywords[0], "average_monthly_searches": 100, "competition_index": 20}],
            "suggested_keywords": [],
            "summary": {},
            "request": {"language": language, "keyword_count": len(keywords)},
        }

    async def fake_call_text_ai(**_kwargs):
        return json.dumps({"keywords": ["מסעדת חומוס", "חומוס"]}, ensure_ascii=False)

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "1234567890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)
    monkeypatch.setattr(marketing_plans, "call_text_ai", fake_call_text_ai)

    intelligence = await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    assert [call["language"] for call in calls] == ["ar", "he"]
    assert calls[0]["keywords"] == ["مطعم حمص"]
    assert calls[1]["keywords"] == ["מסעדת חומוס", "חומוס"]
    assert intelligence["demand_supply"]["summary"]["analyzed_keywords"] == 2


@pytest.mark.asyncio
async def test_demand_supply_seeds_from_keywords_and_services_and_accumulates(monkeypatch):
    keywords = [f"كلمة {index}" for index in range(1, 8)]
    services = [f"خدمة {index}" for index in range(1, 8)]
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Amman Services Co",
        slug="amman-services",
        brand={"name": "Amman Services Co", "industry": "خدمات", "services": services, "audience_country": "الأردن"},
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": f"kw-{index}", "text": text} for index, text in enumerate(keywords, start=1)]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, seed_keywords, language, location, *_args, **_kwargs):
        calls.append(list(seed_keywords))
        return {
            "keyword_metrics": [
                {"keyword": keyword, "average_monthly_searches": 10, "competition_index": 10}
                for keyword in seed_keywords
            ],
            "suggested_keywords": [],
            "summary": {},
            "request": {"language": language, "keyword_count": len(seed_keywords)},
        }

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "1234567890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)

    first = (await marketing_plans._save_demand_supply_from_google_ads(suite, "ar"))["demand_supply"]

    assert len(calls) == 1
    assert len(calls[0]) == 10
    assert sum(1 for term in calls[0] if term in set(keywords)) == 5
    assert sum(1 for term in calls[0] if term in set(services)) == 5
    assert first["remaining_terms"] == 4
    assert len(first["checked_terms"]) == 10
    assert len(first["last_seeds"]["keywords"]) == 5
    assert len(first["last_seeds"]["services"]) == 5

    second = (await marketing_plans._save_demand_supply_from_google_ads(suite, "ar", more=True))["demand_supply"]

    assert len(calls) == 2
    assert len(calls[1]) == 4
    assert not set(calls[1]) & set(calls[0])
    assert second["remaining_terms"] == 0
    assert len(second["checked_terms"]) == 14
    assert second["summary"]["analyzed_keywords"] == 14

    third = (await marketing_plans._save_demand_supply_from_google_ads(suite, "ar", more=True))["demand_supply"]

    assert len(calls) == 2
    assert third["remaining_terms"] == 0
    assert third["summary"]["analyzed_keywords"] == 14
    assert third["warning"] is None


@pytest.mark.asyncio
async def test_demand_supply_hebrew_falls_back_to_static_map_when_ai_fails(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={
            "name": "Smart Line Academy",
            "industry": "تعليم تداول",
            "services": ["دورات تداول"],
            "audience_location": {"scope": "custom", "countries": ["إسرائيل"], "cities": []},
        },
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    calls = []

    async def fake_fetch_keyword_planner_ideas(customer_id, refresh_token, keywords, language, location, *_args, **_kwargs):
        calls.append({"keywords": keywords, "language": language})
        return {
            "keyword_metrics": [{"keyword": keywords[0], "average_monthly_searches": 100, "competition_index": 20}],
            "suggested_keywords": [],
            "summary": {},
            "request": {"language": language, "keyword_count": len(keywords)},
        }

    async def failing_call_text_ai(**_kwargs):
        raise RuntimeError("AI unavailable")

    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "1234567890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)
    monkeypatch.setattr(marketing_plans, "call_text_ai", failing_call_text_ai)

    await marketing_plans._save_demand_supply_from_google_ads(suite, "ar")

    assert [call["language"] for call in calls] == ["ar", "he"]
    assert any("קורס" in keyword or "מסחר" in keyword for keyword in calls[1]["keywords"])


@pytest.mark.asyncio
async def test_generate_demand_supply_route_returns_planner_metrics(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"], "audience_country": "إسرائيل"},
        connections={},
        strategy={"marketing_intelligence": {"keywords": [{"id": "kw-1", "text": "دورات تداول"}]}},
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()
    usage_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_fetch_keyword_planner_ideas(_customer_id, _refresh_token, keywords, language, *_args, **_kwargs):
        return {
            "keyword_metrics": [{"keyword": keywords[0], "average_monthly_searches": 120, "competition_index": 35}],
            "suggested_keywords": [],
            "summary": {},
            "request": {"language": language},
        }

    async def fake_record_provider_usage(_db, **kwargs):
        usage_calls.append(kwargs)

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    async def fake_call_text_ai(**_kwargs):
        return json.dumps({"keywords": ["קורס מסחר"]}, ensure_ascii=False)

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "call_text_ai", fake_call_text_ai)
    monkeypatch.setattr(marketing_plans.settings, "google_ads_customer_id", "1234567890")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_refresh_token", "platform-refresh-token")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_id", "platform-client")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_client_secret", "platform-secret")
    monkeypatch.setattr(marketing_plans.settings, "google_ads_developer_token", "platform-dev-token")
    monkeypatch.setattr(marketing_plans, "fetch_keyword_planner_ideas", fake_fetch_keyword_planner_ideas)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fake_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.generate_marketing_demand_supply(
        "suite-1",
        marketing_plans.GenerateMarketingPlanRequest(language="ar"),
        user,
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert response["intelligence"]["demand_supply"]["summary"]["analyzed_keywords"] == 2
    assert response["intelligence"]["demand_supply"]["warning"] is None
    assert usage_calls[0]["operation"] == "marketing_demand_supply.generate"
    assert usage_calls[0]["status"] == "success"
    assert usage_calls[0]["metadata"]["credential_source"] == "platform"


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


@pytest.mark.asyncio
async def test_competitor_generation_clears_old_warnings_and_fills_missing_sources(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "Trading academy", "services": ["Trading courses"]},
        strategy={
            "marketing_intelligence": {
                "phase": "competitors",
                "status": "competitors_ready",
                "keywords": [{"id": "kw-1", "text": "دورات تداول"}],
                "warnings": ["old SerpAPI failure should not stay visible"],
                "competitors": [],
                "demand_signals": [],
                "supply_signals": [],
                "opportunities": [],
                "source_links": [],
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
            ["SerpAPI Google Maps failed: 400"],
        )

    monkeypatch.setattr(marketing_plans, "_serpapi_competitors", fake_serpapi_competitors)

    intelligence = await marketing_plans._save_competitor_scratch_from_search(suite, "ar")
    sources = {item["result_type"] for item in intelligence["competitors"]}

    assert intelligence["warnings"] == []
    assert "old SerpAPI failure should not stay visible" not in str(intelligence)
    # Source-level failures are admin-only now: logged + stored internally,
    # never surfaced to the user-facing source_warnings.
    assert intelligence["source_warnings"] == []
    assert intelligence["internal_source_warnings"] == ["SerpAPI Google Maps failed: 400"]
    assert {"google_organic", "maps", "instagram", "facebook", "tiktok"}.issubset(sources)
    assert [item["text"] for item in intelligence["keywords"]] == ["دورات تداول"]


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


@pytest.mark.asyncio
async def test_update_competitors_saves_manual_items_and_order(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={"name": "Connec", "services": ["Websites"]},
        strategy={
            "marketing_intelligence": {
                "language": "ar",
                "keywords": [{"id": "kw-1", "text": "دورات تداول"}],
                "competitors": [
                    {"id": "old-1", "name": "Old first", "result_type": "google_organic", "url": "https://one.example"},
                    {"id": "old-2", "name": "Old second", "result_type": "google_organic", "url": "https://two.example"},
                ],
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", hashed_password="hash", full_name="Owner")
    db = FakeDb()

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.update_marketing_competitors(
        "suite-1",
        marketing_plans.MarketingCompetitorsUpdateRequest(
            competitors=[
                {"id": "old-2", "name": "Old second", "result_type": "google_organic", "url": "https://two.example"},
                {"id": "old-1", "name": "Old first", "result_type": "google_organic", "url": "https://one.example"},
                {"name": "Manual maps", "result_type": "maps", "platform": "maps", "url": "https://maps.example", "classification_tags": ["global_competitor", "good_competitor", "bad_tag"]},
            ]
        ),
        user,
        db,
    )

    competitors = response["intelligence"]["competitors"]
    assert [item["id"] for item in competitors[:2]] == ["old-2", "old-1"]
    assert competitors[2]["name"] == "Manual maps"
    assert competitors[2]["result_type"] == "maps"
    assert competitors[2]["classification_tags"] == ["good_competitor", "global_competitor"]
    assert [item["text"] for item in response["intelligence"]["keywords"]] == ["دورات تداول"]
    assert db.committed is True


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
async def test_update_keywords_route_saves_manual_order(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Sea of Herbs",
        slug="sea-of-herbs",
        brand={"name": "Sea of Herbs"},
        strategy={
            "marketing_intelligence": {
                "language": "ar",
                "keywords": [{"id": "kw-old", "text": "قديم"}],
                "competitors": [{"id": "competitor-1", "name": "Keep competitor", "title": "Keep competitor", "result_type": "google_organic", "url": "https://example.com"}],
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()
    audit_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_record_audit_log(_db, **kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.update_marketing_keywords(
        "suite-1",
        marketing_plans.MarketingKeywordsUpdateRequest(
            keywords=[
                marketing_plans.MarketingKeywordInput(id="kw-2", text="زيوت علاجية", intent="commercial"),
                marketing_plans.MarketingKeywordInput(id="kw-1", text="أعشاب طبيعية", intent="core"),
                marketing_plans.MarketingKeywordInput(text="أعشاب طبيعية", intent="duplicate"),
            ]
        ),
        user,
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert [item["text"] for item in suite.strategy["marketing_intelligence"]["keywords"]] == ["زيوت علاجية", "أعشاب طبيعية"]
    assert suite.strategy["marketing_intelligence"]["keywords"][0]["position"] == 0
    assert suite.strategy["marketing_intelligence"]["competitors"][0]["name"] == "Keep competitor"
    assert response["intelligence"]["keywords"][0]["text"] == "زيوت علاجية"
    assert audit_calls[0]["action"] == "marketing.keywords.update"


@pytest.mark.asyncio
async def test_generate_personas_route_saves_personas_and_preserves_market_data(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "industry": "تعليم تداول", "services": ["دورات تداول"]},
        strategy={
            "marketing_intelligence": {
                "keywords": [{"id": "kw-1", "text": "دورات تداول"}],
                "competitors": [{"id": "competitor-1", "name": "CFI", "url": "https://cfi.example"}],
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()
    usage_calls = []

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_generate_personas(suite_arg, language, *_args, existing_persona_values=None, append=False, **_kwargs):
        existing = marketing_plans.normalize_marketing_intelligence(
            suite_arg.strategy["marketing_intelligence"],
            marketing_plans.suite_research_payload(suite_arg),
            language,
        )
        assert existing_persona_values == []
        assert append is False
        return {
            **existing,
            "phase": "personas",
            "status": "personas_ready",
            "personas": [
                {
                    "id": f"persona-{index}",
                    "name": f"عميل {index}",
                    "age": 20 + index,
                    "gender": "female" if index % 2 else "male",
                    "economic_status": "متوسطة",
                    "profession": "مستقل",
                    "challenge": "تحدي واضح",
                    "need": "حاجة واضحة",
                    "motivation": "دافع واضح",
                    "solution": "حل واضح",
                    "avatar_seed": f"persona-{index}",
                }
                for index in range(1, 6)
            ],
        }

    async def fake_record_provider_usage(_db, **kwargs):
        usage_calls.append(kwargs)

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "generate_marketing_customer_personas_research", fake_generate_personas)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fake_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.generate_marketing_personas(
        "suite-1",
        marketing_plans.MarketingStageRequest(language="ar"),
        user,
        db,  # type: ignore[arg-type]
    )

    intelligence = response["intelligence"]
    assert db.committed is True
    assert intelligence["status"] == "personas_ready"
    assert len(intelligence["personas"]) == 5
    assert intelligence["keywords"][0]["text"] == "دورات تداول"
    assert intelligence["competitors"][0]["name"] == "CFI"
    assert usage_calls[0]["operation"] == "marketing_personas.generate"
    assert usage_calls[0]["metadata"]["personas"] == 5


@pytest.mark.asyncio
async def test_generate_more_personas_route_appends_existing_personas(monkeypatch):
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={"name": "Smart Line Academy", "audience_language": "ar", "services": ["دورات تداول"]},
        strategy={
            "marketing_intelligence": {
                "personas": [
                    {
                        "id": "persona-1",
                        "name": "ليان",
                        "age": 28,
                        "gender": "female",
                        "economic_status": "متوسطة",
                        "profession": "صاحبة مشروع",
                        "challenge": "تحدي",
                        "need": "حاجة",
                        "motivation": "دافع",
                        "solution": "حل",
                    }
                ]
            }
        },
    )
    user = User(id="user-1", email="owner@example.com", full_name="Owner", hashed_password="x")
    db = FakeDb()

    async def fake_get_owned_suite(*_args, **_kwargs):
        return suite

    async def fake_generate_personas(suite_arg, language, *_args, existing_persona_values=None, append=False, **_kwargs):
        assert language == "ar"
        assert existing_persona_values == ["ليان"]
        assert append is True
        existing = marketing_plans.normalize_marketing_intelligence(
            suite_arg.strategy["marketing_intelligence"],
            marketing_plans.suite_research_payload(suite_arg),
            language,
        )
        return {
            **existing,
            "phase": "personas",
            "status": "personas_ready",
            "personas": [
                *existing["personas"],
                *[
                    {
                        "id": f"persona-more-{index}",
                        "name": f"عميل إضافي {index}",
                        "age": 35 + index,
                        "gender": "male",
                        "economic_status": "مستقرة",
                        "profession": "مستقل",
                        "challenge": "تحدي إضافي",
                        "need": "حاجة إضافية",
                        "motivation": "دافع إضافي",
                        "solution": "حل إضافي",
                    }
                    for index in range(1, 6)
                ],
            ],
        }

    async def fake_record_provider_usage(*_args, **_kwargs):
        return None

    async def fake_record_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(marketing_plans, "get_owned_suite", fake_get_owned_suite)
    monkeypatch.setattr(marketing_plans, "generate_marketing_customer_personas_research", fake_generate_personas)
    monkeypatch.setattr(marketing_plans, "record_provider_usage", fake_record_provider_usage)
    monkeypatch.setattr(marketing_plans, "record_audit_log", fake_record_audit_log)

    response = await marketing_plans.generate_marketing_personas(
        "suite-1",
        marketing_plans.MarketingStageRequest(language="ar", existing_values=["ليان"]),
        user,
        db,  # type: ignore[arg-type]
    )

    personas = response["intelligence"]["personas"]
    assert len(personas) == 6
    assert personas[0]["name"] == "ليان"
    assert personas[-1]["name"] == "عميل إضافي 5"


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
        marketing_plans.CompetitorClassificationRequest(classification_tags=["good_competitor", "not_competitor", "local_competitor"]),
        user,
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert response["intelligence"]["competitors"][0]["classification_tags"] == ["not_competitor"]
