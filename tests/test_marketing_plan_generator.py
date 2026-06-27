import json

import pytest

from api.models.suite import Suite
from api.services import marketing_plan_generator as mpg


def make_suite() -> Suite:
    return Suite(
        id="suite-1",
        owner_id="user-1",
        name="Connec",
        slug="connec",
        brand={
            "name": "Connec",
            "industry": "Digital marketing",
            "audience_languages": ["ar", "he"],
            "services": ["Social media", "Websites"],
        },
        strategy={"marketing_message": "Clear growth for local businesses"},
        connections={"instagram": {"connected": True, "username": "connec.co.il"}},
    )


def test_infer_plan_language_normalizes_arabic_language_name():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Arabic Suite",
        slug="arabic-suite",
        brand={"audience_languages": ["العربية"]},
        strategy={},
        connections={},
    )

    assert mpg.infer_plan_language(suite) == "ar"


def complete_plan_payload(title: str = "Connec plan") -> dict:
    return {
        "cover": {"title": title, "subtitle": "Practical growth"},
        "research_summary": {
            "sources_used": ["manual profile", "instagram", "website"],
            "limitations": ["Validate budget and current campaign priorities"],
        },
        "monthly_work_plan": {
            "daily_story_direction": ["Show daily proof", "Answer common questions", "Publish clear offers"],
            "items": [
                {
                    "title": f"Content item {i}",
                    "prompt": f"Create content item {i}",
                    "recommended_output": {"format": "image"},
                }
                for i in range(1, 9)
            ],
        },
        "paid_funnel": {
            "stages": [
                {
                    "stage": stage,
                    "goal": f"Goal for {stage}",
                    "content_ideas": [
                        {"title": f"{stage} idea 1", "recommended_outputs": ["video"], "prompt": "Create video"},
                        {"title": f"{stage} idea 2", "recommended_outputs": ["image"], "prompt": "Create image"},
                    ],
                }
                for stage in mpg.FUNNEL_STAGES
            ]
        },
        "sections": [
            {
                "id": section_id,
                "title": section_title,
                "summary": f"Summary for {section_title}",
                "bullets": ["First practical point", "Second practical point", "Third practical point"],
                "cards": [{"title": "Recommendation", "body": "A useful action", "points": ["Start here"]}],
                "metrics": [{"label": "Metric", "value": "Weekly target"}],
            }
            for section_id, section_title in mpg.REQUIRED_SECTIONS
        ],
    }


def test_normalize_marketing_plan_deck_adds_required_sections():
    deck = mpg.normalize_marketing_plan_deck(
        {
            "cover": {"title": "Connec growth plan", "chips": ["Social", "Search"]},
            "sections": [
                {
                    "id": "executive_summary",
                    "title": "Summary",
                    "summary": "A focused plan.",
                    "bullets": ["Win with clarity"],
                }
            ],
        },
        "Connec",
        "ar",
    )

    section_ids = [section["id"] for section in deck["sections"]]
    assert deck["version"] == mpg.PLAN_VERSION
    assert deck["language"] == "ar"
    assert deck["cover"]["title"] == "Connec growth plan"
    assert "executive_summary" in section_ids
    assert "competitors" in section_ids
    assert "budget" in section_ids


def test_build_marketing_plan_partial_result_exposes_market_before_full_deck():
    suite = make_suite()
    partial = mpg.build_marketing_plan_partial_result(suite, "ar")

    assert partial["partial"]["intelligence_ready"] is True
    assert partial["partial"]["deck_ready"] is False
    assert partial["stages"][0]["id"] == "research"
    assert partial["stages"][1]["id"] == "market"
    assert partial["stages"][1]["status"] == "completed"
    assert partial["stages"][2]["status"] == "running"
    assert partial["intelligence"]["competitors"]
    assert partial["intelligence"]["demand_signals"]


