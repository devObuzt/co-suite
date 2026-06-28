"""Build downloadable marketing plan PDFs from saved suite data."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
import re
from typing import Any

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.models.suite import Suite
from api.services.marketing_plan_generator import infer_plan_language


FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
FONT_BY_LANGUAGE = {
    "ar": ("Cairo", FONT_DIR / "Cairo-Regular.ttf"),
    "he": ("NotoSansHebrew", FONT_DIR / "NotoSansHebrew-Regular.ttf"),
    "en": ("Inter", FONT_DIR / "Inter-Regular.ttf"),
}


def _register_font(language: str) -> str:
    font_name, font_path = FONT_BY_LANGUAGE.get(language, FONT_BY_LANGUAGE["en"])
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _is_rtl(language: str) -> bool:
    return language in {"ar", "he", "fa", "ur"}


def _shape_text(value: Any, language: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if language == "ar":
        text = arabic_reshaper.reshape(text)
    if _is_rtl(language):
        text = get_display(text)
    return text


def _p(value: Any, language: str) -> str:
    return escape(_shape_text(value, language))


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strategy(suite: Suite) -> dict[str, Any]:
    return suite.strategy if isinstance(suite.strategy, dict) else {}


def _brand(suite: Suite) -> dict[str, Any]:
    return suite.brand if isinstance(suite.brand, dict) else {}


def _intelligence(suite: Suite) -> dict[str, Any]:
    return _safe_dict(_strategy(suite).get("marketing_intelligence"))


def _action_plan(suite: Suite) -> dict[str, Any]:
    return _safe_dict(_strategy(suite).get("marketing_action_plan"))


def _services(suite: Suite) -> list[str]:
    brand = _brand(suite)
    strategy = _strategy(suite)
    marketing_plan = _safe_dict(strategy.get("marketing_plan"))
    values: list[Any] = []
    for source in (brand, strategy, marketing_plan):
        values.extend(_safe_list(source.get("services")))
        values.extend(_safe_list(source.get("products")))
        values.extend(_safe_list(source.get("products_services")))
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        marker = text.casefold()
        if text and marker not in seen:
            seen.add(marker)
            items.append(text)
    return items[:30]


def _filename(suite: Suite) -> str:
    base = str(_brand(suite).get("name") or suite.name or "suite").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return f"{slug or 'suite'}-marketing-plan.pdf"


def _labels(language: str) -> dict[str, str]:
    if language == "ar":
        return {
            "title": "الخطة التسويقية",
            "subtitle": "ملف جاهز للتحميل مبني على مراحل الخطة داخل OneShare.",
            "generated": "تاريخ التوليد",
            "services": "الخدمات / المنتجات",
            "keywords": "الكلمات المفتاحية",
            "competitors": "المنافسون",
            "demand": "العرض والطلب",
            "personas": "شخصيات العملاء",
            "actions": "خطط العمل",
            "empty": "لم يتم توليد هذا القسم بعد.",
            "source": "المصدر",
            "link": "الرابط",
            "searches": "البحث الشهري",
            "competition": "المنافسة",
            "pressure": "ضغط السوق",
            "age": "العمر",
            "gender": "الجندر",
            "profession": "المهنة",
            "economics": "الوضع الاقتصادي",
            "challenge": "التحدي",
            "need": "الحاجة",
            "motivation": "الدافع",
            "solution": "حل العرض",
        }
    if language == "he":
        return {
            "title": "תכנית שיווקית",
            "subtitle": "קובץ להורדה שמבוסס על שלבי התכנית ב-OneShare.",
            "generated": "נוצר בתאריך",
            "services": "שירותים / מוצרים",
            "keywords": "מילות מפתח",
            "competitors": "מתחרים",
            "demand": "ביקוש והיצע",
            "personas": "פרסונות לקוחות",
            "actions": "תכניות עבודה",
            "empty": "החלק הזה עדיין לא נוצר.",
            "source": "מקור",
            "link": "קישור",
            "searches": "חיפושים חודשיים",
            "competition": "תחרות",
            "pressure": "לחץ שוק",
            "age": "גיל",
            "gender": "מגדר",
            "profession": "מקצוע",
            "economics": "מצב כלכלי",
            "challenge": "אתגר",
            "need": "צורך",
            "motivation": "מוטיבציה",
            "solution": "פתרון ההצעה",
        }
    return {
        "title": "Marketing Plan",
        "subtitle": "Downloadable file built from the saved OneShare marketing stages.",
        "generated": "Generated at",
        "services": "Services / Products",
        "keywords": "Keywords",
        "competitors": "Competitors",
        "demand": "Demand and Supply",
        "personas": "Customer Personas",
        "actions": "Work Plans",
        "empty": "This section has not been generated yet.",
        "source": "Source",
        "link": "Link",
        "searches": "Monthly searches",
        "competition": "Competition",
        "pressure": "Market pressure",
        "age": "Age",
        "gender": "Gender",
        "profession": "Profession",
        "economics": "Economic status",
        "challenge": "Challenge",
        "need": "Need",
        "motivation": "Motivation",
        "solution": "Offer solution",
    }


def _styles(language: str, font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    alignment = TA_RIGHT if _is_rtl(language) else TA_LEFT
    return {
        "title": ParagraphStyle(
            "MarketingPdfTitle",
            parent=base["Title"],
            fontName=font_name,
            fontSize=24,
            leading=32,
            alignment=alignment,
            textColor=colors.HexColor("#111827"),
        ),
        "h2": ParagraphStyle(
            "MarketingPdfH2",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=15,
            leading=22,
            alignment=alignment,
            spaceBefore=16,
            textColor=colors.HexColor("#111827"),
        ),
        "body": ParagraphStyle(
            "MarketingPdfBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=16,
            alignment=alignment,
            textColor=colors.HexColor("#374151"),
        ),
        "small": ParagraphStyle(
            "MarketingPdfSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8,
            leading=12,
            alignment=alignment,
            textColor=colors.HexColor("#6b7280"),
        ),
    }


def _section(story: list[Any], styles: dict[str, ParagraphStyle], title: str, language: str) -> None:
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(_p(title, language), styles["h2"]))


def _bullet_list(story: list[Any], styles: dict[str, ParagraphStyle], items: list[Any], language: str, empty: str, limit: int = 20) -> None:
    if not items:
        story.append(Paragraph(_p(empty, language), styles["body"]))
        return
    for item in items[:limit]:
        story.append(Paragraph(_p(f"- {item}", language), styles["body"]))


def _table(story: list[Any], rows: list[list[Any]], styles: dict[str, ParagraphStyle], language: str, widths: list[float]) -> None:
    table_rows = [[Paragraph(_p(cell, language), styles["small"]) for cell in row] for row in rows]
    table = Table(table_rows, colWidths=widths, hAlign="RIGHT" if _is_rtl(language) else "LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)


def build_marketing_plan_pdf(suite: Suite) -> tuple[bytes, str]:
    language = infer_plan_language(suite)
    labels = _labels(language)
    font_name = _register_font(language)
    styles = _styles(language, font_name)
    buffer = __import__("io").BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=str(_brand(suite).get("name") or suite.name or labels["title"]),
    )

    intelligence = _intelligence(suite)
    action_plan = _action_plan(suite)
    demand_supply = _safe_dict(intelligence.get("demand_supply"))
    summary = _safe_dict(demand_supply.get("summary"))
    story: list[Any] = []

    suite_name = _brand(suite).get("name") or suite.name or "Suite"
    story.append(Paragraph(_p(f"{labels['title']} - {suite_name}", language), styles["title"]))
    story.append(Paragraph(_p(labels["subtitle"], language), styles["body"]))
    story.append(Paragraph(_p(f"{labels['generated']}: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", language), styles["small"]))

    _section(story, styles, labels["services"], language)
    _bullet_list(story, styles, _services(suite), language, labels["empty"], 30)

    _section(story, styles, labels["keywords"], language)
    keywords = [item.get("text") for item in _safe_list(intelligence.get("keywords")) if isinstance(item, dict) and item.get("text")]
    _bullet_list(story, styles, keywords, language, labels["empty"], 40)

    _section(story, styles, labels["competitors"], language)
    competitors = [item for item in _safe_list(intelligence.get("competitors")) if isinstance(item, dict)]
    if competitors:
        rows = [[labels["competitors"], labels["source"], labels["link"]]]
        rows.extend(
            [
                [
                    item.get("title") or item.get("name") or "-",
                    item.get("result_type") or item.get("platform") or "-",
                    item.get("url") or "-",
                ]
                for item in competitors[:20]
            ]
        )
        _table(story, rows, styles, language, [2.5 * inch, 1.2 * inch, 2.7 * inch])
    else:
        story.append(Paragraph(_p(labels["empty"], language), styles["body"]))

    _section(story, styles, labels["demand"], language)
    if summary:
        demand_lines = [
            f"{labels['searches']}: {summary.get('average_monthly_searches', 0)}",
            f"{labels['competition']}: {summary.get('competition_level', 'UNKNOWN')}",
            f"{labels['pressure']}: {summary.get('market_pressure_score', 0)}/100",
        ]
        _bullet_list(story, styles, demand_lines, language, labels["empty"], 10)
    else:
        story.append(Paragraph(_p(labels["empty"], language), styles["body"]))
    metrics = [item for item in _safe_list(demand_supply.get("keyword_metrics")) if isinstance(item, dict)]
    if metrics:
        rows = [[labels["keywords"], labels["searches"], labels["competition"]]]
        rows.extend(
            [
                [
                    item.get("keyword") or "-",
                    item.get("average_monthly_searches", 0),
                    f"{item.get('competition') or 'UNKNOWN'} {item.get('competition_index') or ''}",
                ]
                for item in metrics[:20]
            ]
        )
        _table(story, rows, styles, language, [3.2 * inch, 1.4 * inch, 1.8 * inch])

    _section(story, styles, labels["personas"], language)
    personas = [item for item in _safe_list(intelligence.get("personas")) if isinstance(item, dict)]
    if personas:
        for persona in personas[:10]:
            title = f"{persona.get('name') or '-'}"
            meta = ", ".join(
                str(value)
                for value in [
                    f"{labels['age']}: {persona.get('age')}" if persona.get("age") else "",
                    f"{labels['gender']}: {persona.get('gender')}" if persona.get("gender") else "",
                    f"{labels['profession']}: {persona.get('profession')}" if persona.get("profession") else "",
                    f"{labels['economics']}: {persona.get('economic_status')}" if persona.get("economic_status") else "",
                ]
                if value
            )
            story.append(Paragraph(_p(title, language), styles["h2"]))
            if meta:
                story.append(Paragraph(_p(meta, language), styles["small"]))
            for key in ("challenge", "need", "motivation", "solution"):
                if persona.get(key):
                    story.append(Paragraph(_p(f"{labels[key]}: {persona.get(key)}", language), styles["body"]))
    else:
        story.append(Paragraph(_p(labels["empty"], language), styles["body"]))

    _section(story, styles, labels["actions"], language)
    action_items = [
        *[item for item in _safe_list(action_plan.get("social_items")) if isinstance(item, dict)],
        *[item for item in _safe_list(action_plan.get("ad_funnel_items")) if isinstance(item, dict)],
    ]
    if action_items:
        for item in action_items[:20]:
            body = item.get("objective") or item.get("caption") or item.get("notes") or ""
            story.append(Paragraph(_p(f"- {item.get('title') or '-'}: {body}", language), styles["body"]))
    else:
        story.append(Paragraph(_p(labels["empty"], language), styles["body"]))

    document.build(story)
    return buffer.getvalue(), _filename(suite)
