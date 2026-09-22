

def test_the_sanitizer_drops_every_token_shaped_key():
    from api.routers.connections import _safe_connections

    safe = _safe_connections({
        "facebook": {"page_id": "p1", "page_access_token": "EAA-secret"},
        "meta_ads": {"ad_account_id": "act_1", "user_access_token": "EAA-secret"},
        "meta_user_token": "EAA-secret",
        "google": "not-a-dict",
    })

    assert "EAA-secret" not in str(safe)
    assert safe["facebook"] == {"page_id": "p1"}
    assert safe["meta_ads"] == {"ad_account_id": "act_1"}
    # The Meta callback parks `meta_user_token` at the top level between
    # connecting and picking a Page; the nested-only sanitizer handed it back.
    assert "meta_user_token" not in safe
    assert safe["google"] == "not-a-dict"
