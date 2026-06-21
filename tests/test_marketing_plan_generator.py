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


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_uses_anthropic(monkeypatch):
    calls = {}

    async def fake_call_text_ai(**kwargs):
        calls.update(kwargs)
        return json.dumps(
            {
                "cover": {"title": "Connec plan", "subtitle": "Practical growth"},
                "research_summary": {
                    "sources_used": ["manual profile", "instagram"],
                    "limitations": ["Validate budget and current campaign priorities"],
                },
                "monthly_work_plan": {
                    "daily_story_direction": ["Show daily proof", "Answer common questions"],
                    "items": [
                        {"title": "Founder trust reel", "prompt": "Create a trust reel", "recommended_output": {"format": "video"}},
                        {"title": "Offer carousel", "prompt": "Create an offer carousel", "recommended_output": {"format": "carousel"}},
                    ],
                },
                "paid_funnel": {
                    "stages": [
                        {
                            "stage": "Awareness",
                            "goal": "Reach local business owners",
                            "content_ideas": [
                                {"title": "Pain opener", "recommended_outputs": ["video"], "prompt": "Create awareness video"}
                            ],
                        }
                    ]
                },
                "sections": [
                    {
                        "id": "executive_summary",
                        "summary": "Start with the strongest offers.",
                        "bullets": ["Lead with proof", "Make the offer obvious"],
                        "cards": [{"title": "Main move", "body": "Turn existing services into clear packages."}],
                    },
                    {
                        "id": "content_strategy",
                        "summary": "Use a mix of education, proof, and conversion content.",
                        "bullets": ["70% attraction", "20% trust", "10% sales"],
                    },
                ],
            }
        )

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "he")

    assert calls["provider"] == "anthropic"
    assert calls["model"] == mpg.settings.anthropic_text_model
    assert calls["max_tokens"] == mpg.MARKETING_PLAN_MAX_TOKENS
    assert calls["timeout"] == mpg.MARKETING_PLAN_TIMEOUT_SECONDS
    assert deck["language"] == "he"
    assert deck["cover"]["title"] == "Connec plan"


@pytest.mark.asyncio
async def test_generate_marketing_plan_deck_rejects_empty_ai_json(monkeypatch):
    async def fake_call_text_ai(**kwargs):
        return "{}"

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    with pytest.raises(mpg.MarketingPlanGenerationError):
        await mpg.generate_marketing_plan_deck(make_suite(), "ar")


def test_validate_marketing_plan_deck_rejects_title_only_skeleton():
    deck = mpg.normalize_marketing_plan_deck({}, "Connec", "ar")

    with pytest.raises(mpg.MarketingPlanGenerationError):
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
