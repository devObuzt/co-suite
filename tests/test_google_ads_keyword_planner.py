from api.services import google_ads


def test_normalize_keyword_idea_extracts_historical_metrics():
    raw = {
        "text": "dental clinic",
        "keywordIdeaMetrics": {
            "avgMonthlySearches": "1200",
            "competition": "HIGH",
            "competitionIndex": "82",
            "lowTopOfPageBidMicros": "1500000",
            "highTopOfPageBidMicros": "5200000",
            "monthlySearchVolumes": [
                {"year": "2026", "month": "MAY", "monthlySearches": "1300"},
            ],
        },
    }

    item = google_ads.normalize_keyword_idea(raw, source="google_suggested")

    assert item["keyword"] == "dental clinic"
    assert item["source"] == "google_suggested"
    assert item["average_monthly_searches"] == 1200
    assert item["competition"] == "HIGH"
    assert item["competition_index"] == 82
    assert item["low_top_of_page_bid"] == 1.5
    assert item["high_top_of_page_bid"] == 5.2
    assert item["monthly_search_volumes"][0]["monthly_searches"] == 1300


def test_build_keyword_planner_summary_scores_demand_and_competition():
    items = [
        {"keyword": "a", "average_monthly_searches": 100, "competition_index": 20, "competition": "LOW"},
        {"keyword": "b", "average_monthly_searches": 900, "competition_index": 80, "competition": "HIGH"},
    ]

    summary = google_ads.build_keyword_planner_summary(items)

    assert summary["analyzed_keywords"] == 2
    assert summary["average_monthly_searches"] == 500
    assert summary["average_competition_index"] == 50
    assert summary["competition_level"] == "MEDIUM"
    assert summary["demand_level"] == "MEDIUM"


def test_geo_target_constants_handles_structured_arabic_israel_location():
    location = {"scope": "custom", "countries": ["إسرائيل"], "cities": []}

    assert google_ads.geo_target_constants(location) == ["geoTargetConstants/2376"]


def test_geo_target_constants_does_not_match_us_inside_countries():
    location = {"scope": "custom", "countries": ["Jordan"], "cities": []}

    assert google_ads.geo_target_constants(location) == ["geoTargetConstants/2400"]


def test_google_ads_error_detail_includes_field_and_error_code():
    payload = {
        "error": {
            "message": "Request contains an invalid argument.",
            "details": [
                {
                    "errors": [
                        {
                            "errorCode": {"requestError": "RESOURCE_NAME_MALFORMED"},
                            "message": "Invalid resource name.",
                            "location": {"fieldPathElements": [{"fieldName": "language"}]},
                        }
                    ]
                }
            ],
        }
    }

    detail = google_ads._google_ads_error_detail(payload)

    assert "Request contains an invalid argument" in detail
    assert "requestError: RESOURCE_NAME_MALFORMED" in detail
    assert "language" in detail
    assert "Invalid resource name" in detail


def test_google_ads_headers_omit_login_customer_when_same_customer(monkeypatch):
    monkeypatch.setattr(google_ads.settings, "google_ads_login_customer_id", "123-456-7890")
    monkeypatch.setattr(google_ads.settings, "google_ads_developer_token", "dev-token")

    headers = google_ads._headers("access-token", "1234567890")

    assert headers["developer-token"] == "dev-token"
    assert "login-customer-id" not in headers


def test_keyword_planner_empty_response_returns_warning(monkeypatch):
    async def fake_refresh_google_ads_access_token(_refresh_token):
        return "access-token"

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"results": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(google_ads, "refresh_google_ads_access_token", fake_refresh_google_ads_access_token)
    monkeypatch.setattr(google_ads.httpx, "AsyncClient", FakeClient)

    import asyncio

    result = asyncio.run(
        google_ads.fetch_keyword_planner_ideas(
            "1234567890",
            "refresh-token",
            ["dental clinic"],
            "en",
            "Israel",
        )
    )

    assert result["keyword_metrics"] == []
    assert "No keyword ideas" in result["warning"]
