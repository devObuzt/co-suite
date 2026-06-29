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
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.models.suite import Suite
from api.services.marketing_plan_generator import infer_plan_language


SLIDE_SIZE = (900, 507)
SLIDE_MARGIN = 42
DARK_BG = colors.HexColor("#07090d")
PANEL_BG = colors.HexColor("#0f172a")
CARD_BG = colors.HexColor("#111827")
CARD_BORDER = colors.HexColor("#2f80ff")
TEXT_LIGHT = colors.HexColor("#f8fafc")
TEXT_MUTED = colors.HexColor("#dbeafe")
TEXT_DIM = colors.HexColor("#93a4b8")
ACCENT = colors.HexColor("#2f80ff")
ACCENT_2 = colors.HexColor("#18b89d")
ACCENT_3 = colors.HexColor("#b7791f")
ACCENT_HEX = "#2f80ff"

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
            "brand": "العلامة التجارية",
            "market": "السوق",
            "audience": "الجمهور",
            "language": "اللغة",
            "location": "الموقع",
            "project_nature": "طبيعة المشروع",
            "marketing_plan": "خطة نمو وتسويق",
            "snapshot": "صورة المشروع",
            "snapshot_subtitle": "نقطة الانطلاق الاستراتيجية قبل قرارات القنوات والمحتوى.",
            "deck_metric_services": "محاور عرض",
            "deck_metric_keywords": "مصطلحات سوق",
            "deck_metric_competitors": "إشارات منافسة",
            "services_pitch": "منظومة العرض التي سنحوّلها إلى طلب ورسائل حملات واضحة.",
            "service_card_copy": "محور عرض واضح للتموضع والمحتوى وبنية الحملات.",
            "market_reading": "قراءة السوق",
            "market_reading_subtitle": "ماذا يخبرنا السوق قبل تحويل الاستراتيجية إلى تنفيذ.",
            "opportunity": "الفرصة",
            "problem": "مشكلة السوق",
            "positioning": "التموضع",
            "opportunity_copy": "نبني الطلب حول مشكلة واضحة وإثبات ونتيجة مفهومة.",
            "problem_copy": "الجمهور يحتاج سبباً أوضح ليختار هذا البزنس الآن.",
            "positioning_copy": "نقود بالثقة والتميّز ودعوات فعل مباشرة.",
            "direct_intent": "كلمات طلب مباشر",
            "learning_intent": "كلمات أسئلة وتعلّم",
            "comparison_intent": "كلمات مقارنة واختيار",
            "local_intent": "كلمات بحث محلي",
            "direct_intent_help": "عبارات يبحث بها شخص قريب من طلب الخدمة أو الشراء.",
            "learning_intent_help": "عبارات يستخدمها الجمهور ليفهم المشكلة أو يتعلم الحل.",
            "comparison_intent_help": "عبارات تظهر قبل الاختيار بين مزودين أو حلول.",
            "local_intent_help": "عبارات فيها نية مكانية مثل قريب، مدينة، منطقة، أو خرائط.",
            "keywords_missing": "ولّد الكلمات المفتاحية حتى تظهر مجموعات نية البحث هنا.",
            "market_services_missing": "أضف الخدمات/المنتجات حتى تظهر محاور العرض هنا.",
            "market_pressure_missing": "أرقام العرض والطلب غير متوفرة بعد؛ نبدأ من إشارات الكلمات والمنافسين.",
            "keywords_pitch": "الكلمات تتحول إلى مجموعات نية، وليس قائمة مسطحة.",
            "competitors_pitch": "المنافسون إشارات سوق: عروض، تموضع، وضغط قنوات.",
            "missing_source": "هذا المصدر لم ينتج منافسين مباشرين بعد.",
            "market_signal": "راجع هذا المصدر لاستخراج إشارات تموضع.",
            "demand_pitch": "الطلب والمنافسة وضغط السوق يحددون درجة هجومية الخطة.",
            "monthly_searches": "طلب بحث شهري",
            "pressure_copy": "مزيج الطلب والمنافسة",
            "personas_pitch": "كل شخصية تربط حاجة حقيقية بوعد تسويقي محدد.",
            "strategic_direction": "الاتجاه الاستراتيجي",
            "strategy_pitch": "القصة التسويقية التي تحول إشارات السوق إلى قرارات عملية.",
            "message": "الرسالة المركزية",
            "channels": "القنوات",
            "differentiation": "زاوية التميز",
            "themes": "محاور المحتوى",
            "message_copy": "نعرض الحل كمسار واضح من الحاجة إلى نتيجة قابلة للفهم.",
            "content_engine": "محتوى تعليمي قصير وإعادة استهداف.",
            "differentiation_copy": "نستخدم الإثبات، الصلة المحلية، ووعد خدمة مركز.",
            "themes_copy": "مشاكل، مقارنات، قصص نجاح، اعتراضات، وعروض مباشرة.",
            "execution": "تنفيذ 30 / 60 / 90 يوم",
            "execution_pitch": "طريق بسيط من الاستراتيجية إلى الفعل.",
            "days_30": "توضيح العرض، رسالة الهبوط، والكلمات ذات الأولوية.",
            "days_60": "إطلاق محتوى وحملات بحث حول الطلب الأعلى نية.",
            "days_90": "توسيع الفائز، إعادة استهداف الجمهور الدافئ، وتعميق الإثبات المحلي.",
            "closing": "الصورة التسويقية الكاملة جاهزة.",
            "closing_copy": "هذا العرض يربط العرض، الطلب، المنافسين، شخصيات العملاء، وأولويات التنفيذ في خطة عملية واحدة.",
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
            "brand": "מותג",
            "market": "שוק",
            "audience": "קהל יעד",
            "language": "שפה",
            "location": "מיקום",
            "project_nature": "אופי הפרויקט",
            "marketing_plan": "תכנית צמיחה ושיווק",
            "snapshot": "תמונת הפרויקט",
            "snapshot_subtitle": "נקודת הפתיחה האסטרטגית לפני החלטות ערוצים ותוכן.",
            "deck_metric_services": "עמודי הצעה",
            "deck_metric_keywords": "מונחי שוק",
            "deck_metric_competitors": "סימני תחרות",
            "services_pitch": "מערכת ההצעה שנהפוך לביקוש ולמסרי קמפיין ברורים.",
            "service_card_copy": "עמוד הצעה ברור למיצוב, תוכן ומבנה קמפיינים.",
            "market_reading": "קריאת שוק",
            "market_reading_subtitle": "מה השוק מספר לנו לפני שהאסטרטגיה הופכת לביצוע.",
            "opportunity": "הזדמנות",
            "problem": "בעיית השוק",
            "positioning": "מיצוב",
            "opportunity_copy": "בונים ביקוש סביב בעיה ברורה, הוכחה ותוצאה מובנת.",
            "problem_copy": "הקהל צריך סיבה חדה יותר לבחור בעסק עכשיו.",
            "positioning_copy": "מובילים עם אמון, בידול וקריאה ברורה לפעולה.",
            "direct_intent": "מילות ביקוש ישיר",
            "learning_intent": "מילות שאלות ולמידה",
            "comparison_intent": "מילות השוואה ובחירה",
            "local_intent": "מילות חיפוש מקומי",
            "direct_intent_help": "ביטויים של אדם שקרוב לבקשת שירות או קנייה.",
            "learning_intent_help": "ביטויים שהקהל משתמש בהם כדי להבין בעיה או ללמוד פתרון.",
            "comparison_intent_help": "ביטויים שמופיעים לפני בחירה בין ספקים או פתרונות.",
            "local_intent_help": "ביטויים עם כוונה מקומית כמו קרוב, עיר, אזור או מפות.",
            "keywords_missing": "יש ליצור מילות מפתח כדי להציג כאן קבוצות כוונת חיפוש.",
            "market_services_missing": "יש להוסיף שירותים/מוצרים כדי להציג כאן את צירי ההצעה.",
            "market_pressure_missing": "נתוני ביקוש והיצע עדיין לא זמינים; מתחילים מסימני מילות מפתח ומתחרים.",
            "keywords_pitch": "מילות המפתח הופכות לקבוצות כוונה, לא לרשימה שטוחה.",
            "competitors_pitch": "מתחרים הם סימני שוק: הצעות, מיצוב ולחץ ערוצים.",
            "missing_source": "מקור זה עדיין לא הפיק מתחרים ישירים.",
            "market_signal": "יש לבדוק מקור זה כדי לזהות רמזי מיצוב.",
            "demand_pitch": "ביקוש, תחרות ולחץ שוק קובעים את עוצמת התכנית.",
            "monthly_searches": "ביקוש חיפוש חודשי",
            "pressure_copy": "שילוב ביקוש ותחרות",
            "personas_pitch": "כל פרסונה מחברת צורך אמיתי להבטחה שיווקית ממוקדת.",
            "strategic_direction": "כיוון אסטרטגי",
            "strategy_pitch": "הסיפור השיווקי שהופך סימני שוק להחלטות מעשיות.",
            "message": "מסר מרכזי",
            "channels": "ערוצים",
            "differentiation": "זווית בידול",
            "themes": "נושאי תוכן",
            "message_copy": "מציגים את ההצעה כמסלול ברור מצורך לתוצאה מובנת.",
            "content_engine": "תוכן לימודי קצר וריטרגטינג.",
            "differentiation_copy": "משתמשים בהוכחה, רלוונטיות מקומית והבטחת שירות ממוקדת.",
            "themes_copy": "בעיות, השוואות, סיפורי הצלחה, התנגדויות והצעות ישירות.",
            "execution": "ביצוע 30 / 60 / 90 יום",
            "execution_pitch": "דרך פשוטה מאסטרטגיה לפעולה.",
            "days_30": "חידוד ההצעה, מסר הנחיתה ומילות המפתח בעדיפות.",
            "days_60": "השקת תוכן וקמפייני חיפוש סביב ביקוש בכוונה גבוהה.",
            "days_90": "הרחבת המנצחים, ריטרגטינג לקהל חם והעמקת הוכחה מקומית.",
            "closing": "התמונה השיווקית המלאה מוכנה.",
            "closing_copy": "המצגת מחברת הצעה, ביקוש, מתחרים, פרסונות וסדרי עדיפויות לתכנית אחת מעשית.",
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
        "brand": "Brand",
        "market": "Market",
        "audience": "Audience",
        "language": "Language",
        "location": "Location",
        "project_nature": "Project nature",
        "marketing_plan": "Marketing growth plan",
        "snapshot": "Business snapshot",
        "snapshot_subtitle": "The strategic starting point before channel and content decisions.",
        "deck_metric_services": "offer areas",
        "deck_metric_keywords": "market terms",
        "deck_metric_competitors": "market signals",
        "services_pitch": "The offer system we will turn into demand and clear campaign messages.",
        "service_card_copy": "A clear offer pillar for positioning, content, and campaign structure.",
        "market_reading": "Market reading",
        "market_reading_subtitle": "What the market is telling us before we turn strategy into execution.",
        "opportunity": "Opportunity",
        "problem": "Market problem",
        "positioning": "Positioning",
        "opportunity_copy": "Build demand around clear problems, proof, and service outcomes.",
        "problem_copy": "The audience needs a sharper reason to choose this business now.",
        "positioning_copy": "Lead with credibility, clear differentiation, and direct calls to action.",
        "direct_intent": "Direct demand",
        "learning_intent": "Questions and learning",
        "comparison_intent": "Comparison and choice",
        "local_intent": "Local search",
        "direct_intent_help": "Phrases from someone close to requesting or buying.",
        "learning_intent_help": "Phrases people use to understand the problem or learn the solution.",
        "comparison_intent_help": "Phrases that appear before choosing between providers or solutions.",
        "local_intent_help": "Phrases with local intent such as near me, city, area, or maps.",
        "keywords_missing": "Generate keywords to show search-intent groups here.",
        "market_services_missing": "Add services/products so the offer pillars can appear here.",
        "market_pressure_missing": "Demand and supply numbers are not available yet; start from keyword and competitor signals.",
        "keywords_pitch": "Search terms become intent groups, not just a flat list.",
        "competitors_pitch": "Competitors are market signals: offers, positioning, and channel pressure.",
        "missing_source": "This source has not produced direct competitors yet.",
        "market_signal": "Review this source for positioning clues.",
        "demand_pitch": "Demand, competition, and market pressure help decide how aggressive the plan should be.",
        "monthly_searches": "monthly search demand",
        "pressure_copy": "combined demand and competition",
        "personas_pitch": "Each persona connects a real need to a focused marketing promise.",
        "strategic_direction": "Strategic direction",
        "strategy_pitch": "The marketing story that turns market signals into client-facing decisions.",
        "message": "Core message",
        "channels": "Channels",
        "differentiation": "Differentiation",
        "themes": "Content themes",
        "message_copy": "Present the offer as a clear path from need to measurable outcome.",
        "content_engine": "Short educational content and retargeting.",
        "differentiation_copy": "Use proof, local relevance, and a focused service promise.",
        "themes_copy": "Problems, comparisons, success stories, objections, and direct offers.",
        "execution": "30 / 60 / 90 day execution",
        "execution_pitch": "A simple path from strategy to action.",
        "days_30": "Clarify offer, landing message, and priority keywords.",
        "days_60": "Launch content and search campaigns around high-intent demand.",
        "days_90": "Scale winners, retarget warm audiences, and deepen local proof.",
        "closing": "The full marketing picture is ready.",
        "closing_copy": "This deck connects the offer, market demand, competitors, customer personas, and execution priorities into one practical plan.",
    }