def test_normalize_marketing_plan_deck_preserves_monthly_work_plan_and_paid_funnel():
    deck = mpg.normalize_marketing_plan_deck(
        {
            "cover": {"title": "Connec monthly plan"},
            "monthly_work_plan": {
                "client_focus_questions": ["Do you have products or campaigns to push this month?"],
                "calendar_context": {
                    "countries": ["Israel"],
                    "religions_considered": ["Islam", "Judaism", "Christianity"],
                    "seasonal_notes": ["Check local holidays before scheduling offers."],
                },
                "content_mix": [
                    {"type": "attraction", "percentage": 70},
                    {"type": "trust", "percentage": 20},
                    {"type": "sales", "percentage": 10},
                ],
                "items": [
                    {
                        "id": "week-1-reel",
                        "title": "Founder trust reel",
                        "objective": "trust",
                        "platforms": ["instagram", "facebook"],
                        "placement": "reel",
                        "recommended_output": {"format": "video", "production_mode": "talking_head"},
                        "prompt": "Create a warm founder reel.",
                        "needs_user_asset": True,
                    }
                ],
            },
            "paid_funnel": {
                "stages": [
                    {
                        "stage": "Awareness",
                        "goal": "Reach relevant local audiences",
                        "content_ideas": [
                            {
                                "title": "Problem opener",
                                "recommended_outputs": ["video", "image"],
                                "prompt": "Create awareness ads.",
                            }
                        ],
                    }
                ]
            },
            "sections": [],
        },
        "Connec",
        "ar",
    )

    assert deck["monthly_work_plan"]["content_mix"] == [
        {"type": "attraction", "percentage": 70},
        {"type": "trust", "percentage": 20},
        {"type": "sales", "percentage": 10},
    ]
    assert deck["monthly_work_plan"]["items"][0]["recommended_output"]["format"] == "video"
    assert deck["monthly_work_plan"]["items"][0]["generation_request"]["content_type"] == "video"
    assert deck["paid_funnel"]["stages"][0]["stage"] == "Awareness"
    assert deck["paid_funnel"]["stages"][0]["content_ideas"][0]["generation_request"]["content_type"] == "mixed"


def test_normalize_marketing_plan_deck_expands_social_plan_to_recommended_monthly_cadence():
    payload = complete_plan_payload()
    payload["monthly_work_plan"]["recommended_weekly_posts"] = 3
    payload["monthly_work_plan"]["cadence_reason"] = "The client has enough owned channels for three focused posts per week."

    deck = mpg.normalize_marketing_plan_deck(payload, "Connec", "ar")
    monthly = deck["monthly_work_plan"]

    assert monthly["recommended_weekly_posts"] == 3
    assert monthly["recommended_monthly_posts"] == 12
    assert "three focused posts" in monthly["cadence_reason"]
    assert len(monthly["items"]) >= 12


def test_normalize_marketing_plan_deck_keeps_real_world_production_modes_not_ai_only():
    payload = complete_plan_payload()
    payload["monthly_work_plan"]["items"] = [
        {
            "title": "Founder explainer",
            "placement": "reel",
            "recommended_output": {"format": "video", "production_mode": "talking_head"},
            "prompt": "Record the founder explaining the offer.",
            "needs_user_asset": True,
        },
        {
            "title": "Office trust walkthrough",
            "placement": "reel",
            "recommended_output": {"format": "video", "production_mode": "office_video"},
            "prompt": "Film the office and team.",
            "needs_user_asset": True,
        },
        {
            "title": "Product/service proof",
            "placement": "post",
            "recommended_output": {"format": "image", "production_mode": "product_photo"},
            "prompt": "Use real product or service proof.",
            "needs_user_asset": True,
        },
    ]

    deck = mpg.normalize_marketing_plan_deck(payload, "Connec", "ar")
    modes = [item["recommended_output"]["production_mode"] for item in deck["monthly_work_plan"]["items"]]
    action_plan = mpg.normalize_marketing_action_plan({}, deck, "ar")

    assert {"talking_head", "office_video", "product_photo"}.issubset(set(modes))
    assert {"human_video", "location_video", "product_photos"}.issubset(
        {asset for item in action_plan["social_items"] for asset in item["required_assets"]}
    )


