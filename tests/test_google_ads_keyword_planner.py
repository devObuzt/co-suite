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
