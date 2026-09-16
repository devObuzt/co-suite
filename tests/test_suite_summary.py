from api.models.suite import Suite
from api.services.suite_summary import suite_summary


def _suite(**over) -> Suite:
    suite = Suite(id="s1", owner_id="u1", name="Afkar", slug="afkar")
    suite.organization_id = "o1"
    suite.brand = {"description": "healthy food", "tagline": "eat well", "services": ["catering"], "logo_url": "x"}
    suite.strategy = {
        "marketing_plan": {
            "audience": {
                "problem": "no time to cook",
                "demographics": {"age": "25-45", "gender": "all", "language": "ar", "social_status": "working"},
                "personas": [{"name": "Sara", "age": 34, "profession": "nurse", "needs": "fast", "challenges": "shifts"}],
            },
            "keywords": ["healthy", "delivery"],
            "content_themes": ["recipes"],
        },
        "marketing_message": "eat well without cooking",
        "language": "ar",
    }
    for key, value in over.items():
        setattr(suite, key, value)
    return suite


def test_summary_publishes_the_contract_shape():
    out = suite_summary(_suite())

    assert out["suite"]["id"] == "s1"
    assert out["brand"]["tagline"] == "eat well"
    assert out["audience"]["language"] == "ar"
    assert out["audience"]["demographics"]["age"] == "25-45"
    assert out["audience"]["personas"][0]["name"] == "Sara"
    assert out["audience"]["keywords"] == ["healthy", "delivery"]
    assert out["marketing_message"] == "eat well without cooking"
    assert out["content_themes"] == ["recipes"]


def test_summary_survives_a_suite_with_no_strategy_yet():
    out = suite_summary(_suite(strategy=None, brand=None))

    assert out["suite"]["id"] == "s1"
    assert out["brand"] == {"description": "", "tagline": "", "services": []}
    assert out["audience"]["personas"] == []
    assert out["marketing_message"] == ""


def test_summary_never_leaks_connections_or_tokens():
    suite = _suite()
    suite.connections = {"meta_user_token": "EAA-secret", "facebook": {"page_access_token": "EAA-secret"}}

    assert "EAA-secret" not in str(suite_summary(suite))


def test_summary_carries_no_key_outside_the_contract():
    out = suite_summary(_suite())

    assert set(out) == {"suite", "brand", "audience", "marketing_message", "content_themes"}
    assert set(out["audience"]) == {"language", "demographics", "problem", "personas", "keywords"}