def test_build_marketing_plan_prompt_requests_required_json_and_language():
    prompt = mpg.build_marketing_plan_prompt(
        {
            "suite": {"name": "Connec"},
            "planning_inputs": {
                "near_term_focus": "Push summer website offers",
                "upcoming_campaigns": ["June lead campaign"],
            },
        },
        "ar",
    )

    assert "Return ONLY valid JSON" in prompt
    assert "Arabic" in prompt
    assert "Push summer website offers" in prompt
    assert "June lead campaign" in prompt
    assert "competitors" in prompt
    assert "market_demand" in prompt
    assert "kpis" in prompt
    assert "70% attraction" in prompt
    assert "Awareness" in prompt
    assert "monthly_work_plan" in prompt


def test_build_marketing_plan_prompt_can_request_strategy_only_without_execution_sections():
    prompt = mpg.build_marketing_plan_prompt(
        {
            "suite": {"name": "Connec"},
            "planning_inputs": {"near_term_focus": "Build the core positioning first"},
        },
        "ar",
        include_execution_sections=False,
    )

    assert "Return ONLY valid JSON" in prompt
    assert "Arabic" in prompt
    assert "Build the core positioning first" in prompt
    assert "competitors" in prompt
    assert "market_demand" in prompt
    assert "monthly_work_plan" not in prompt
    assert "paid_funnel" not in prompt
    assert "70% attraction" not in prompt
    assert "Awareness" not in prompt


def test_build_marketing_competitor_research_prompt_requests_only_competitors():
    prompt = mpg.build_marketing_competitor_research_prompt(
        {
            "suite": {"name": "Connec"},
            "brand": {"services": ["Websites"]},
            "planning_inputs": {"near_term_focus": "Show competitors first"},
        },
        "ar",
    )

    assert "Return STRICT JSON only" in prompt
    assert "Arabic" in prompt
    assert "competitors" in prompt
    assert "source_links" in prompt
    assert "Do not create demand_signals" in prompt
    assert "supply_signals" not in prompt
    assert "Show competitors first" in prompt


def test_build_marketing_demand_supply_prompt_uses_existing_competitors():
    prompt = mpg.build_marketing_demand_supply_prompt(
        {"suite": {"name": "Connec"}},
        {
            "competitors": [
                {"name": "Market Peer", "platform": "instagram", "url": "https://example.com/peer"}
            ]
        },
        "he",
    )

    assert "Hebrew" in prompt
    assert "Market Peer" in prompt
    assert "demand_signals" in prompt
    assert "supply_signals" in prompt
    assert "opportunities" in prompt
    assert "Do not replace the competitor list" in prompt


def test_normalize_marketing_intelligence_preserves_customer_personas():
    payload = mpg.suite_research_payload(make_suite())

    intelligence = mpg.normalize_marketing_intelligence(
        {
            "phase": "personas",
            "keywords": [{"text": "إدارة سوشيال"}],
            "competitors": [{"name": "Market peer", "url": "https://peer.example"}],
            "personas": [
                {
                    "name": "ليان",
                    "age": 28,
                    "gender": "female",
                    "economic_status": "متوسطة",
                    "profession": "صاحبة مشروع صغير",
                    "challenge": "لا تعرف كيف تحول المتابعين لعملاء.",
                    "need": "عرض واضح وسهل الفهم.",
                    "motivation": "تريد نمو مبيعات بدون هدر ميزانية.",
                    "solution": "نوضح العرض ونبني محتوى يقود للاستفسار.",
                }
            ],
        },
        payload,
        "ar",
    )

    assert intelligence["status"] == "personas_ready"
    assert intelligence["keywords"][0]["text"] == "إدارة سوشيال"
    assert intelligence["competitors"][0]["name"] == "Market peer"
    persona = intelligence["personas"][0]
    assert persona["name"] == "ليان"
    assert persona["age"] == 28
    assert persona["economic_status"] == "متوسطة"
    assert persona["avatar_seed"]


def test_build_customer_personas_prompt_requests_ten_diverse_profiles():
    prompt = mpg.build_marketing_customer_personas_prompt(
        mpg.suite_research_payload(make_suite()),
        {"keywords": [{"text": "إدارة سوشيال"}], "competitors": [{"name": "Market peer"}]},
        "ar",
    )

    assert "10" in prompt
    assert "personas" in prompt
    assert "economic_status" in prompt
    assert "profession" in prompt
    assert "challenge" in prompt
    assert "motivation" in prompt
    assert "solution" in prompt
    assert "Arabic" in prompt


