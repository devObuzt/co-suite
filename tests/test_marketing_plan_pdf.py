from api.models.suite import Suite
from api.services.marketing_plan_pdf import build_marketing_plan_pdf, _labels


def test_build_marketing_plan_pdf_returns_valid_pdf_bytes():
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="Smart Line Academy",
        slug="smart-line",
        brand={
            "name": "Smart Line Academy",
            "industry": "تعليم تداول",
            "services": ["دورات تداول", "تعلم الاستثمار"],
        },
        strategy={
            "marketing_intelligence": {
                "language": "ar",
                "keywords": [
                    {"id": "kw-1", "text": "دورات تداول", "intent": "commercial"},
                    {"id": "kw-2", "text": "تعليم الأسهم", "intent": "commercial"},
                ],
                "competitors": [
                    {
                        "id": "comp-1",
                        "title": "أكاديمية تداول",
                        "result_type": "google_organic",
                        "url": "https://example.com",
                        "snippet": "دورات تداول للمبتدئين.",
                    }
                ],
                "demand_supply": {
                    "summary": {
                        "average_monthly_searches": 500,
                        "competition_level": "MEDIUM",
                        "market_pressure_score": 35,
                    },
                    "keyword_metrics": [
                        {
                            "keyword": "دورات تداول",
                            "average_monthly_searches": 500,
                            "competition": "MEDIUM",
                            "competition_index": 44,
                        }
                    ],
                },
                "personas": [
                    {
                        "id": "persona-1",
                        "name": "ليان",
                        "age": 31,
                        "gender": "أنثى",
                        "profession": "موظفة",
                        "economic_status": "متوسطة",
                        "challenge": "تحتاج طريقة آمنة لتتعلم التداول.",
                        "need": "مسار واضح ومناسب للمبتدئين.",
                        "motivation": "زيادة الدخل بثقة.",
                        "solution": "نقدم دورة منظمة مع أمثلة عملية.",
                    }
                ],
            },
            "marketing_action_plan": {
                "social_items": [
                    {
                        "id": "social-1",
                        "title": "فيديو تعليمي قصير",
                        "objective": "شرح قيمة الدورة للمبتدئين.",
                    }
                ],
                "ad_funnel_items": [],
            },
        },
    )

    pdf_bytes, filename = build_marketing_plan_pdf(suite)

    assert filename == "smart-line-academy-marketing-plan.pdf"
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 2500


def test_marketing_plan_pdf_uses_marketing_intelligence_language():
    suite = Suite(
        id="suite-2",
        owner_id="user-1",
        name="Arabic Suite",
        slug="arabic-suite",
        brand={"name": "Arabic Suite"},
        strategy={"marketing_intelligence": {"language": "ar", "keywords": []}},
    )

    pdf_bytes, _filename = build_marketing_plan_pdf(suite)

    assert pdf_bytes.startswith(b"%PDF")
    assert _labels("ar")["title"] == "الخطة التسويقية"


def test_marketing_plan_pdf_ignores_bidi_isolate_controls():
    suite = Suite(
        id="suite-3",
        owner_id="user-1",
        name="Mixed Direction Suite",
        slug="mixed-direction",
        brand={
            "name": "Mixed Direction Suite",
            "services": ["خدمة \u2068Google Ads\u2069 متقدمة"],
        },
        strategy={
            "marketing_intelligence": {
                "language": "ar",
                "keywords": [{"text": "تسويق \u2068AI\u2069"}],
                "competitors": [
                    {
                        "title": "منافس \u2068Meta\u2069",
                        "result_type": "google_organic",
                        "url": "https://example.com",
                        "snippet": "نص عربي مع \u2068English\u2069 داخل الجملة.",
                    }
                ],
                "personas": [
                    {
                        "name": "ليان",
                        "challenge": "تحتاج \u2068CRM\u2069 واضح.",
                        "motivation": "زيادة الطلب.",
                        "solution": "نقدم خطة مبيعات.",
                    }
                ],
            }
        },
    )

    pdf_bytes, filename = build_marketing_plan_pdf(suite)

    assert filename == "mixed-direction-suite-marketing-plan.pdf"
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 2500
