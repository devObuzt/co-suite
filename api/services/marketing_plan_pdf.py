"""Build downloadable marketing plan PDFs from saved suite data."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
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

log = logging.getLogger(__name__)

# Apt library dirs for the WeasyPrint subprocess fallback (nix python cannot
# dlopen apt-installed pango/gobject without an explicit LD_LIBRARY_PATH).
_SYSTEM_LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu")

# Never expose the core toolchain libs to the subprocess — shadowing the nix
# python's own libc/ssl family crashes the interpreter at startup.
_LIB_EXCLUDE_PREFIXES = (
    "libc.", "libc-", "libm.", "libm-", "libmvec", "libpthread", "libdl", "librt",
    "ld-", "libresolv", "libnsl", "libutil", "libgcc_s", "libstdc++",
    "libssl", "libcrypto", "libnss_", "libanl",
)


def _prepare_weasyprint_lib_dir(tmp: Path) -> str:
    """Symlink only the pango/gobject dependency closure into a private dir."""
    libdir = tmp / "libs"
    libdir.mkdir(exist_ok=True)
    for src_dir in _SYSTEM_LIB_DIRS:
        source = Path(src_dir)
        if not source.is_dir():
            continue
        for so_path in source.glob("lib*.so*"):
            if so_path.name.startswith(_LIB_EXCLUDE_PREFIXES):
                continue
            target = libdir / so_path.name
            if not target.exists():
                try:
                    target.symlink_to(so_path)
                except OSError:
                    continue
    return str(libdir)


def _render_html_to_pdf(html: str) -> bytes:
    try:
        import weasyprint

        return weasyprint.HTML(string=html).write_pdf()
    except OSError as exc:
        log.warning("WeasyPrint in-process load failed (%s); falling back to subprocess", exc)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        html_path = tmp_path / "deck.html"
        pdf_path = tmp_path / "deck.pdf"
        html_path.write_text(html, encoding="utf-8")
        env = dict(os.environ)
        libdir = _prepare_weasyprint_lib_dir(tmp_path)
        env["LD_LIBRARY_PATH"] = libdir + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        result = subprocess.run(
            [sys.executable, "-m", "weasyprint", str(html_path), str(pdf_path)],
            env=env,
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(f"weasyprint subprocess failed: {result.stderr.decode(errors='replace')[-400:]}")
        return pdf_path.read_bytes()


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


def _clean_list(values: Any, limit: int = 5) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    source = values if isinstance(values, list) else [values]
    for value in source:
        if isinstance(value, dict):
            value = value.get("name") or value.get("label") or value.get("value") or ""
        text = re.sub(r"\s+", " ", str(value or "").translate(BIDI_CONTROL_CHARS)).strip(" ,،")
        marker = text.casefold()
        if text and marker not in seen:
            seen.add(marker)
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _localized_join(labels: dict[str, str], items: list[str]) -> str:
    separator = "، " if labels.get("worldwide") == "عالمي" else ", "
    return separator.join(items)


def _localized_audience_term(labels: dict[str, str], text: str) -> str:
    if labels.get("worldwide") == "عالمي":
        replacements = {
            "hand made": "يدوية",
            "handmade": "يدوية",
            "worldwide": "عالمي",
            "organic": "عضوية",
        }
    elif labels.get("worldwide") == "עולמי":
        replacements = {
            "hand made": "עבודת יד",
            "handmade": "עבודת יד",
            "worldwide": "עולמי",
            "organic": "אורגני",
        }
    else:
        replacements = {}
    value = text
    for source, replacement in replacements.items():
        value = re.sub(re.escape(source), replacement, value, flags=re.IGNORECASE)
    return value


def _audience_location_summary(brand: dict[str, Any], strategy: dict[str, Any], labels: dict[str, str]) -> str:
    location = brand.get("audience_location") or strategy.get("audience_location") or {}
    if isinstance(location, dict):
        if location.get("scope") == "world":
            return labels["worldwide"]
        places = [
            *_clean_list(location.get("countries"), 3),
            *_clean_list(location.get("cities"), 3),
            *_clean_list(location.get("regions"), 3),
        ]
        if places:
            return _localized_join(labels, places)
    places = (
        _clean_list(brand.get("audience_locations"), 3)
        or _clean_list(brand.get("countries"), 3)
        or _clean_list(brand.get("location"), 1)
        or _clean_list(strategy.get("location"), 1)
    )
    return _localized_join(labels, places)


def _looks_like_structured_dump(text: str) -> bool:
    lowered = text.casefold()
    markers = ("worldwide", "الجمهور:", "يهتمون ب", "audience:", "interests:", "{", "}", "[", "]")
    return any(marker in lowered for marker in markers) or text.count(",") >= 4 or text.count("،") >= 4


def _audience_language_summary(brand: dict[str, Any], strategy: dict[str, Any], labels: dict[str, str]) -> str:
    language_names = _clean_list(brand.get("audience_language_names"), 3)
    language_codes = _clean_list(brand.get("audience_languages") or brand.get("languages") or brand.get("audience_language"), 3)
    if labels.get("worldwide") == "عالمي":
        code_labels = {"ar": "العربية", "he": "العبرية", "en": "الإنجليزية"}
    elif labels.get("worldwide") == "עולמי":
        code_labels = {"ar": "ערבית", "he": "עברית", "en": "אנגלית"}
    else:
        code_labels = {"ar": "Arabic", "he": "Hebrew", "en": "English"}
    languages = [code_labels.get(item.casefold(), item) for item in language_codes] or language_names
    tone = str(brand.get("dialect") or brand.get("tone") or strategy.get("tone") or "").strip()
    if languages and tone:
        return f"{_localized_join(labels, languages)}؛ {tone}"
    if languages:
        return _localized_join(labels, languages)
    return labels["audience_language_default"]


def _audience_demographic_summary(brand: dict[str, Any], labels: dict[str, str]) -> str:
    segments = [_localized_audience_term(labels, item) for item in _clean_list(brand.get("audience_social_statuses") or brand.get("audience_segments"), 4)]
    age = str(brand.get("audience_age") or brand.get("audience_age_range") or "").strip()
    gender = str(brand.get("audience_gender") or "").strip()
    if segments:
        base = _localized_join(labels, segments)
        details = _localized_join(labels, [item for item in [age, gender] if item])
        return f"{base}؛ {details}" if details else base
    if age or gender:
        return _localized_join(labels, [item for item in [age, gender] if item])
    return labels["audience_demographic_default"]


def _audience_need_summary(brand: dict[str, Any], strategy: dict[str, Any], labels: dict[str, str]) -> str:
    marketing_plan_audience = _safe_dict(_safe_dict(strategy.get("marketing_plan")).get("audience"))
    raw_values = [
        brand.get("audience_need"),
        brand.get("audience_problem"),
        marketing_plan_audience.get("problem"),
        marketing_plan_audience.get("need"),
        strategy.get("target_audience"),
        brand.get("target_audience"),
        brand.get("audience_notes"),
    ]
    for value in raw_values:
        text = re.sub(r"\s+", " ", str(value or "").translate(BIDI_CONTROL_CHARS)).strip(" .،,")
        if text and not _looks_like_structured_dump(text):
            return _clamp_text(text, 170)
    return labels["audience_need_default"]


def _audience_summary(suite: Suite, labels: dict[str, str]) -> str:
    brand = _brand(suite)
    strategy = _strategy(suite)
    raw = str(strategy.get("target_audience") or brand.get("target_audience") or brand.get("audience") or "").strip()
    location = _audience_location_summary(brand, strategy, labels)
    interests = (
        _clean_list(brand.get("audience_interests"), 4)
        or _clean_list(_safe_dict(_safe_dict(strategy.get("marketing_plan")).get("audience")).get("interests"), 4)
    )
    interests = [_localized_audience_term(labels, item) for item in interests]
    behaviors = [_localized_audience_term(labels, item) for item in _clean_list(brand.get("audience_behaviors"), 4)]
    raw_summary = "" if _looks_like_structured_dump(raw) else _clamp_text(raw, 120)

    parts = [
        f"{labels['audience_geography']}: {location or labels['audience_geography_default']}",
        f"{labels['audience_demographics']}: {_audience_demographic_summary(brand, labels)}",
        f"{labels['audience_language_style']}: {_audience_language_summary(brand, strategy, labels)}",
        f"{labels['audience_behavior_interests']}: {_localized_join(labels, [*(behaviors[:2]), *(interests[:3])]) if behaviors or interests else labels['audience_behavior_default']}",
    ]
    if raw_summary:
        parts.insert(0, f"{labels['audience_summary_prefix']}: {raw_summary}")
    return ". ".join(parts)


def _audience_snapshot_summary(suite: Suite, labels: dict[str, str]) -> str:
    brand = _brand(suite)
    strategy = _strategy(suite)
    need = _audience_need_summary(brand, strategy, labels)
    location = _audience_location_summary(brand, strategy, labels) or labels["audience_geography_default"]
    language = _audience_language_summary(brand, strategy, labels)
    return f"{labels['audience_geography']}: {location}. {labels['audience_language_style']}: {language}. {labels['audience_need']}: {need}"


def _audience_profile_cards(
    suite: Suite,
    labels: dict[str, str],
    language: str,
    styles: dict[str, ParagraphStyle],
    fonts: dict[str, str],
    default_font: str,
) -> list[Table]:
    brand = _brand(suite)
    strategy = _strategy(suite)
    marketing_plan_audience = _safe_dict(_safe_dict(strategy.get("marketing_plan")).get("audience"))
    interests = (
        _clean_list(brand.get("audience_interests"), 6)
        or _clean_list(marketing_plan_audience.get("interests"), 6)
    )
    behaviors = (
        _clean_list(brand.get("audience_behaviors"), 6)
        or _clean_list(marketing_plan_audience.get("behaviors") or marketing_plan_audience.get("digital_behavior"), 6)
    )
    fields = [
        (
            labels["audience_geography"],
            [_audience_location_summary(brand, strategy, labels) or labels["audience_geography_default"]],
            ACCENT,
        ),
        (
            labels["audience_demographics_language"],
            [
                _audience_demographic_summary(brand, labels),
                _audience_language_summary(brand, strategy, labels),
            ],
            ACCENT_2,
        ),
        (
            labels["audience_interests"],
            [_localized_audience_term(labels, item) for item in interests] or [labels["audience_interests_default"]],
            ACCENT_3,
        ),
        (
            labels["audience_behaviors"],
            [_localized_audience_term(labels, item) for item in behaviors] or [labels["audience_behavior_default"]],
            ACCENT,
        ),
        (
            labels["audience_need"],
            [_audience_need_summary(brand, strategy, labels)],
            ACCENT_2,
        ),
    ]
    return [
        _pitch_card(title, lines, language, styles, fonts, default_font, accent, width=248, max_lines=5)
        for title, lines, accent in fields
    ]


def _display_location(suite: Suite, labels: dict[str, str]) -> str:
    brand = _brand(suite)
    strategy = _strategy(suite)
    raw = str(brand.get("location") or brand.get("country") or strategy.get("location") or "").strip()
    if raw.casefold() in {"world", "worldwide", "global"}:
        return labels["worldwide"]
    return raw or _audience_location_summary(brand, strategy, labels) or "-"


def _display_language(suite: Suite) -> str:
    brand = _brand(suite)
    strategy = _strategy(suite)
    language = str(brand.get("language") or strategy.get("language") or "").strip()
    codes = {"ar": "العربية", "he": "עברית", "en": "English"}
    return codes.get(language, language or "-")


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
            "worldwide": "عالمي",
            "audience_general": "الجمهور الأنسب لهذا العرض",
            "audience_interest_prefix": "اهتمامات",
            "audience_location_prefix": "النطاق",
            "audience_summary_prefix": "تعريف الجمهور",
            "audience_pitch": "نفصل الجمهور بوضوح حتى يعرف العميل أننا نفهم لمن نخاطب ولماذا.",
            "audience_geography": "الجغرافيا",
            "audience_geography_default": "النطاق الجغرافي غير محدد بعد",
            "audience_demographics": "الديموغرافيا",
            "audience_demographics_language": "الديموغرافيا واللغة",
            "audience_demographic_default": "شرائح مناسبة لطبيعة المنتج وسعره",
            "audience_language_style": "اللغة والأسلوب",
            "audience_language_default": "لغة الجمهور اليومية والبسيطة",
            "audience_behavior_interests": "السلوكيات والاهتمامات",
            "audience_interests": "الاهتمامات",
            "audience_interests_default": "اهتمامات الجمهور غير محددة بعد",
            "audience_behaviors": "السلوكيات",
            "audience_behavior_default": "يهتمون بالحل العملي، الثقة، وتجربة الشراء الواضحة",
            "audience_need": "الحاجة",
            "audience_need_default": "الحاجة الرئيسية للجمهور غير معبأة بعد. أضفها من بروفايل العلامة التجارية.",
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
            "worldwide": "עולמי",
            "audience_general": "הקהל המתאים ביותר להצעה זו",
            "audience_interest_prefix": "מתעניינים ב",
            "audience_location_prefix": "טווח",
            "audience_summary_prefix": "תיאור הקהל",
            "audience_pitch": "מפרידים את הקהל בבירור כדי להראות למי פונים ולמה.",
            "audience_geography": "גאוגרפיה",
            "audience_geography_default": "הטווח הגאוגרפי עדיין לא הוגדר",
            "audience_demographics": "דמוגרפיה",
            "audience_demographics_language": "דמוגרפיה ושפה",
            "audience_demographic_default": "סגמנטים שמתאימים לאופי המוצר ולמחיר",
            "audience_language_style": "שפה וסגנון",
            "audience_language_default": "שפה יומיומית וברורה של הקהל",
            "audience_behavior_interests": "התנהגויות ותחומי עניין",
            "audience_interests": "תחומי עניין",
            "audience_interests_default": "תחומי העניין של הקהל עדיין לא הוגדרו",
            "audience_behaviors": "התנהגויות",
            "audience_behavior_default": "מחפשים פתרון ברור, אמון וחוויית קנייה פשוטה",
            "audience_need": "צורך",
            "audience_need_default": "הצורך המרכזי של הקהל עדיין לא מולא. יש להוסיף אותו בפרופיל המותג.",
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
        "worldwide": "Worldwide",
        "audience_general": "The most relevant audience for this offer",
        "audience_interest_prefix": "Interested in",
        "audience_location_prefix": "Scope",
        "audience_summary_prefix": "Audience definition",
        "audience_pitch": "Separate audience fields show exactly who we are speaking to and why.",
        "audience_geography": "Geography",
        "audience_geography_default": "Geographic scope is not defined yet",
        "audience_demographics": "Demographics",
        "audience_demographics_language": "Demographics and language",
        "audience_demographic_default": "Segments that fit the product nature and price point",
        "audience_language_style": "Language and style",
        "audience_language_default": "The audience's plain everyday language",
        "audience_behavior_interests": "Behaviors and interests",
        "audience_interests": "Interests",
        "audience_interests_default": "Audience interests are not defined yet",
        "audience_behaviors": "Behaviors",
        "audience_behavior_default": "They care about practical solutions, trust, and a clear buying path",
        "audience_need": "Need",
        "audience_need_default": "The core audience need is not filled yet. Add it in the brand profile.",
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
        (_label(labels, "audience", "Audience"), _audience_snapshot_summary(suite, labels)),
        (_label(labels, "language", "Language"), _display_language(suite)),
        (_label(labels, "location", "Location"), _display_location(suite, labels)),
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



# ── HTML deck renderer (WeasyPrint) ───────────────────────────────────────────

ENGINE_FONT_DIR = Path(__file__).resolve().parents[1] / "engine" / "assets" / "fonts"
API_ROOT = Path(__file__).resolve().parents[1]

DECK_FONT_FILES = {
    ("Deck", 400): ENGINE_FONT_DIR / "Cairo-Regular.ttf",
    ("Deck", 700): ENGINE_FONT_DIR / "Cairo-Bold.ttf",
    ("Deck", 800): ENGINE_FONT_DIR / "Cairo-ExtraBold.ttf",
    ("DeckHebrew", 400): FONT_DIR / "NotoSansHebrew-Regular.ttf",
    ("DeckLatin", 400): FONT_DIR / "Inter-Regular.ttf",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _deck_accent(brand: dict[str, Any]) -> str:
    colors_map = brand.get("colors") if isinstance(brand.get("colors"), dict) else {}
    for candidate in (colors_map.get("primary"), colors_map.get("accent"), colors_map.get("secondary")):
        value = str(candidate or "").strip()
        if _HEX_COLOR_RE.match(value) and value.lower() not in ("#ffffff", "#000000"):
            return value
    return "#e14fd0"


def _font_faces_css() -> str:
    faces = []
    for (family, weight), path in DECK_FONT_FILES.items():
        if path.exists():
            faces.append(
                f"@font-face {{ font-family: '{family}'; src: url('{path.as_uri()}'); "
                f"font-weight: {weight}; font-style: normal; }}"
            )
    return "\n".join(faces)


def _asset_src(url: Any) -> str:
    """Resolve a stored asset URL to something WeasyPrint can fetch."""
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return escape(value, quote=True)
    if value.startswith("/static/"):
        path = API_ROOT / value.lstrip("/")
        if path.exists():
            return escape(path.as_uri(), quote=True)
    return ""


def _logo_src(brand: dict[str, Any]) -> str:
    candidates = [brand.get("logo_url")]
    for asset in brand.get("logo_assets") or []:
        if isinstance(asset, dict):
            candidates.append(asset.get("url"))
    for logo in brand.get("brand_logos") or []:
        if isinstance(logo, dict):
            candidates.append(logo.get("url"))
        elif isinstance(logo, str):
            candidates.append(logo)
    for candidate in candidates:
        src = _asset_src(candidate)
        if src:
            return src
    return ""


def _deck_visual_urls(suite: Suite) -> dict[str, str]:
    strategy = _strategy(suite)
    deck = _safe_dict(strategy.get("marketing_plan_deck"))
    visuals = {}
    for item in [*_safe_list(strategy.get("marketing_plan_visuals")), *_safe_list(deck.get("visuals"))]:
        if isinstance(item, dict) and item.get("url"):
            visuals.setdefault(str(item.get("kind") or f"visual{len(visuals)}"), _asset_src(item["url"]))
    return {kind: src for kind, src in visuals.items() if src}


def _keyword_groups_full(intelligence: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str, list[str]]]:
    """Same grouping as _keyword_groups but WITHOUT truncating the values."""
    grouped = {
        key: (title, helper, [])
        for key, (title, helper, _values) in {
            "direct": (_label(labels, "direct_intent", "Direct demand"), _label(labels, "direct_intent_help", ""), []),
            "learning": (_label(labels, "learning_intent", "Questions and learning"), _label(labels, "learning_intent_help", ""), []),
            "comparison": (_label(labels, "comparison_intent", "Comparison and choice"), _label(labels, "comparison_intent_help", ""), []),
            "local": (_label(labels, "local_intent", "Local search"), _label(labels, "local_intent_help", ""), []),
        }.items()
    }
    for item in _safe_list(intelligence.get("keywords")):
        if not isinstance(item, dict):
            continue
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
        grouped[key][2].append(text)
    return [(title, helper, values) for title, helper, values in grouped.values() if values]


def _chip(text: Any) -> str:
    return f'<span class="chip" dir="auto">{escape(str(text))}</span>'


def _card(title: str, lines: list[str], extra_class: str = "") -> str:
    body = "".join(f'<p dir="auto">{escape(str(line))}</p>' for line in lines if str(line or "").strip())
    return (
        f'<div class="card {extra_class}">'
        f'<h3 dir="auto">{escape(str(title))}</h3>{body}'
        "</div>"
    )


def _section_header(kicker: str, title: str, subtitle: str = "") -> str:
    subtitle_html = f'<p class="section-sub" dir="auto">{escape(subtitle)}</p>' if subtitle else ""
    return (
        f'<p class="kicker" dir="auto">{escape(kicker)}</p>'
        f'<h2 dir="auto">{escape(title)}</h2>{subtitle_html}'
    )


def _divider_section(image_src: str, kicker: str, title: str) -> str:
    if not image_src:
        return ""
    return (
        '<section class="divider">'
        f'<img src="{image_src}" alt="" />'
        '<div class="divider-overlay">'
        f'<p class="kicker" dir="auto">{escape(kicker)}</p>'
        f'<h2 dir="auto">{escape(title)}</h2>'
        "</div></section>"
    )


def _deck_css(accent: str, rtl: bool) -> str:
    direction = "rtl" if rtl else "ltr"
    accent_border = "border-right" if rtl else "border-left"
    return f"""
{_font_faces_css()}
@page {{ size: 1280px 720px; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ background: #17171d; }}
body {{
  font-family: 'Deck', 'DeckHebrew', 'DeckLatin', sans-serif;
  color: #e9e9ef;
  direction: {direction};
  font-size: 15px;
  line-height: 1.65;
}}
section {{ page-break-before: always; padding: 54px 68px; }}
section.cover, section.divider {{ padding: 0; height: 720px; overflow: hidden; }}
section:first-child {{ page-break-before: avoid; }}
.kicker {{ color: {accent}; font-weight: 700; font-size: 15px; letter-spacing: 0.5px; margin-bottom: 4px; }}
h2 {{ font-size: 40px; font-weight: 800; line-height: 1.25; margin-bottom: 6px; }}
.section-sub {{ color: #b9b9c4; font-size: 16px; margin-bottom: 22px; }}
.cards {{ margin-top: 18px; }}
.card {{
  display: inline-block; vertical-align: top; width: 358px;
  background: #212129; border-radius: 16px; padding: 18px 20px;
  margin: 0 0 14px 0; margin-inline-end: 14px;
  {accent_border}: 4px solid {accent};
  page-break-inside: avoid;
}}
.card.wide {{ width: 545px; }}
.card h3 {{ font-size: 18px; font-weight: 700; margin-bottom: 6px; color: #ffffff; }}
.card p {{ color: #c3c3ce; font-size: 14px; line-height: 1.7; }}
.chip {{
  display: inline-block; background: #23232b; color: #e9e9ef;
  border: 1px solid {accent}55; border-radius: 999px;
  padding: 5px 15px; margin: 0 0 9px 0; margin-inline-end: 9px;
  font-size: 14px; page-break-inside: avoid;
}}
.metric {{
  display: inline-block; vertical-align: top; width: 358px;
  background: #212129; border-radius: 16px; padding: 22px;
  margin-inline-end: 14px; text-align: center; page-break-inside: avoid;
}}
.metric .value {{ font-size: 42px; font-weight: 800; color: {accent}; line-height: 1.2; }}
.metric .label {{ font-size: 15px; font-weight: 700; margin-top: 2px; }}
.metric .hint {{ font-size: 12px; color: #9d9daa; }}
.cover-flex {{ width: 100%; height: 720px; }}
.cover-text {{
  display: inline-block; vertical-align: top; width: 55%; height: 720px;
  padding: 70px 68px; background: #17171d;
}}
.cover-text.full {{
  width: 100%; text-align: center; padding-top: 150px;
  background: linear-gradient(160deg, #17171d 55%, {accent}2e 130%);
}}
.cover-text.full .cover-sub {{ margin: 0 auto; }}
.cover-rule {{
  width: 72px; height: 5px; background: {accent}; border-radius: 3px;
  margin: 22px auto 0 auto;
}}
.cover-img {{ display: inline-block; vertical-align: top; width: 44%; height: 720px; }}
.cover-img img {{ width: 100%; height: 720px; object-fit: cover; }}
.cover-logo {{ max-height: 84px; max-width: 220px; margin-bottom: 34px; }}
.cover-name {{ font-size: 54px; font-weight: 800; line-height: 1.2; color: #ffffff; }}
.cover-title {{ color: {accent}; font-size: 22px; font-weight: 700; margin: 8px 0 18px 0; }}
.cover-sub {{ color: #c3c3ce; font-size: 17px; max-width: 480px; }}
.cover-date {{
  display: inline-block; margin-top: 26px; color: #b9b9c4; font-size: 13px;
  border: 1px solid #3a3a44; border-radius: 10px; padding: 5px 14px;
}}
.divider {{ position: relative; }}
.divider img {{ width: 1280px; height: 720px; object-fit: cover; }}
.divider-overlay {{
  position: absolute; top: 0; right: 0; left: 0; bottom: 0;
  background: linear-gradient(to top, #17171dee, #17171d55);
  padding: 250px 90px;
}}
.divider-overlay h2 {{ font-size: 52px; }}
.competitor-link {{ color: {accent}; font-size: 12px; }}
.persona-meta {{ color: {accent}; font-size: 13px; font-weight: 700; }}
.closing {{ text-align: center; padding-top: 210px; }}
.closing h2 {{ font-size: 46px; }}
.footer-note {{ color: #77777f; font-size: 12px; margin-top: 26px; }}
"""


def build_marketing_plan_pdf(suite: Suite) -> tuple[bytes, str]:
    intelligence = _intelligence(suite)
    language = infer_plan_language(suite, intelligence.get("language") or intelligence.get("audience_language"))
    labels = _labels(language)
    rtl = _is_rtl(language)
    brand = _brand(suite)
    strategy = _strategy(suite)
    action_plan = _action_plan(suite)
    accent = _deck_accent(brand)
    visuals = _deck_visual_urls(suite)
    logo = _logo_src(brand)
    suite_name = str(brand.get("name") or suite.name or "Suite")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sections: list[str] = []

    # 1. Cover
    cover_image = visuals.get("cover") or visuals.get("services") or ""
    logo_html = f'<img class="cover-logo" src="{logo}" alt="" />' if logo else ""
    cover_img_html = f'<div class="cover-img"><img src="{cover_image}" alt="" /></div>' if cover_image else ""
    cover_text_class = "cover-text" if cover_image else "cover-text full"
    cover_rule = "" if cover_image else '<div class="cover-rule"></div>'
    sections.append(
        f'<section class="cover"><div class="cover-flex">'
        f'<div class="{cover_text_class}">'
        f"{logo_html}"
        f'<div class="cover-name" dir="auto">{escape(suite_name)}</div>'
        f'<div class="cover-title" dir="auto">{escape(labels["title"])}</div>'
        f'<div class="cover-sub" dir="auto">{escape(labels["subtitle"])}</div>'
        f"{cover_rule}"
        f'<br/><span class="cover-date">{escape(labels["generated"])}: {generated_at}</span>'
        "</div>"
        f"{cover_img_html}"
        "</div></section>"
    )

    # 2. Business snapshot
    snapshot_cards = "".join(_card(title, [value]) for title, value in _business_snapshot(suite, labels))
    sections.append(
        "<section>"
        + _section_header(labels["overview"], _label(labels, "snapshot", "Business snapshot"), _label(labels, "snapshot_subtitle", ""))
        + f'<div class="cards">{snapshot_cards}</div></section>'
    )

    # 3. Audience
    audience_cards = "".join([
        _card(labels["audience_geography"], [_audience_location_summary(brand, strategy, labels) or labels["audience_geography_default"]]),
        _card(labels["audience_demographics_language"], [_audience_demographic_summary(brand, labels), _audience_language_summary(brand, strategy, labels)]),
        _card(labels["audience_need"], [_audience_need_summary(brand, strategy, labels)]),
    ])
    interests = _clean_list(brand.get("audience_interests"), 24)
    behaviors = _clean_list(brand.get("audience_behaviors"), 24)
    interest_chips = "".join(_chip(item) for item in interests)
    behavior_chips = "".join(_chip(item) for item in behaviors)
    audience_extra = ""
    if interest_chips:
        audience_extra += f'<h3 class="kicker" dir="auto">{escape(labels["audience_interests"])}</h3><div>{interest_chips}</div>'
    if behavior_chips:
        audience_extra += f'<h3 class="kicker" dir="auto">{escape(labels["audience_behaviors"])}</h3><div>{behavior_chips}</div>'
    sections.append(
        "<section>"
        + _section_header("02", labels["audience"], _label(labels, "audience_pitch", ""))
        + f'<div class="cards">{audience_cards}</div>{audience_extra}</section>'
    )

    if visuals.get("audience"):
        sections.append(_divider_section(visuals["audience"], labels["audience"], _audience_need_summary(brand, strategy, labels)[:120]))

    # 4. Services — all of them
    services = _services(suite)
    service_chips = "".join(_chip(item) for item in services) or _chip(labels["empty"])
    sections.append(
        "<section>"
        + _section_header("03", labels["services"], _label(labels, "services_pitch", ""))
        + f"<div>{service_chips}</div></section>"
    )

    if visuals.get("services"):
        sections.append(_divider_section(visuals["services"], labels["services"], suite_name))

    # 5. Market reading
    market_cards = "".join(_card(title, lines) for title, lines in _market_insights(suite, intelligence, labels))
    sections.append(
        "<section>"
        + _section_header(labels["overview"], _label(labels, "market_reading", "Market reading"), _label(labels, "market_reading_subtitle", ""))
        + f'<div class="cards">{market_cards}</div></section>'
    )

    # 6. Keywords — all of them, grouped by intent
    keyword_sections = ""
    for title, helper, values in _keyword_groups_full(intelligence, labels):
        chips = "".join(_chip(value) for value in values)
        keyword_sections += (
            f'<h3 class="kicker" dir="auto">{escape(title)} — {len(values)}</h3>'
            f'<p class="section-sub" dir="auto">{escape(helper)}</p><div>{chips}</div>'
        )
    if not keyword_sections:
        keyword_sections = f'<p class="section-sub" dir="auto">{escape(_label(labels, "keywords_missing", ""))}</p>'
    sections.append(
        "<section>"
        + _section_header("04", labels["keywords"], _label(labels, "keywords_pitch", ""))
        + keyword_sections
        + "</section>"
    )

    # 7. Competitors — all items per source
    grouped_competitors = _competitors_by_source(intelligence)
    for source, items in grouped_competitors.items():
        if not items:
            continue
        source_title = source.replace("_", " ").title()
        competitor_cards = "".join(
            _card(
                str(item.get("title") or item.get("name") or labels["empty"]),
                [
                    str(item.get("snippet") or item.get("description") or ""),
                    f"{labels['link']}: {_compact_url(item.get('url'), 60)}",
                ],
                extra_class="wide",
            )
            for item in items
        )
        sections.append(
            "<section>"
            + _section_header("05", f"{labels['competitors']} — {source_title}", _label(labels, "competitors_pitch", ""))
            + f'<div class="cards">{competitor_cards}</div></section>'
        )

    # 8. Demand & supply
    demand_supply = _safe_dict(intelligence.get("demand_supply"))
    summary = _safe_dict(demand_supply.get("summary"))
    metrics = "".join([
        f'<div class="metric"><div class="value">{escape(str(summary.get("average_monthly_searches", 0) if summary else 0))}</div>'
        f'<div class="label" dir="auto">{escape(labels["searches"])}</div>'
        f'<div class="hint" dir="auto">{escape(_label(labels, "monthly_searches", ""))}</div></div>',
        f'<div class="metric"><div class="value">{escape(str(summary.get("competition_level", "-") if summary else "-"))}</div>'
        f'<div class="label" dir="auto">{escape(labels["competition"])}</div>'
        f'<div class="hint">Google Ads</div></div>',
        f'<div class="metric"><div class="value">{escape(str(summary.get("market_pressure_score", 0) if summary else 0))}/100</div>'
        f'<div class="label" dir="auto">{escape(labels["pressure"])}</div>'
        f'<div class="hint" dir="auto">{escape(_label(labels, "pressure_copy", ""))}</div></div>',
    ])
    sections.append(
        "<section>"
        + _section_header("06", labels["demand"], _label(labels, "demand_pitch", ""))
        + f'<div class="cards">{metrics}</div></section>'
    )

    # 9. Personas — all of them
    personas = [item for item in _safe_list(intelligence.get("personas")) if isinstance(item, dict)]
    if personas:
        persona_cards = ""
        for persona in personas:
            meta_bits = [str(persona.get("age") or "").strip(), str(persona.get("profession") or "").strip()]
            meta = " · ".join(bit for bit in meta_bits if bit)
            lines = [
                str(persona.get("needs") or persona.get("need") or "").strip(),
                str(persona.get("challenges") or persona.get("challenge") or "").strip(),
            ]
            body = "".join(f'<p dir="auto">{escape(line)}</p>' for line in lines if line)
            persona_cards += (
                '<div class="card">'
                f'<h3 dir="auto">{escape(str(persona.get("name") or labels["empty"]))}</h3>'
                + (f'<p class="persona-meta" dir="auto">{escape(meta)}</p>' if meta else "")
                + body
                + "</div>"
            )
        sections.append(
            "<section>"
            + _section_header("07", labels["personas"], _label(labels, "personas_pitch", ""))
            + f'<div class="cards">{persona_cards}</div></section>'
        )

    # 10. Strategic direction
    strategy_cards = "".join(_card(title, lines, extra_class="wide") for title, lines in _strategic_direction(suite, intelligence, labels))
    sections.append(
        "<section>"
        + _section_header("08", _label(labels, "strategic_direction", "Strategic direction"), _label(labels, "strategy_pitch", ""))
        + f'<div class="cards">{strategy_cards}</div></section>'
    )

    # 11. 30/60/90 execution
    execution_cards = "".join(_card(title, lines) for title, lines in _execution_steps(action_plan, labels))
    sections.append(
        "<section>"
        + _section_header("09", _label(labels, "execution", "30 / 60 / 90"), _label(labels, "execution_pitch", ""))
        + f'<div class="cards">{execution_cards}</div></section>'
    )

    # 12. Closing
    sections.append(
        '<section class="closing">'
        f'<p class="kicker" dir="auto">{escape(suite_name)}</p>'
        f'<h2 dir="auto">{escape(_label(labels, "closing", ""))}</h2>'
        f'<p class="section-sub" dir="auto">{escape(_label(labels, "closing_copy", ""))}</p>'
        f'<p class="footer-note" dir="auto">{escape(labels["generated_by"])}</p>'
        "</section>"
    )

    html = (
        f'<html dir="{"rtl" if rtl else "ltr"}" lang="{escape(language)}"><head><meta charset="utf-8">'
        f"<title>{escape(suite_name)}</title>"
        f"<style>{_deck_css(accent, rtl)}</style></head><body>"
        + "".join(sections)
        + "</body></html>"
    )
    pdf_bytes = _render_html_to_pdf(html)
    return pdf_bytes, _filename(suite)