@pytest.mark.asyncio
async def test_generate_marketing_customer_personas_returns_diverse_fallback_when_ai_fails(monkeypatch):
    suite = make_suite()

    async def failing_call_text_ai(**_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mpg, "call_text_ai", failing_call_text_ai)

    intelligence = await mpg.generate_marketing_customer_personas_research(suite, "ar")

    personas = intelligence["personas"]
    assert intelligence["status"] == "personas_ready"
    assert len(personas) == 10
    assert len({item["gender"] for item in personas}) >= 2
    assert len({item["economic_status"] for item in personas}) >= 3
    assert len({item["profession"] for item in personas}) >= 5
    assert all(item["challenge"] and item["need"] and item["motivation"] and item["solution"] for item in personas)
    assert all(item["avatar_seed"] for item in personas)


def test_competitor_only_intelligence_does_not_fill_demand_supply_fallbacks():
    payload = mpg.suite_research_payload(make_suite())

    intelligence = mpg.normalize_marketing_intelligence(
        {
            "phase": "competitors",
            "competitors": [{"name": "Market Peer", "platform": "instagram"}],
        },
        payload,
        "en",
    )

    assert intelligence["status"] == "competitors_ready"
    assert intelligence["competitors"][0]["name"] == "Market Peer"
    assert intelligence["demand_signals"] == []
    assert intelligence["supply_signals"] == []
    assert intelligence["opportunities"] == []


@pytest.mark.asyncio
async def test_generate_marketing_competitor_research_returns_starter_results_when_ai_fails(monkeypatch):
    async def fake_call_text_ai(**kwargs):
        raise RuntimeError("provider is down")

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    intelligence = await mpg.generate_marketing_competitor_research(make_suite(), "ar")

    assert intelligence["status"] == "competitors_ready"
    assert intelligence["competitors"]
    assert all(item.get("research_lead") for item in intelligence["competitors"])
    assert intelligence["demand_signals"] == []
    assert any("provider" in warning.lower() or "ai" in warning.lower() for warning in intelligence["warnings"])


@pytest.mark.asyncio
async def test_generate_marketing_demand_supply_research_returns_profile_signals_when_ai_fails(monkeypatch):
    async def fake_call_text_ai(**kwargs):
        raise RuntimeError("provider is down")

    suite = make_suite()
    suite.strategy = {
        "marketing_intelligence": {
            "phase": "competitors",
            "competitors": [{"name": "Market Peer", "platform": "instagram"}],
        }
    }
    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    intelligence = await mpg.generate_marketing_demand_supply_research(suite, "en")

    assert intelligence["status"] == "ready"
    assert intelligence["competitors"][0]["name"] == "Market Peer"
    assert intelligence["demand_signals"]
    assert intelligence["supply_signals"]
    assert intelligence["opportunities"]
    assert any("provider" in warning.lower() or "ai" in warning.lower() for warning in intelligence["warnings"])


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_uses_anthropic(monkeypatch):
    calls = {}

    async def fake_call_text_ai(**kwargs):
        calls.update(kwargs)
        return json.dumps(complete_plan_payload())

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "he")

    assert calls["provider"] == "anthropic"
    assert calls["model"] == mpg.settings.anthropic_text_model
    assert calls["max_tokens"] == mpg.MARKETING_PLAN_MAX_TOKENS
    assert calls["timeout"] == mpg.MARKETING_PLAN_TIMEOUT_SECONDS
    assert deck["language"] == "he"
    assert deck["cover"]["title"] == "Connec plan"


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_can_return_strategy_before_execution_sections(monkeypatch):
    calls = {}
    payload = complete_plan_payload()
    payload.pop("monthly_work_plan")
    payload.pop("paid_funnel")

    async def fake_call_text_ai(**kwargs):
        calls.update(kwargs)
        return json.dumps(payload)

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "ar", include_execution_sections=False)

    prompt = calls["messages"][0]["content"]
    assert "monthly_work_plan" not in prompt
    assert "paid_funnel" not in prompt
    assert deck["status"] == "ready"
    assert deck["partial"]["deck_ready"] is True
    assert deck["partial"]["social_plan_ready"] is False
    assert deck["partial"]["paid_funnel_ready"] is False
    assert "monthly_work_plan" not in deck
    assert "paid_funnel" not in deck
    mpg.validate_marketing_plan_deck(deck, require_execution_sections=False)