def _styles(language: str, font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    alignment = TA_RIGHT if _is_rtl(language) else TA_LEFT
    return {
        "cover": ParagraphStyle(
            "MarketingDeckCover",
            parent=base["Title"],
            fontName=font_name,
            fontSize=34,
            leading=42,
            alignment=alignment,
            textColor=TEXT_LIGHT,
            spaceAfter=12,
        ),
        "title": ParagraphStyle(
            "MarketingDeckTitle",
            parent=base["Heading1"],
            fontName=font_name,
            fontSize=25,
            leading=31,
            alignment=alignment,
            textColor=TEXT_LIGHT,
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "MarketingDeckSection",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=13,
            leading=17,
            alignment=alignment,
            textColor=ACCENT,
            spaceAfter=4,
        ),
        "card_title": ParagraphStyle(
            "MarketingDeckCardTitle",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=13,
            leading=17,
            alignment=alignment,
            textColor=TEXT_LIGHT,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "MarketingDeckBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.5,
            leading=14,
            alignment=alignment,
            textColor=TEXT_MUTED,
        ),
        "small": ParagraphStyle(
            "MarketingDeckSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.5,
            leading=10,
            alignment=alignment,
            textColor=TEXT_DIM,
        ),
        "metric": ParagraphStyle(
            "MarketingDeckMetric",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=24,
            leading=29,
            alignment=TA_CENTER,
            textColor=TEXT_LIGHT,
        ),
    }


def _label(labels: dict[str, str], key: str, fallback: str) -> str:
    return labels.get(key) or fallback


def _para(value: Any, language: str, styles: dict[str, ParagraphStyle], style: str, fonts: dict[str, str], default_font: str) -> Paragraph:
    return Paragraph(_p(value, language, fonts, default_font), styles[style])


def _clamp_text(value: Any, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", str(value or "").translate(BIDI_CONTROL_CHARS)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _compact_url(value: Any, limit: int = 38) -> str:
    text = str(value or "").strip().replace("https://", "").replace("http://", "")
    text = text.split("?")[0].strip("/")
    return _clamp_text(text, limit) if text else "-"


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)] or [[]]


