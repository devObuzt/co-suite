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
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.models.suite import Suite
from api.services.marketing_plan_generator import infer_plan_language


FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
FONT_FILES = {
    "Arabic": FONT_DIR / "NotoSansArabic-Regular.ttf",
    "Hebrew": FONT_DIR / "NotoSansHebrew-Regular.ttf",
    "Latin": FONT_DIR / "Inter-Regular.ttf",
}
FONT_BY_LANGUAGE = {
    "ar": "Arabic",
    "he": "Hebrew",
    "en": "Latin",
}
ACCENTS = {
    "blue": ("#eff6ff", "#60a5fa", "#1d4ed8"),
    "mint": ("#ecfdf5", "#34d399", "#047857"),
    "pink": ("#fdf2f8", "#f472b6", "#be185d"),
    "amber": ("#fffbeb", "#fbbf24", "#b45309"),
    "violet": ("#f5f3ff", "#a78bfa", "#6d28d9"),
    "slate": ("#f8fafc", "#94a3b8", "#334155"),
}
BIDI_CONTROL_CHARS = dict.fromkeys(
    ord(char)
    for char in (
        "\u061c"  # Arabic letter mark
        "\u200e"  # left-to-right mark
        "\u200f"  # right-to-left mark
        "\u202a"  # left-to-right embedding
        "\u202b"  # right-to-left embedding
        "\u202c"  # pop directional formatting
        "\u202d"  # left-to-right override
        "\u202e"  # right-to-left override
        "\u2066"  # left-to-right isolate
        "\u2067"  # right-to-left isolate
        "\u2068"  # first strong isolate
        "\u2069"  # pop directional isolate
    )
)


def _register_fonts() -> dict[str, str]:
    names: dict[str, str] = {}
    for name, path in FONT_FILES.items():
        if path.exists():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
            names[name] = name
        else:
            names[name] = "Helvetica"
    return names


def _is_rtl(language: str) -> bool:
    return language in {"ar", "he", "fa", "ur"}


def _is_arabic_char(char: str) -> bool:
    code = ord(char)
    return 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF or 0xFB50 <= code <= 0xFDFF or 0xFE70 <= code <= 0xFEFF


def _is_hebrew_char(char: str) -> bool:
    code = ord(char)
    return 0x0590 <= code <= 0x05FF


def _font_for_char(char: str, fonts: dict[str, str], default_font: str) -> str:
    if _is_arabic_char(char):
        return fonts["Arabic"]
    if _is_hebrew_char(char):
        return fonts["Hebrew"]
    if char.isascii():
        return fonts["Latin"]
    return default_font


def _visual_text(value: Any, language: str) -> str:
    text = str(value or "").translate(BIDI_CONTROL_CHARS).strip()
    if not text:
        return "-"
    if language == "ar":
        text = arabic_reshaper.reshape(text)
    if _is_rtl(language):
        text = get_display(text)
    return text


def _p(value: Any, language: str, fonts: dict[str, str], default_font: str) -> str:
    text = _visual_text(value, language)
    chunks: list[str] = []
    current_font = ""
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_text, current_font
        if current_text:
            chunks.append(f'<font name="{current_font}">{escape("".join(current_text))}</font>')
        current_text = []

    for char in text:
        font = _font_for_char(char, fonts, default_font)
        if font != current_font:
            flush()
            current_font = font
        current_text.append(char)
    flush()
    return "".join(chunks) or escape(text)


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
            "subtitle": "ملف عرض جاهز للتحميل مبني على مراحل الخطة داخل OneShare.",
            "generated": "تاريخ التوليد",
            "overview": "ملخص العرض",
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
            "generated_by": "تم إنشاؤه عبر OneShare",
        }
    if language == "he":
        return {
            "title": "תכנית שיווקית",
            "subtitle": "מצגת מוכנה להורדה שמבוססת על שלבי התכנית ב-OneShare.",
            "generated": "נוצר בתאריך",
            "overview": "תקציר",
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
            "generated_by": "נוצר באמצעות OneShare",
        }
    return {
        "title": "Marketing Plan",
        "subtitle": "Presentation-ready file built from the saved OneShare marketing stages.",
        "generated": "Generated at",
        "overview": "Overview",
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
        "generated_by": "Generated by OneShare",
    }