@pytest.mark.asyncio
async def test_generate_marketing_plan_execution_section_returns_only_requested_social_plan(monkeypatch):
    calls = {}

    async def fake_call_text_ai(**kwargs):
        calls.update(kwargs)
        return json.dumps({"monthly_work_plan": complete_plan_payload()["monthly_work_plan"]})

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    section = await mpg.generate_marketing_plan_execution_section(make_suite(), "ar", "social")

    prompt = calls["messages"][0]["content"]
    assert "monthly_work_plan" in prompt
    assert "paid_funnel" not in prompt
    assert len(section["items"]) >= 8
    assert section["items"][0]["generation_request"]["mode"] == "quick"


@pytest.mark.asyncio
async def test_generate_marketing_plan_execution_section_returns_only_requested_ads_funnel(monkeypatch):
    calls = {}

    async def fake_call_text_ai(**kwargs):
        calls.update(kwargs)
        return json.dumps({"paid_funnel": complete_plan_payload()["paid_funnel"]})

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    section = await mpg.generate_marketing_plan_execution_section(make_suite(), "he", "ads")

    prompt = calls["messages"][0]["content"]
    assert "paid_funnel" in prompt
    assert "monthly_work_plan" not in prompt
    assert section["stages"][0]["stage"] == "Awareness"
    assert section["stages"][0]["content_ideas"][0]["generation_request"]["content_type"] == "video"


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_uses_rule_based_fallback_when_ai_json_fails(monkeypatch):
    calls = []

    async def fake_call_text_ai(**kwargs):
        calls.append(kwargs)
        return "{}"

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "ar")

    assert len(calls) == 4
    assert deck["cover"]["title"] == "الخطة التسويقية – Connec"
    assert len(deck["sections"]) >= len(mpg.REQUIRED_SECTIONS)
    assert len(deck["monthly_work_plan"]["items"]) >= 12
    assert all(len(stage["content_ideas"]) == 2 for stage in deck["paid_funnel"]["stages"])
    mpg.validate_marketing_plan_deck(deck)


def test_validate_marketing_plan_deck_rejects_title_only_skeleton():
    deck = mpg.normalize_marketing_plan_deck({}, "Connec", "ar")

    with pytest.raises(mpg.MarketingPlanGenerationError):
        mpg.validate_marketing_plan_deck(deck)


def test_validate_marketing_plan_deck_rejects_monthly_only_empty_sections():
    payload = complete_plan_payload()
    payload["paid_funnel"] = {"stages": [{"stage": stage, "goal": f"Goal {stage}"} for stage in mpg.FUNNEL_STAGES]}
    payload["sections"] = [{"id": section_id, "title": title} for section_id, title in mpg.REQUIRED_SECTIONS]
    deck = mpg.normalize_marketing_plan_deck(payload, "Connec", "ar")

    with pytest.raises(mpg.MarketingPlanGenerationError, match="empty sections"):
        mpg.validate_marketing_plan_deck(deck)


