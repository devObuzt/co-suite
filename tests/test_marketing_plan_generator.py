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
                "sections": [
                    {"id": "executive_summary", "summary": "Start with the strongest offers."}
                ],
            }
        )

    monkeypatch.setattr(mpg, "call_text_ai", fake_call_text_ai)

    deck = await mpg.generate_marketing_plan_deck(make_suite(), "he")

    assert calls["provider"] == "anthropic"
    assert calls["model"] == mpg.settings.anthropic_text_model
    assert deck["language"] == "he"
    assert deck["cover"]["title"] == "Connec plan"
