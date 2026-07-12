from api.routers.marketing_plans import _update_social_ideas_selection, _social_ideas_plan


class _Suite:
    def __init__(self, strategy):
        self.strategy = strategy


def _suite_with_candidates():
    plan = {
        "candidates": [
            {"id": "a", "title": "A", "selected": False, "user_notes": "",
             "apply_assets": [{"asset_type": "image", "recommended": True},
                              {"asset_type": "carousel", "recommended": False}]},
            {"id": "b", "title": "B", "selected": False, "user_notes": "",
             "apply_assets": [{"asset_type": "ugc", "recommended": True}]},
        ],
        "selected_ids": [],
    }
    return _Suite({"marketing_action_plan": {"social_ideas_plan": plan}})


def test_selection_marks_selected_notes_and_assets():
    suite = _suite_with_candidates()
    _update_social_ideas_selection(
        suite, selected_ids=["a"], notes={"a": "خلي التركيز عالعرض"},
        assets={"a": ["carousel"]},
    )
    plan = _social_ideas_plan(suite)
    by_id = {c["id"]: c for c in plan["candidates"]}
    assert by_id["a"]["selected"] is True
    assert by_id["b"]["selected"] is False
    assert by_id["a"]["user_notes"] == "خلي التركيز عالعرض"
    # asset recommendation now reflects the user's pick (carousel on, image off)
    rec = {a["asset_type"]: a["recommended"] for a in by_id["a"]["apply_assets"]}
    assert rec == {"image": False, "carousel": True}
    assert plan["selected_ids"] == ["a"]


def test_selection_persists_to_suite_strategy():
    suite = _suite_with_candidates()
    _update_social_ideas_selection(suite, selected_ids=["b"], notes={}, assets={})
    # reassigned onto suite.strategy (SQLAlchemy JSON change detection)
    assert suite.strategy["marketing_action_plan"]["social_ideas_plan"]["selected_ids"] == ["b"]