def test_normalize_marketing_plan_deck_accepts_ai_field_aliases():
    payload = complete_plan_payload()
    payload["sections"] = [
        {
            "id": section_id,
            "name": section_title,
            "overview": f"Overview for {section_title}",
            "actions": [{"title": "Action", "description": "Do this next"}],
            "kpis": [{"name": "Lead signal", "target": "Weekly check"}],
        }
        for section_id, section_title in mpg.REQUIRED_SECTIONS
    ]
    payload["paid_funnel"] = {
        "stages": [
            {
                "name": stage,
                "objective": f"Objective {stage}",
                "ideas": [
                    {"headline": f"{stage} alt 1", "formats": ["video"], "description": "Video prompt"},
                    f"{stage} alt 2",
                ],
            }
            for stage in mpg.FUNNEL_STAGES
        ]
    }

    deck = mpg.normalize_marketing_plan_deck(payload, "Connec", "ar")

    assert deck["sections"][0]["summary"].startswith("Overview")
    assert deck["sections"][0]["bullets"] == ["Action"]
    assert deck["sections"][0]["cards"][0]["body"] == "Do this next"
    assert deck["sections"][0]["metrics"][0]["label"] == "Lead signal"
    assert deck["paid_funnel"]["stages"][0]["content_ideas"][0]["title"].endswith("alt 1")
    assert deck["paid_funnel"]["stages"][0]["content_ideas"][1]["prompt"].endswith("alt 2")
    mpg.validate_marketing_plan_deck(deck)


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_repairs_malformed_json(monkeypatch):
    calls = []
    repaired_payload = {
        "cover": {"title": "خطة Connec", "subtitle": "خطة نمو عملية"},
        "research_summary": {
            "sources_used": ["manual profile", "instagram", "website"],
            "limitations": ["تأكيد الأولويات الشهرية"],
        },
        "monthly_work_plan": {
            "daily_story_direction": ["اعرض دليل يومي", "اسأل سؤال عملي", "انشر نتيجة"],
            "items": [
                {"title": f"فكرة محتوى {i}", "prompt": f"ولّد فكرة {i}", "recommended_output": {"format": "image"}}
                for i in range(1, 9)
            ],
        },
        "paid_funnel": {
            "stages": [
                {
                    "stage": stage,
                    "goal": f"هدف {stage}",
                    "content_ideas": [
                        {"title": f"{stage} idea 1", "recommended_outputs": ["video"], "prompt": "prompt"},
                        {"title": f"{stage} idea 2", "recommended_outputs": ["image"], "prompt": "prompt"},
                    ],
                }
                for stage in mpg.FUNNEL_STAGES
            ]
        },
        "sections": [
            {
                "id": section_id,
                "title": title,
                "summary": f"ملخص {title}",
                "bullets": ["نقطة عملية", "نقطة ثانية"],
                "cards": [{"title": "بطاقة", "body": "شرح مختصر"}],
                "metrics": [{"label": "مؤشر", "value": "هدف"}],
            }
            for section_id, title in mpg.REQUIRED_SECTIONS
        ],
    }

    async def fake_call_text_ai(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return '{"cover": {"title": "broken"'
        return json.dumps(repaired_payload, ensure_ascii=False)

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "ar")

    assert len(calls) == 2
    assert "Repair the following marketing-plan response" in calls[1]["messages"][0]["content"]
    assert deck["cover"]["title"] == "خطة Connec"
    assert len(deck["monthly_work_plan"]["items"]) == 8


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_uses_compact_fallback_when_repair_fails(monkeypatch):
    calls = []
    compact_payload = {
        "cover": {"title": "خطة Connec المختصرة", "subtitle": "خطة عملية قابلة للتنفيذ"},
        "research_summary": {
            "sources_used": ["ملف البزنس", "صفحات السوشيال", "الموقع"],
            "limitations": ["تأكيد الميزانية وأولويات الشهر"],
        },
        "monthly_work_plan": {
            "client_focus_questions": ["ما العروض أو الخدمات التي تريد دفعها هذا الشهر؟"],
            "calendar_context": {
                "countries": ["Israel"],
                "religions_considered": ["Islam", "Judaism", "Christianity"],
                "seasonal_notes": ["افحص المناسبات المحلية قبل إطلاق العروض."],
            },
            "daily_story_direction": ["دليل يومي", "سؤال عملي", "نتيجة واضحة"],
            "items": [
                {
                    "title": f"محتوى عملي {i}",
                    "objective": "attraction",
                    "platforms": ["instagram", "facebook"],
                    "placement": "post",
                    "recommended_output": {"format": "image", "production_mode": "AI"},
                    "prompt": f"ولّد محتوى عملي {i}",
                }
                for i in range(1, 9)
            ],
        },
        "paid_funnel": {
            "stages": [
                {
                    "stage": stage,
                    "goal": f"هدف {stage}",
                    "content_ideas": [
                        {"title": f"{stage} 1", "recommended_outputs": ["video"], "prompt": "prompt"},
                        {"title": f"{stage} 2", "recommended_outputs": ["image"], "prompt": "prompt"},
                    ],
                }
                for stage in mpg.FUNNEL_STAGES
            ]
        },
        "sections": [
            {
                "id": section_id,
                "title": title,
                "summary": f"ملخص عملي عن {title}",
                "bullets": ["نقطة أولى", "نقطة ثانية", "نقطة ثالثة"],
                "cards": [{"title": "توصية", "body": "خطوة عملية", "points": ["ابدأ بقياس واضح"]}],
                "metrics": [{"label": "مؤشر", "value": "هدف أسبوعي"}],
            }
            for section_id, title in mpg.REQUIRED_SECTIONS
        ],
    }

    async def fake_call_text_ai(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return '{"cover": {"title": "broken"'
        if len(calls) == 2:
            return '{"still": "broken"'
        return json.dumps(compact_payload, ensure_ascii=False)

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "ar")

    assert len(calls) == 3
    assert "Repair the following marketing-plan response" in calls[1]["messages"][0]["content"]
    assert "Create a compact but useful marketing plan deck" in calls[2]["messages"][0]["content"]
    assert deck["cover"]["title"] == "خطة Connec المختصرة"
    assert len(deck["monthly_work_plan"]["items"]) == 8
    assert mpg.marketing_plan_content_score(deck) >= 18