def _text_or_empty(items: list[Any], labels: dict[str, str]) -> list[Any]:
    return items if items else [labels["empty"]]


def _slide_title(
    story: list[Any],
    title: str,
    subtitle: str | None,
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
    section: str | None = None,
) -> None:
    if section:
        story.append(_para(section, language, styles, "section", fonts, default_font))
    story.append(_para(title, language, styles, "title", fonts, default_font))
    if subtitle:
        story.append(_para(_clamp_text(subtitle, 190), language, styles, "body", fonts, default_font))
    story.append(Spacer(1, 0.14 * inch))


def _pitch_card(
    title: str,
    lines: list[Any],
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
    accent: colors.Color = ACCENT,
    width: float = 248,
    max_lines: int = 4,
) -> Table:
    is_rtl = _is_rtl(language)
    content: list[Any] = [_para(_clamp_text(title, 70), language, styles, "card_title", fonts, default_font)]
    for line in lines[:max_lines]:
        if line is None or str(line).strip() == "":
            continue
        content.append(_para(_clamp_text(line, 135), language, styles, "body", fonts, default_font))
    table = Table([[content]], colWidths=[width], hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.9, CARD_BORDER),
                ("LINEAFTER" if is_rtl else "LINEBEFORE", (0, 0), (0, -1), 4, accent),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def _metric_card(
    title: str,
    value: Any,
    detail: str,
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
    accent: colors.Color,
) -> Table:
    content = [
        _para(title, language, styles, "body", fonts, default_font),
        _para(value, language, styles, "metric", fonts, default_font),
        _para(detail, language, styles, "small", fonts, default_font),
    ]
    table = Table([[content]], colWidths=[246], hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.9, CARD_BORDER),
                ("LINEABOVE", (0, 0), (-1, 0), 4, accent),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def _pitch_grid(story: list[Any], cards: list[Table], columns: int = 3, col_width: float = 260, language: str = "en") -> None:
    rows: list[list[Any]] = []
    is_rtl = _is_rtl(language)
    for index in range(0, len(cards), columns):
        row = cards[index : index + columns]
        while len(row) < columns:
            row.append("")
        if is_rtl:
            row = list(reversed(row))
        rows.append(row)
    if not rows:
        return
    table = Table(rows, colWidths=[col_width] * columns, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)


