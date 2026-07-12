import json
import pytest
from unittest.mock import AsyncMock, patch

from api.services.social_ideas_generator import (
    normalize_idea, parse_ideas, fallback_ideas, build_ideas_prompt, APPLY_ASSET_TYPES,
)


def test_normalize_idea_coerces_and_guarantees_recommended():
    idea = normalize_idea({
        "objective_type": "weird",
        "title": "  تحدّي المونديال  ",
        "description": "مسابقة تفاعلية",
        "apply_assets": [{"asset_type": "talking_head"}, "carousel", {"asset_type": "not_real"}],
        "client_story": "قصة",
        "occasion_ref": "مونديال 2026",
    }, index=3)
    assert idea["objective_type"] == "attraction"        # unknown -> default
    assert idea["title"] == "تحدّي المونديال"
    assert idea["short_description"] == "مسابقة تفاعلية"
    types = [a["asset_type"] for a in idea["apply_assets"]]
    assert types == ["talking_head", "carousel"]         # invalid dropped, string coerced
    assert any(a["recommended"] for a in idea["apply_assets"])  # a middle default is guaranteed
    assert idea["client_story"] == {"text": "قصة", "example": "", "is_illustrative": True}
    assert idea["occasion_ref"]["title"] == "مونديال 2026"
    assert idea["selected"] is False


def test_normalize_idea_rejects_titleless():
    assert normalize_idea({"title": "  "}) is None
    assert normalize_idea("notadict") is None


def test_normalize_idea_defaults_asset_when_none_valid():
    idea = normalize_idea({"title": "X", "apply_assets": []})
    assert idea["apply_assets"] == [{"asset_type": "image", "recommended": True}]


def test_parse_ideas_extracts_and_normalizes():
    raw = 'noise {"ideas":[{"title":"A","objective_type":"trust"},{"title":""},{"title":"B"}]} tail'
    ideas = parse_ideas(raw)
    assert [i["title"] for i in ideas] == ["A", "B"]
    assert ideas[0]["objective_type"] == "trust"


def test_parse_ideas_salvages_truncated_json():
    # A response cut off mid-array (no closing ] or }) — must keep the complete ones.
    truncated = ('{"ideas":[{"title":"A","objective_type":"attraction"},'
                 '{"title":"B با قوسين } جوا نص","objective_type":"trust"},'
                 '{"title":"C","short_desc')  # last object truncated
    ideas = parse_ideas(truncated)
    assert [i["title"] for i in ideas] == ["A", "B با قوسين } جوا نص"]


def test_fallback_ideas_shapes_and_uses_occasions():
    occ = [{"title": "عيد الأضحى", "type": "religious", "date_or_window": "2026-08"}]
    ideas = fallback_ideas(3, occ, "ar")
    assert len(ideas) == 3
    assert ideas[0]["occasion_ref"]["title"] == "عيد الأضحى"
    assert all(any(a["recommended"] for a in i["apply_assets"]) for i in ideas)


def test_objective_split_is_70_20_10():
    from api.services.social_ideas_generator import _objective_split
    s = _objective_split(24)
    assert s == {"attraction": 17, "trust": 5, "sales": 2}
    assert sum(s.values()) == 24
    assert _objective_split(6)["sales"] >= 1   # sales never zero


def test_build_ideas_prompt_requests_ideas_not_content_and_lists_occasions():
    ctx = {"name": "X", "audience_language": "Arabic", "dialect": "Palestinian",
           "products_services": [], "target_audience": {}, "marketing_offer": "", "marketing_message": ""}
    occ = [{"title": "المونديال 2026", "type": "sports", "date_or_window": "2026-06"}]
    prompt = build_ideas_prompt(ctx, occ, {"audience_behavior": ""}, target_count=12, period="2026-08", language="ar")
    assert "IDEAS (NOT finished posts" in prompt
    assert "المونديال 2026" in prompt
    assert "24" in prompt                       # 2x over-generation
    for t in APPLY_ASSET_TYPES:
        assert t in prompt                       # full asset taxonomy offered


@pytest.mark.asyncio
async def test_generate_social_ideas_orchestration_success():
    from api.services import social_ideas_generator as gen
    suite = type("S", (), {"id": "s1", "brand": {"name": "X", "location": "Israel"}, "strategy": {}})()
    llm = json.dumps({"ideas": [{"title": f"idea{i}", "objective_type": "attraction"} for i in range(24)]})
    with patch.object(gen, "infer_plan_language", return_value="ar"), \
         patch.object(gen, "suite_research_payload", return_value={"brand": {"location": "Israel"}}), \
         patch.object(gen, "_social_content_plan_context", return_value={"audience_language": "Arabic", "target_audience": {"location": "Israel"}}), \
         patch.object(gen, "get_occasions", AsyncMock(return_value=[{"title": "عيد", "type": "religious", "confidence": "high"}])), \
         patch.object(gen, "get_market_research", AsyncMock(return_value={"audience_behavior": ""})), \
         patch.object(gen, "call_text_ai", AsyncMock(return_value=llm)):
        out = await gen.generate_social_ideas(db=object(), suite=suite, period="2026-08", target_count=12)
    assert out["version"] == "social_ideas_v1"
    assert out["target_count"] == 12
    assert len(out["candidates"]) == 24
    assert out["warnings"] == []


@pytest.mark.asyncio
async def test_generate_social_ideas_falls_back_on_llm_failure():
    from api.services import social_ideas_generator as gen
    suite = type("S", (), {"id": "s1", "brand": {}, "strategy": {}})()
    with patch.object(gen, "infer_plan_language", return_value="ar"), \
         patch.object(gen, "suite_research_payload", return_value={"brand": {}}), \
         patch.object(gen, "_social_content_plan_context", return_value={"audience_language": "Arabic", "target_audience": {}}), \
         patch.object(gen, "get_occasions", AsyncMock(return_value=[])), \
         patch.object(gen, "get_market_research", AsyncMock(return_value={})), \
         patch.object(gen, "call_text_ai", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await gen.generate_social_ideas(db=object(), suite=suite, period="2026-08", target_count=6)
    assert "generation_failed" in out["warnings"]
    assert len(out["candidates"]) == 12          # 2x fallback
    assert all(c["title"] for c in out["candidates"])