def test_build_marketing_plan_prompt_compacts_large_payload():
    prompt = mpg.build_marketing_plan_prompt(
        {
            "suite": {"name": "Big payload"},
            "brand": {"notes": "x" * 40000},
        },
        "en",
    )

    assert len(prompt) < 26000
    assert "[truncated]" in prompt


def test_normalize_marketing_intelligence_derives_sources_and_warnings():
    suite = make_suite()
    suite.brand = {
        **suite.brand,
        "website": "https://connec.co.il",
        "social_links": {"instagram": "https://www.instagram.com/connec.co.il/"},
        "services": ["Websites", "Social media"],
    }
    payload = mpg.suite_research_payload(suite)

    intelligence = mpg.normalize_marketing_intelligence({}, payload, "ar")

    assert intelligence["version"] == mpg.INTELLIGENCE_VERSION
    assert intelligence["status"] in {"ready", "needs_research"}
    assert any(link["url"] == "https://connec.co.il" for link in intelligence["source_links"])
    assert any(signal["title"] == "Websites" for signal in intelligence["demand_signals"])
    assert len(intelligence["competitors"]) >= 4
    assert any(item["platform"] == "instagram" and item["url"] for item in intelligence["competitors"])
    assert intelligence["supply_signals"]
    assert intelligence["opportunities"]
    assert intelligence["warnings"]


def test_normalize_marketing_intelligence_uses_existing_competitors_before_research_leads():
    suite = make_suite()
    suite.strategy = {
        "competitors": [
            {
                "name": "Market Peer",
                "url": "https://www.instagram.com/market.peer/",
                "description": "A nearby business with active social content.",
            }
        ]
    }
    payload = mpg.suite_research_payload(suite)

    intelligence = mpg.normalize_marketing_intelligence({}, payload, "en")

    assert intelligence["competitors"][0]["name"] == "Market Peer"
    assert intelligence["competitors"][0]["platform"] == "instagram"
    assert not any(item.get("research_lead") for item in intelligence["competitors"])


def test_normalize_marketing_action_plan_converts_deck_items_to_executable_items():
    deck = mpg.normalize_marketing_plan_deck(complete_plan_payload(), "Connec", "ar")

    action_plan = mpg.normalize_marketing_action_plan({}, deck, "ar")

    assert action_plan["version"] == mpg.ACTION_PLAN_VERSION
    assert action_plan["status"] == "ready"
    assert len(action_plan["social_items"]) == 8
    assert len(action_plan["ad_funnel_items"]) == 10
    assert action_plan["social_items"][0]["generation_request"]["mode"] == "quick"
    assert action_plan["ad_funnel_items"][0]["funnel_stage"] == "Awareness"