def _section_break(
    story: list[Any],
    title: str,
    subtitle: str,
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
) -> None:
    story.append(Spacer(1, 1.25 * inch))
    story.append(_para(title, language, styles, "cover", fonts, default_font))
    story.append(_para(subtitle, language, styles, "body", fonts, default_font))


def _draw_deck_page(canvas: Any, document: SimpleDocTemplate) -> None:
    canvas.saveState()
    width, height = SLIDE_SIZE
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(PANEL_BG)
    canvas.rect(width * 0.64, 0, width * 0.36, height, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, height - 5, width, 5, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#0b2d5c"))
    canvas.circle(width - 92, height - 92, 80, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#0f766e"))
    canvas.circle(width - 66, height - 70, 42, fill=1, stroke=0)
    canvas.setFillColor(TEXT_DIM)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(SLIDE_MARGIN, 18, f"OneShare / Cosuite - {document.page}")
    canvas.restoreState()


def _business_snapshot(suite: Suite, labels: dict[str, str]) -> list[tuple[str, str]]:
    brand = _brand(suite)
    strategy = _strategy(suite)
    return [
        (_label(labels, "brand", "Brand"), brand.get("name") or suite.name or "-"),
        (_label(labels, "market", "Market"), brand.get("industry") or brand.get("category") or strategy.get("business_category") or "-"),
        (_label(labels, "audience", "Audience"), brand.get("target_audience") or brand.get("audience") or "-"),
        (_label(labels, "language", "Language"), brand.get("language") or strategy.get("language") or "-"),
        (_label(labels, "location", "Location"), brand.get("location") or brand.get("country") or "-"),
        (_label(labels, "project_nature", "Project nature"), _label(labels, "marketing_plan", "Marketing growth plan")),
    ]


def _keyword_groups(intelligence: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str, list[str]]]:
    definitions = {
        "direct": (_label(labels, "direct_intent", "Direct demand"), _label(labels, "direct_intent_help", "Phrases from someone close to requesting or buying."), []),
        "learning": (_label(labels, "learning_intent", "Questions and learning"), _label(labels, "learning_intent_help", "Phrases people use to understand the problem or learn the solution."), []),
        "comparison": (_label(labels, "comparison_intent", "Comparison and choice"), _label(labels, "comparison_intent_help", "Phrases that appear before choosing between providers or solutions."), []),
        "local": (_label(labels, "local_intent", "Local search"), _label(labels, "local_intent_help", "Phrases with local intent such as near me, city, area, or maps."), []),
    }
    keywords = [item for item in _safe_list(intelligence.get("keywords")) if isinstance(item, dict)]
    for item in keywords:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        marker = f"{item.get('intent') or ''} {text}".lower()
        if any(word in marker for word in ("near", "local", "map", "قريب", "محلي", "אזור", "קרוב")):
            key = "local"
        elif any(word in marker for word in ("compare", "best", "vs", "مقارنة", "أفضل", "השוואה")):
            key = "comparison"
        elif any(word in marker for word in ("learn", "how", "course", "تعلم", "دورة", "איך", "קורס")):
            key = "learning"
        else:
            key = "direct"
        definitions[key][2].append(text)
    return [(title, helper, values[:8]) for title, helper, values in definitions.values() if values]


def _competitors_by_source(intelligence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in _safe_list(intelligence.get("competitors")):
        if not isinstance(item, dict):
            continue
        source = str(item.get("result_type") or item.get("platform") or item.get("source") or "other")
        grouped.setdefault(source, []).append(item)
    return grouped


def _market_insights(suite: Suite, intelligence: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[str]]]:
    services = _services(suite)[:4]
    keyword_count = len(_safe_list(intelligence.get("keywords")))
    competitor_count = len(_safe_list(intelligence.get("competitors")))
    demand_supply = _safe_dict(intelligence.get("demand_supply"))
    summary = _safe_dict(demand_supply.get("summary"))
    return [
        (_label(labels, "opportunity", "Opportunity"), [
            _label(labels, "opportunity_copy", "Build demand around clear problems, proof, and service outcomes."),
            ", ".join(services) if services else _label(labels, "market_services_missing", "Add services/products so the offer pillars can appear here."),
        ]),
        (_label(labels, "problem", "Market problem"), [
            _label(labels, "problem_copy", "The audience needs a sharper reason to choose this business now."),
            f"{keyword_count} {labels['keywords']} / {competitor_count} {labels['competitors']}",
        ]),
        (_label(labels, "positioning", "Positioning"), [
            _label(labels, "positioning_copy", "Lead with credibility, clear differentiation, and direct calls to action."),
            f"{labels['pressure']}: {summary.get('market_pressure_score', 0)}/100" if summary else _label(labels, "market_pressure_missing", "Demand and supply numbers are not available yet; start from keyword and competitor signals."),
        ]),
    ]


def _strategic_direction(suite: Suite, intelligence: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[str]]]:
    services = _services(suite)[:3]
    keywords = [item.get("text") for item in _safe_list(intelligence.get("keywords")) if isinstance(item, dict) and item.get("text")][:4]
    return [
        (_label(labels, "message", "Core message"), [
            _label(labels, "message_copy", "Present the offer as a clear path from need to measurable outcome."),
            ", ".join(services) if services else labels["empty"],
        ]),
        (_label(labels, "channels", "Channels"), [
            "Google Search / Maps",
            "Instagram / Facebook",
            _label(labels, "content_engine", "Short educational content and retargeting."),
        ]),
        (_label(labels, "differentiation", "Differentiation"), [
            _label(labels, "differentiation_copy", "Use proof, local relevance, and a focused service promise."),
            ", ".join(keywords) if keywords else labels["empty"],
        ]),
        (_label(labels, "themes", "Content themes"), [
            _label(labels, "themes_copy", "Problems, comparisons, success stories, objections, and direct offers."),
        ]),
    ]


