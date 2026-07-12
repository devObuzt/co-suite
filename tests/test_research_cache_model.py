def test_research_cache_model_has_expected_columns():
    from api.models.research_cache import ResearchCache
    cols = set(ResearchCache.__table__.columns.keys())
    assert {
        "id", "kind", "country", "language", "period", "data", "source",
        "created_at", "refreshed_at", "expires_at",
    } <= cols


def test_research_cache_has_composite_unique_constraint():
    from api.models.research_cache import ResearchCache
    uniques = [
        c for c in ResearchCache.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any(
        {"kind", "country", "language", "period"} == {col.name for col in u.columns}
        for u in uniques
    )


def test_research_cache_registered_in_models_package():
    import api.models as models
    assert hasattr(models, "ResearchCache")