def _styles(language: str, font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    alignment = TA_RIGHT if _is_rtl(language) else TA_LEFT
    return {
        "cover": ParagraphStyle(
            "MarketingPdfCover",
            parent=base["Title"],
            fontName=font_name,
            fontSize=34,
            leading=42,
            alignment=alignment,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=10,
        ),
        "title": ParagraphStyle(
            "MarketingPdfTitle",
            parent=base["Heading1"],
            fontName=font_name,
            fontSize=24,
            leading=30,
            alignment=alignment,
            textColor=colors.HexColor("#111827"),
            spaceAfter=8,
        ),
        "eyebrow": ParagraphStyle(
            "MarketingPdfEyebrow",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=12,
            alignment=alignment,
            textColor=colors.HexColor("#64748b"),
        ),
        "card_title": ParagraphStyle(
            "MarketingPdfCardTitle",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=13,
            leading=18,
            alignment=alignment,
            textColor=colors.HexColor("#111827"),
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "MarketingPdfBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            alignment=alignment,
            textColor=colors.HexColor("#374151"),
        ),
        "small": ParagraphStyle(
            "MarketingPdfSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8,
            leading=11,
            alignment=alignment,
            textColor=colors.HexColor("#6b7280"),
        ),
        "metric": ParagraphStyle(
            "MarketingPdfMetric",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=20,
            leading=26,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0f172a"),
        ),
    }


def _para(value: Any, language: str, styles: dict[str, ParagraphStyle], style: str, fonts: dict[str, str], default_font: str) -> Paragraph:
    return Paragraph(_p(value, language, fonts, default_font), styles[style])


def _slide_title(story: list[Any], title: str, subtitle: str | None, language: str, styles: dict[str, ParagraphStyle], fonts: dict[str, str], default_font: str) -> None:
    story.append(_para(title, language, styles, "title", fonts, default_font))
    if subtitle:
        story.append(_para(subtitle, language, styles, "body", fonts, default_font))
    story.append(Spacer(1, 0.18 * inch))


def _card(
    title: str,
    lines: list[Any],
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
    accent: str = "blue",
) -> Table:
    bg, border, _strong = ACCENTS.get(accent, ACCENTS["blue"])
    content: list[Any] = [_para(title, language, styles, "card_title", fonts, default_font)]
    for line in lines[:7]:
        if line is None or str(line).strip() == "":
            continue
        content.append(_para(line, language, styles, "body", fonts, default_font))
    table = Table([[content]], colWidths=[3.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
                ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor(border)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def _card_grid(story: list[Any], cards: list[Table], columns: int = 3) -> None:
    rows: list[list[Any]] = []
    for index in range(0, len(cards), columns):
        row = cards[index : index + columns]
        while len(row) < columns:
            row.append("")
        rows.append(row)
    if not rows:
        return
    table = Table(rows, colWidths=[3.15 * inch] * columns, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)] or [[]]


def _metric_cards(summary: dict[str, Any], labels: dict[str, str], language: str, styles: dict[str, ParagraphStyle], fonts: dict[str, str], default_font: str) -> list[Table]:
    return [
        _card(labels["searches"], [summary.get("average_monthly_searches", 0)], language, styles, fonts, default_font, "mint"),
        _card(labels["competition"], [summary.get("competition_level", "UNKNOWN")], language, styles, fonts, default_font, "amber"),
        _card(labels["pressure"], [f"{summary.get('market_pressure_score', 0)}/100"], language, styles, fonts, default_font, "violet"),
    ]


def _text_or_empty(items: list[Any], labels: dict[str, str]) -> list[Any]:
    return items if items else [labels["empty"]]


def build_marketing_plan_pdf(suite: Suite) -> tuple[bytes, str]:
    intelligence = _intelligence(suite)
    language = infer_plan_language(suite, intelligence.get("language") or intelligence.get("audience_language"))
    labels = _labels(language)
    fonts = _register_fonts()
    default_font = fonts[FONT_BY_LANGUAGE.get(language, "Latin")]
    styles = _styles(language, default_font)
    buffer = __import__("io").BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=0.42 * inch,
        leftMargin=0.42 * inch,
        topMargin=0.38 * inch,
        bottomMargin=0.38 * inch,
        title=str(_brand(suite).get("name") or suite.name or labels["title"]),
    )

    action_plan = _action_plan(suite)
    demand_supply = _safe_dict(intelligence.get("demand_supply"))
    summary = _safe_dict(demand_supply.get("summary"))
    story: list[Any] = []
    suite_name = _brand(suite).get("name") or suite.name or "Suite"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Cover slide
    story.append(Spacer(1, 0.8 * inch))
    story.append(_para(f"{labels['title']} - {suite_name}", language, styles, "cover", fonts, default_font))
    story.append(_para(labels["subtitle"], language, styles, "body", fonts, default_font))
    story.append(Spacer(1, 0.35 * inch))
    _card_grid(
        story,
        [
            _card(labels["services"], [len(_services(suite))], language, styles, fonts, default_font, "blue"),
            _card(labels["keywords"], [len(_safe_list(intelligence.get("keywords")))], language, styles, fonts, default_font, "mint"),
            _card(labels["competitors"], [len(_safe_list(intelligence.get("competitors")))], language, styles, fonts, default_font, "pink"),
        ],
    )
    story.append(Spacer(1, 0.25 * inch))
    story.append(_para(f"{labels['generated']}: {generated_at}", language, styles, "small", fonts, default_font))
    story.append(_para(labels["generated_by"], language, styles, "small", fonts, default_font))

    # Services/products
    for page_index, group in enumerate(_chunks(_text_or_empty(_services(suite), labels), 9)):
        story.append(PageBreak())
        _slide_title(story, labels["services"], None if page_index else labels["overview"], language, styles, fonts, default_font)
        cards = [_card(str(item), [], language, styles, fonts, default_font, "blue") for item in group]
        _card_grid(story, cards)

    # Keywords
    keywords = [item.get("text") for item in _safe_list(intelligence.get("keywords")) if isinstance(item, dict) and item.get("text")]
    for page_index, group in enumerate(_chunks(_text_or_empty(keywords, labels), 15)):
        story.append(PageBreak())
        _slide_title(story, labels["keywords"], None if page_index else labels["subtitle"], language, styles, fonts, default_font)
        cards = [_card(str(item), [], language, styles, fonts, default_font, "mint") for item in group]
        _card_grid(story, cards)

    # Competitors
    competitors = [item for item in _safe_list(intelligence.get("competitors")) if isinstance(item, dict)]
    competitor_items = competitors or [{"title": labels["empty"], "result_type": "-", "url": "-"}]
    for page_index, group in enumerate(_chunks(competitor_items[:18], 6)):
        story.append(PageBreak())
        _slide_title(story, labels["competitors"], None if page_index else labels["subtitle"], language, styles, fonts, default_font)
        cards = []
        for item in group:
            cards.append(
                _card(
                    item.get("title") or item.get("name") or labels["empty"],
                    [
                        f"{labels['source']}: {item.get('result_type') or item.get('platform') or '-'}",
                        f"{labels['link']}: {item.get('url') or '-'}",
                        item.get("snippet") or item.get("description") or "",
                    ],
                    language,
                    styles,
                    fonts,
                    default_font,
                    "pink",
                )
            )
        _card_grid(story, cards, columns=2)

    # Demand/supply
    story.append(PageBreak())
    _slide_title(story, labels["demand"], labels["subtitle"], language, styles, fonts, default_font)
    if summary:
        _card_grid(story, _metric_cards(summary, labels, language, styles, fonts, default_font))
    else:
        story.append(_card(labels["demand"], [labels["empty"]], language, styles, fonts, default_font, "amber"))
    metrics = [item for item in _safe_list(demand_supply.get("keyword_metrics")) if isinstance(item, dict)]
    if metrics:
        story.append(Spacer(1, 0.18 * inch))
        cards = [
            _card(
                item.get("keyword") or "-",
                [
                    f"{labels['searches']}: {item.get('average_monthly_searches', 0)}",
                    f"{labels['competition']}: {item.get('competition') or 'UNKNOWN'} {item.get('competition_index') or ''}",
                ],
                language,
                styles,
                fonts,
                default_font,
                "amber",
            )
            for item in metrics[:6]
        ]
        _card_grid(story, cards)

    # Personas
    personas = [item for item in _safe_list(intelligence.get("personas")) if isinstance(item, dict)]
    persona_items = personas or [{"name": labels["empty"]}]
    for page_index, group in enumerate(_chunks(persona_items[:10], 4)):
        story.append(PageBreak())
        _slide_title(story, labels["personas"], None if page_index else labels["subtitle"], language, styles, fonts, default_font)
        cards = []
        for persona in group:
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
            cards.append(
                _card(
                    persona.get("name") or labels["empty"],
                    [
                        meta,
                        f"{labels['challenge']}: {persona.get('challenge')}" if persona.get("challenge") else "",
                        f"{labels['motivation']}: {persona.get('motivation')}" if persona.get("motivation") else "",
                        f"{labels['solution']}: {persona.get('solution')}" if persona.get("solution") else "",
                    ],
                    language,
                    styles,
                    fonts,
                    default_font,
                    "violet",
                )
            )
        _card_grid(story, cards, columns=2)

    # Action plans
    action_items = [
        *[item for item in _safe_list(action_plan.get("social_items")) if isinstance(item, dict)],
        *[item for item in _safe_list(action_plan.get("ad_funnel_items")) if isinstance(item, dict)],
    ]
    actions = action_items or [{"title": labels["empty"]}]
    for page_index, group in enumerate(_chunks(actions[:12], 6)):
        story.append(PageBreak())
        _slide_title(story, labels["actions"], None if page_index else labels["subtitle"], language, styles, fonts, default_font)
        cards = []
        for item in group:
            body = item.get("objective") or item.get("caption") or item.get("notes") or ""
            cards.append(_card(item.get("title") or labels["empty"], [body], language, styles, fonts, default_font, "slate"))
        _card_grid(story, cards, columns=2)

    document.build(story)
    return buffer.getvalue(), _filename(suite)