def _execution_steps(action_plan: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[str]]]:
    items = [
        *[item for item in _safe_list(action_plan.get("social_items")) if isinstance(item, dict)],
        *[item for item in _safe_list(action_plan.get("ad_funnel_items")) if isinstance(item, dict)],
    ]
    titles = [str(item.get("title") or item.get("objective") or "").strip() for item in items if item.get("title") or item.get("objective")]
    return [
        ("30", [_label(labels, "days_30", "Clarify offer, landing message, and priority keywords."), *titles[:2]]),
        ("60", [_label(labels, "days_60", "Launch content and search campaigns around high-intent demand."), *titles[2:4]]),
        ("90", [_label(labels, "days_90", "Scale winners, retarget warm audiences, and deepen local proof."), *titles[4:6]]),
    ]


def _append_page(story: list[Any], content: list[Any]) -> None:
    if story:
        story.append(PageBreak())
    story.extend(content)


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
        pagesize=SLIDE_SIZE,
        rightMargin=SLIDE_MARGIN,
        leftMargin=SLIDE_MARGIN,
        topMargin=36,
        bottomMargin=32,
        title=str(_brand(suite).get("name") or suite.name or labels["title"]),
    )

    action_plan = _action_plan(suite)
    demand_supply = _safe_dict(intelligence.get("demand_supply"))
    summary = _safe_dict(demand_supply.get("summary"))
    story: list[Any] = []
    suite_name = _brand(suite).get("name") or suite.name or "Suite"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 1. Cover
    cover_cards = [
        _metric_card(labels["services"], len(_services(suite)), _label(labels, "deck_metric_services", "offer areas"), language, styles, fonts, default_font, ACCENT_3),
        _metric_card(labels["keywords"], len(_safe_list(intelligence.get("keywords"))), _label(labels, "deck_metric_keywords", "market terms"), language, styles, fonts, default_font, ACCENT),
        _metric_card(labels["competitors"], len(_safe_list(intelligence.get("competitors"))), _label(labels, "deck_metric_competitors", "market signals"), language, styles, fonts, default_font, ACCENT_2),
    ]
    _append_page(story, [
        Spacer(1, 0.95 * inch),
        _para(f"{suite_name}", language, styles, "cover", fonts, default_font),
        _para(labels["title"], language, styles, "title", fonts, default_font),
        _para(labels["subtitle"], language, styles, "body", fonts, default_font),
        Spacer(1, 0.22 * inch),
    ])
    _pitch_grid(story, cover_cards, columns=3, col_width=260, language=language)
    story.append(Spacer(1, 0.12 * inch))
    story.append(_para(f"{labels['generated']}: {generated_at}", language, styles, "small", fonts, default_font))

    # 2. Business snapshot
    snapshot_cards = [
        _pitch_card(title, [value], language, styles, fonts, default_font, ACCENT, width=248, max_lines=2)
        for title, value in _business_snapshot(suite, labels)
    ]
    _append_page(story, [])
    _slide_title(story, _label(labels, "snapshot", "Business snapshot"), _label(labels, "snapshot_subtitle", "The strategic starting point before channel and content decisions."), language, styles, fonts, default_font, labels["overview"])
    _pitch_grid(story, snapshot_cards, columns=3, col_width=260, language=language)

    # 3. Services/products
    for page_index, group in enumerate(_chunks(_text_or_empty(_services(suite), labels), 6)):
        _append_page(story, [])
        _slide_title(story, labels["services"], _label(labels, "services_pitch", "The offer system we will turn into demand and clear campaign messages."), language, styles, fonts, default_font, str(page_index + 1).zfill(2))
        cards = [_pitch_card(str(item), [_label(labels, "service_card_copy", "A clear offer pillar for positioning, content, and campaign structure.")], language, styles, fonts, default_font, ACCENT_3, width=248, max_lines=2) for item in group]
        _pitch_grid(story, cards, columns=3, col_width=260, language=language)

    # 4. Market reading
    _append_page(story, [])
    _slide_title(story, _label(labels, "market_reading", "Market reading"), _label(labels, "market_reading_subtitle", "What the market is telling us before we turn strategy into execution."), language, styles, fonts, default_font, labels["overview"])
    cards = [
        _pitch_card(title, lines, language, styles, fonts, default_font, ACCENT, width=248)
        for title, lines in _market_insights(suite, intelligence, labels)
    ]
    _pitch_grid(story, cards, columns=3, col_width=260, language=language)

    # 5. Keywords by intent
    keyword_groups = _keyword_groups(intelligence, labels)
    _append_page(story, [])
    _slide_title(story, labels["keywords"], _label(labels, "keywords_pitch", "Search terms become intent groups, not just a flat list."), language, styles, fonts, default_font, "03")
    keyword_cards = [
        _pitch_card(title, [helper, *values], language, styles, fonts, default_font, ACCENT_2, width=366, max_lines=7)
        for title, helper, values in keyword_groups
    ]
    if not keyword_cards:
        keyword_cards = [
            _pitch_card(labels["keywords"], [_label(labels, "keywords_missing", "Generate keywords to show search-intent groups here.")], language, styles, fonts, default_font, ACCENT_2, width=366, max_lines=2)
        ]
    _pitch_grid(story, keyword_cards, columns=2, col_width=390, language=language)

    # 6. Competitors by source
    grouped_competitors = _competitors_by_source(intelligence)
    sources = ["google_organic", "maps", "instagram", "facebook", "tiktok"]
    for source in sources:
        items = grouped_competitors.get(source, [])
        _append_page(story, [])
        source_title = source.replace("_", " ").title()
        _slide_title(story, f"{labels['competitors']} - {source_title}", _label(labels, "competitors_pitch", "Competitors are market signals: offers, positioning, and channel pressure."), language, styles, fonts, default_font, "04")
        cards = []
        for item in (items[:4] or [{"title": labels["empty"], "url": "-", "snippet": _label(labels, "missing_source", "This source has not produced direct competitors yet.")}]):
            cards.append(
                _pitch_card(
                    item.get("title") or item.get("name") or labels["empty"],
                    [
                        f"{labels['source']}: {source_title}",
                        f"{labels['link']}: {_compact_url(item.get('url'))}",
                        item.get("snippet") or item.get("description") or _label(labels, "market_signal", "Review this source for positioning clues."),
                    ],
                    language,
                    styles,
                    fonts,
                    default_font,
                    ACCENT,
                    width=366,
                    max_lines=3,
                )
            )
        _pitch_grid(story, cards, columns=2, col_width=390, language=language)

    # 7. Demand/supply
    _append_page(story, [])
    _slide_title(story, labels["demand"], _label(labels, "demand_pitch", "Demand, competition, and market pressure help decide how aggressive the plan should be."), language, styles, fonts, default_font, "05")
    metrics_cards = [
        _metric_card(labels["searches"], summary.get("average_monthly_searches", 0) if summary else 0, _label(labels, "monthly_searches", "monthly search demand"), language, styles, fonts, default_font, ACCENT_3),
        _metric_card(labels["competition"], summary.get("competition_level", "UNKNOWN") if summary else "UNKNOWN", "Google Ads", language, styles, fonts, default_font, ACCENT),
        _metric_card(labels["pressure"], f"{summary.get('market_pressure_score', 0) if summary else 0}/100", _label(labels, "pressure_copy", "combined demand and competition"), language, styles, fonts, default_font, ACCENT_2),
    ]
    _pitch_grid(story, metrics_cards, columns=3, col_width=260, language=language)
    metrics = [item for item in _safe_list(demand_supply.get("keyword_metrics")) if isinstance(item, dict)]
    if metrics:
        story.append(Spacer(1, 0.12 * inch))
        cards = [
            _pitch_card(
                item.get("keyword") or "-",
                [
                    f"{labels['searches']}: {item.get('average_monthly_searches', 0)}",
                    f"{labels['competition']}: {item.get('competition') or 'UNKNOWN'} {item.get('competition_index') or ''}",
                ],
                language,
                styles,
                fonts,
                default_font,
                ACCENT_3,
                width=248,
                max_lines=2,
            )
            for item in metrics[:3]
        ]
        _pitch_grid(story, cards, columns=3, col_width=260, language=language)

    # 8. Personas
    personas = [item for item in _safe_list(intelligence.get("personas")) if isinstance(item, dict)]
    persona_items = personas or [{"name": labels["empty"]}]
    for page_index, group in enumerate(_chunks(persona_items[:10], 3)):
        _append_page(story, [])
        _slide_title(story, labels["personas"], _label(labels, "personas_pitch", "Each persona connects a real need to a focused marketing promise."), language, styles, fonts, default_font, f"06.{page_index + 1}")
        cards = []
        for persona in group:
            meta = " / ".join(
                str(value)
                for value in [
                    f"{labels['age']}: {persona.get('age')}" if persona.get("age") else "",
                    persona.get("gender") or "",
                    persona.get("profession") or "",
                    persona.get("economic_status") or "",
                ]
                if value
            )
            cards.append(
                _pitch_card(
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
                    ACCENT_2,
                    width=248,
                    max_lines=4,
                )
            )
        _pitch_grid(story, cards, columns=3, col_width=260, language=language)

    # 9. Strategic direction
    _append_page(story, [])
    _slide_title(story, _label(labels, "strategic_direction", "Strategic direction"), _label(labels, "strategy_pitch", "The marketing story that turns market signals into client-facing decisions."), language, styles, fonts, default_font, "07")
    strategy_cards = [
        _pitch_card(title, lines, language, styles, fonts, default_font, ACCENT, width=366, max_lines=3)
        for title, lines in _strategic_direction(suite, intelligence, labels)
    ]
    _pitch_grid(story, strategy_cards, columns=2, col_width=390, language=language)

    # 10. 30/60/90 execution
    _append_page(story, [])
    _slide_title(story, _label(labels, "execution", "30 / 60 / 90 day execution"), _label(labels, "execution_pitch", "A simple path from strategy to action."), language, styles, fonts, default_font, "08")
    execution_cards = [
        _pitch_card(title, lines, language, styles, fonts, default_font, ACCENT_3, width=248, max_lines=4)
        for title, lines in _execution_steps(action_plan, labels)
    ]
    _pitch_grid(story, execution_cards, columns=3, col_width=260, language=language)

    # 11. Closing
    _append_page(story, [])
    _section_break(
        story,
        _label(labels, "closing", "The full marketing picture is ready."),
        _label(labels, "closing_copy", "This deck connects the offer, market demand, competitors, customer personas, and execution priorities into one practical plan."),
        language,
        styles,
        fonts,
        default_font,
    )
    story.append(Spacer(1, 0.2 * inch))
    story.append(_para(labels["generated_by"], language, styles, "small", fonts, default_font))

    document.build(story, onFirstPage=_draw_deck_page, onLaterPages=_draw_deck_page)
    return buffer.getvalue(), _filename(suite)
