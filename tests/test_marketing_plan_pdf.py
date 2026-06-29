from api.models.suite import Suite
from api.services.marketing_plan_pdf import build_marketing_plan_pdf, _audience_summary, _keyword_groups, _labels, _market_insights
import re
import subprocess
from pathlib import Path


def _pdfinfo(pdf_bytes: bytes, tmp_path: Path) -> str:
    path = tmp_path / "marketing-plan.pdf"
    path.write_bytes(pdf_bytes)
    result = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True)
    return result.stdout


def test_build_marketing_plan_pdf_returns_valid_pdf_bytes(tmp_path):
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
    info = _pdfinfo(pdf_bytes, tmp_path)
    pages_match = re.search(r"Pages:\s+(\d+)", info)
    assert pages_match
    assert int(pages_match.group(1)) >= 10
    size_match = re.search(r"Page size:\s+([0-9.]+) x ([0-9.]+)", info)
    assert size_match
    width = float(size_match.group(1))
    height = float(size_match.group(2))
    assert width > height
    assert round(width / height, 2) == 1.78


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
    assert len(pdf_bytes) > 5000


def test_keyword_groups_hide_empty_intent_groups():
    labels = _labels("ar")
    groups = _keyword_groups(
        {"keywords": [{"text": "أكاديمية تداول", "intent": "commercial"}]},
        labels,
    )

    assert groups == [
        (
            labels["direct_intent"],
            labels["direct_intent_help"],
            ["أكاديمية تداول"],
        )
    ]


def test_market_insights_use_specific_missing_copy():
    labels = _labels("ar")
    suite = Suite(
        id="suite-4",
        owner_id="user-1",
        name="No Demand Yet",
        slug="no-demand-yet",
        brand={"name": "No Demand Yet"},
        strategy={"marketing_intelligence": {"language": "ar", "keywords": []}},
    )

    flattened = [
        line
        for _title, lines in _market_insights(suite, {"keywords": [], "competitors": []}, labels)
        for line in lines
    ]

    assert labels["empty"] not in flattened
    assert labels["market_services_missing"] in flattened
    assert labels["market_pressure_missing"] in flattened


def test_audience_summary_formats_structured_audience_fields():
    labels = _labels("ar")
    suite = Suite(
        id="suite-5",
        owner_id="user-1",
        name="Sea of Herbs",
        slug="sea-of-herbs",
        brand={
            "name": "Sea of Herbs",
            "target_audience": "طبيعية, زيوت علاجية, صوابين طبيعية, Worldwide الجمهور: يهتمون بـ hand made",
            "audience_location": {"scope": "world", "countries": [], "cities": []},
            "audience_interests": ["بهارات", "أعشاب hand made", "زيوت علاجية"],
            "audience_behaviors": ["يبحثون عن منتجات طبيعية", "يفضلون الشراء اليدوي"],
            "audience_social_statuses": ["محبو المنتجات الطبيعية"],
            "audience_languages": ["ar"],
            "audience_language_names": ["العربية"],
        },
        strategy={},
    )

    summary = _audience_summary(suite, labels)

    assert "Worldwide" not in summary
    assert "الجغرافيا: عالمي" in summary
    assert "الديموغرافيا: محبو المنتجات الطبيعية" in summary
    assert "اللغة والأسلوب: العربية" in summary
    assert "السلوكيات والاهتمامات:" in summary
    assert "عالمي" in summary
    assert "بهارات، أعشاب يدوية، زيوت علاجية" in summary
    assert "يفضلون الشراء اليدوي" in summary
    assert "الجمهور:" not in summary
