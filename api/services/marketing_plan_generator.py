"""Marketing plan deck generator for OneShare suite strategy pages."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any

from ..core.config import settings
from ..core.llm_client import call_text_ai
from ..models.suite import Suite

log = logging.getLogger(__name__)

PLAN_VERSION = "marketing_plan_deck_v1"
PROMPT_PAYLOAD_CHAR_LIMIT = 16000
MARKETING_PLAN_MAX_TOKENS = 9000
MARKETING_PLAN_TIMEOUT_SECONDS = 320
MARKETING_PLAN_REPAIR_MAX_TOKENS = 7000
MARKETING_PLAN_REPAIR_TIMEOUT_SECONDS = 220


class MarketingPlanGenerationError(RuntimeError):
    """Raised when the AI response cannot produce a useful client-facing plan."""

LANG_NAMES = {
    "ar": "Arabic, natural Palestinian/Levantine professional tone when appropriate",
    "he": "Hebrew",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "tr": "Turkish",
    "ru": "Russian",
    "zh": "Chinese",
}

REQUIRED_SECTIONS = [
    ("executive_summary", "Executive summary"),
    ("current_situation", "Current situation"),
    ("asset_audit", "Digital asset audit"),
    ("market_demand", "Market demand and opportunity"),
    ("competitors", "Competitor landscape"),
    ("audience", "Target audience"),
    ("positioning", "Positioning and message"),
    ("channel_strategy", "Channel strategy"),
    ("content_strategy", "Content strategy"),
    ("campaign_ideas", "Campaign ideas"),
    ("action_plan", "Action plan"),
    ("kpis", "KPIs and measurement"),
    ("budget", "Budget direction"),
    ("next_steps", "Next steps"),
]

FUNNEL_STAGES = ["Awareness", "Consideration", "Conversion", "Loyalty", "Ambassador"]


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escape = 0, False, False
    for i, c in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def parse_marketing_plan_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_json_object(text)
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                log.warning("Could not parse marketing plan JSON: %.240s", raw)
        return {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any, limit: int = 8) -> list[str]:
    items = []
    for item in _list(value):
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        elif isinstance(item, (int, float)):
            items.append(str(item))
    return items[:limit]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text_list(value: Any, limit: int = 8) -> list[str]:
    items = []
    for item in _list(value):
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        elif isinstance(item, (int, float)):
            items.append(str(item))
        elif isinstance(item, dict):
            text = str(
                item.get("title")
                or item.get("name")
                or item.get("summary")
                or item.get("body")
                or item.get("description")
                or item.get("text")
                or ""
            ).strip()
            if text:
                items.append(text)
    return items[:limit]


def _normalize_card(card: Any) -> dict[str, Any] | None:
    if isinstance(card, str):
        return {"title": card, "body": ""}
    if not isinstance(card, dict):
        return None
    title = str(card.get("title") or card.get("name") or "").strip()
    body = str(card.get("body") or card.get("description") or card.get("summary") or "").strip()
    if not title and not body:
        return None
    return {"title": title or body[:64], "body": body, "points": _string_list(card.get("points") or card.get("bullets"), 5)}


def _normalize_metric(metric: Any) -> dict[str, str] | None:
    if not isinstance(metric, dict):
        return None
    label = str(metric.get("label") or metric.get("name") or "").strip()
    value = str(metric.get("value") or metric.get("target") or "").strip()
    if not label and not value:
        return None
    return {"label": label or "Metric", "value": value or "-"}


def _content_type_from_outputs(*values: Any) -> str:
    flattened = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(str(item or "") for item in value)
        else:
            flattened.append(str(value or ""))
    text = " ".join(flattened).lower()
    mentioned = {
        "video": any(token in text for token in ("video", "reel", "story", "ucg", "ugc")),
        "image": any(token in text for token in ("image", "photo", "banner")),
        "carousel": "carousel" in text,
    }
    if sum(1 for active in mentioned.values() if active) > 1:
        return "mixed"
    if "mix" in text:
        return "mixed"
    if "carousel" in text:
        return "carousel"
    if "video" in text or "reel" in text or "story" in text or "ucg" in text or "ugc" in text:
        return "video"
    if "image" in text or "photo" in text or "banner" in text:
        return "image"
    return "mixed"


def _generation_request_for_item(item: dict[str, Any], default_prompt: str = "") -> dict[str, Any]:
    recommended = _dict(item.get("recommended_output"))
    content_type = _content_type_from_outputs(
        recommended.get("format"),
        recommended.get("production_mode"),
        item.get("placement"),
        item.get("recommended_outputs"),
    )
    return {
        "mode": "quick",
        "content_type": content_type,
        "count": 3 if content_type == "mixed" else 1,
        "destination": "both",
        "use_brand": True,
        "prompt": str(item.get("prompt") or default_prompt or item.get("title") or "").strip(),
    }


def _normalize_monthly_work_plan(source: Any) -> dict[str, Any]:
    source = _dict(source)
    content_mix = []
    for item in _list(source.get("content_mix")):
        if isinstance(item, dict):
            kind = str(item.get("type") or item.get("label") or "").strip()
            percentage = int(item.get("percentage") or 0)
            if kind and percentage:
                content_mix.append({"type": kind, "percentage": percentage})
    if not content_mix:
        content_mix = [
            {"type": "attraction", "percentage": 70},
            {"type": "trust", "percentage": 20},
            {"type": "sales", "percentage": 10},
        ]

    items = []
    for index, raw in enumerate(_list(source.get("items")), start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or f"Content item {index}").strip()
        item = {
            "id": str(raw.get("id") or f"monthly-content-{index}").strip(),
            "title": title,
            "objective": str(raw.get("objective") or "").strip(),
            "platforms": _string_list(raw.get("platforms"), 5),
            "placement": str(raw.get("placement") or "").strip(),
            "recommended_output": _dict(raw.get("recommended_output")),
            "prompt": str(raw.get("prompt") or title).strip(),
            "needs_user_asset": bool(raw.get("needs_user_asset")),
            "notes": str(raw.get("notes") or "").strip(),
        }
        item["generation_request"] = _generation_request_for_item(item)
        items.append(item)

    return {
        "client_focus_questions": _string_list(source.get("client_focus_questions"), 6)
        or ["Do you have products, services, offers, launches, or campaigns to focus on this month?"],
        "calendar_context": _dict(source.get("calendar_context")),
        "content_mix": content_mix,
        "daily_story_direction": _string_list(source.get("daily_story_direction"), 10),
        "items": items[:40],
    }


def _normalize_paid_funnel(source: Any) -> dict[str, Any]:
    source = _dict(source)
    raw_stages = _list(source.get("stages"))
    by_stage = {}
    for stage in raw_stages:
        if isinstance(stage, dict):
            name = str(stage.get("stage") or stage.get("name") or "").strip()
            if name:
                by_stage[name.lower()] = stage

    stages = []
    for fallback in FUNNEL_STAGES:
        raw = _dict(by_stage.get(fallback.lower()))
        ideas = []
        raw_ideas = _first_present(
            raw,
            "content_ideas",
            "ideas",
            "content",
            "recommended_content",
            "ad_ideas",
            "campaign_ideas",
            "creative_ideas",
        )
        for index, raw_idea in enumerate(_list(raw_ideas), start=1):
            if not isinstance(raw_idea, dict):
                if isinstance(raw_idea, str) and raw_idea.strip():
                    raw_idea = {"title": raw_idea, "prompt": raw_idea}
                else:
                    continue
            title = str(
                raw_idea.get("title")
                or raw_idea.get("name")
                or raw_idea.get("headline")
                or f"{fallback} idea {index}"
            ).strip()
            prompt = str(
                raw_idea.get("prompt")
                or raw_idea.get("body")
                or raw_idea.get("description")
                or raw_idea.get("summary")
                or title
            ).strip()
            idea = {
                "id": str(raw_idea.get("id") or f"{fallback.lower()}-{index}").strip(),
                "title": title,
                "recommended_outputs": _text_list(
                    raw_idea.get("recommended_outputs")
                    or raw_idea.get("outputs")
                    or raw_idea.get("formats")
                    or raw_idea.get("format"),
                    5,
                ),
                "prompt": prompt,
                "notes": str(raw_idea.get("notes") or raw_idea.get("rationale") or "").strip(),
            }
            idea["generation_request"] = _generation_request_for_item(
                {"title": title, "prompt": idea["prompt"], "recommended_outputs": idea["recommended_outputs"]}
            )
            ideas.append(idea)
        stages.append(
            {
                "stage": str(raw.get("stage") or fallback).strip(),
                "goal": str(raw.get("goal") or raw.get("objective") or "").strip(),
                "audience": str(raw.get("audience") or raw.get("target_audience") or "").strip(),
                "budget_direction": str(raw.get("budget_direction") or raw.get("budget") or "").strip(),
                "content_ideas": ideas[:8],
            }
        )
    return {"stages": stages}


def _normalize_section(section_id: str, fallback_title: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    raw_cards = _first_present(
        source,
        "cards",
        "items",
        "recommendations",
        "actions",
        "examples",
        "opportunities",
        "ideas",
    )
    cards = [_normalize_card(card) for card in _list(raw_cards)]
    metrics = [_normalize_metric(metric) for metric in _list(_first_present(source, "metrics", "kpis", "measurements"))]
    summary = str(
        _first_present(source, "summary", "overview", "description", "body", "insight", "analysis") or ""
    ).strip()
    bullets = _text_list(
        _first_present(source, "bullets", "points", "takeaways", "recommendations", "actions", "findings"),
        10,
    )
    return {
        "id": section_id,
        "title": str(source.get("title") or source.get("name") or fallback_title).strip(),
        "summary": summary,
        "bullets": bullets,
        "cards": [card for card in cards if card][:6],
        "metrics": [metric for metric in metrics if metric][:6],
    }


def infer_plan_language(suite: Suite, requested_language: str | None = None) -> str:
    if requested_language:
        return requested_language
    brand = _dict(suite.brand)
    strategy = _dict(suite.strategy)
    for value in (
        strategy.get("language"),
        brand.get("app_language"),
        (_list(brand.get("audience_languages")) or [None])[0],
    ):
        if isinstance(value, str) and value:
            return value
    return "en"


def suite_research_payload(suite: Suite, planning_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    brand = _dict(suite.brand)
    strategy = _dict(suite.strategy)
    strategy_without_deck = {k: v for k, v in strategy.items() if k != "marketing_plan_deck"}
    return {
        "suite": {"id": suite.id, "name": suite.name, "status": suite.status},
        "brand": brand,
        "strategy": strategy_without_deck,
        "connections": _dict(suite.connections),
        "reference_links": brand.get("reference_links") or [],
        "website": brand.get("website"),
        "social_links": brand.get("social_links") or {},
        "planning_inputs": planning_inputs or {},
    }


def _json_for_prompt(payload: dict[str, Any]) -> str:
    """Compact suite research so long-running plan jobs stay inside provider timeouts."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= PROMPT_PAYLOAD_CHAR_LIMIT:
        return text
    return text[:PROMPT_PAYLOAD_CHAR_LIMIT] + "...[truncated]"


def build_marketing_plan_prompt(suite_payload: dict[str, Any], language: str) -> str:
    lang_name = LANG_NAMES.get(language, language or "English")
    section_ids = [section_id for section_id, _ in REQUIRED_SECTIONS]
    return f"""You are a senior marketing strategist and presentation strategist for OneShare.
Build a client-facing strategic marketing plan as an interactive web deck, not a generic report.

Output language: {lang_name}.
Use the client/business language naturally. If Arabic or Hebrew, write right-to-left friendly text.
Use the provided business data as facts. If a fact is missing, state a careful assumption rather than inventing numbers.

Business research payload:
{_json_for_prompt(suite_payload)}

Return ONLY valid JSON with this exact top-level shape:
{{
  "cover": {{
    "title": "business or plan title",
    "subtitle": "one strong positioning sentence",
    "chips": ["3-6 short chips"],
    "image_prompt": "optional visual direction for a future cover image"
  }},
  "research_summary": {{
    "sources_used": ["website", "instagram", "meta", "google", "manual profile", "competitor research"],
    "confidence": "high|medium|low",
    "limitations": ["what is missing or should be validated"]
  }},
  "monthly_work_plan": {{
    "client_focus_questions": ["questions to ask the client before finalizing this month"],
    "calendar_context": {{
      "countries": ["target countries"],
      "religions_considered": ["religions/cultures that may affect timing"],
      "seasonal_notes": ["holidays, events, weather, school, shopping, or local moments to watch"]
    }},
    "content_mix": [
      {{"type": "attraction", "percentage": 70}},
      {{"type": "trust", "percentage": 20}},
      {{"type": "sales", "percentage": 10}}
    ],
    "daily_story_direction": ["daily story/reel/post reminders"],
    "items": [
      {{
        "id": "stable short id",
        "title": "content title",
        "objective": "attraction|trust|sales",
        "platforms": ["instagram", "facebook"],
        "placement": "post|reel|story|carousel|ad",
        "recommended_output": {{"format": "image|video|carousel|mixed", "production_mode": "ai|talking_head|ugc|store_video|product_photo|manual_upload"}},
        "prompt": "ready-to-generate prompt for OneShare",
        "needs_user_asset": true,
        "notes": "what the user should upload or approve"
      }}
    ]
  }},
  "paid_funnel": {{
    "stages": [
      {{
        "stage": "Awareness|Consideration|Conversion|Loyalty|Ambassador",
        "goal": "stage goal",
        "audience": "who this stage talks to",
        "budget_direction": "practical budget guidance",
        "content_ideas": [
          {{"id": "stable id", "title": "idea title", "recommended_outputs": ["video", "image"], "prompt": "ready-to-generate paid creative prompt", "notes": "optional"}}
        ]
      }}
    ]
  }},
  "sections": [
    {{
      "id": "one of: {', '.join(section_ids)}",
      "title": "section title",
      "summary": "2-4 sentence executive summary",
      "bullets": ["practical bullet", "practical bullet"],
      "cards": [{{"title": "card title", "body": "short useful explanation", "points": ["optional"]}}],
      "metrics": [{{"label": "metric", "value": "target or current value"}}]
    }}
  ]
}}

Required content:
- Cover that feels like a premium client presentation.
- Current situation and asset audit based on website/social/brand data.
- Market demand/opportunity and offer-demand framing.
- Competitor landscape and how the business can win.
- Target audience, pain points, motivations, language/culture notes.
- Positioning, USP/ESP, and marketing message.
- Channel strategy for social, search, paid ads, website, and remarketing when relevant.
- Content strategy with themes, formats, and posting direction.
- Campaign ideas with practical examples.
- A monthly social content work plan:
  - Start by asking what products, services, campaigns, launches, or offers the client wants to focus on soon.
  - Check target audience, country, religions/cultures, holidays, local seasons, and relevant events before suggesting timing.
  - Build the social plan around 70% attraction / attention, 20% trust building, 10% sales. Do not exceed 10% direct sales.
  - Include daily direction for posts, reels, and stories.
  - Every content item must recommend the output shape: image, video, carousel, mixed, story, reel, UGC/talking-head, store footage, product photo, manual upload, or AI generation.
  - Some ideas may require more than one output, such as video + image or video + carousel.
- A complete paid marketing funnel with these stages: Awareness, Consideration, Conversion, Loyalty, Ambassador.
  - For each stage, suggest content ideas and recommended outputs.
  - Keep each idea ready to generate, upload, schedule, or convert into ads later.
- 30/60/90 action plan.
- KPIs, measurement, and budget direction.
- Clear next steps.

Rules:
- Include all required section ids at least once.
- Keep each section concise enough for a web deck.
- No markdown, no comments, no surrounding text. JSON only."""


def build_marketing_plan_repair_prompt(raw: str, language: str) -> str:
    lang_name = LANG_NAMES.get(language, language or "English")
    return f"""Repair the following marketing-plan response into valid JSON only.

Output language: {lang_name}.
Do not explain. Do not wrap in markdown.
If the response is truncated or malformed, complete the missing required fields with concise, useful content in the requested language.
Keep it compact but not empty.

Required top-level keys:
cover, research_summary, monthly_work_plan, paid_funnel, sections.

Every section must include: id, title, summary, bullets, cards, metrics.
monthly_work_plan must include at least 8 items.
paid_funnel must include Awareness, Consideration, Conversion, Loyalty, Ambassador, each with at least 2 content_ideas.

Malformed source:
{raw[:24000]}
"""


def build_compact_marketing_plan_prompt(payload: dict[str, Any], language: str) -> str:
    lang_name = LANG_NAMES.get(language, language or "English")
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    if len(payload_json) > PROMPT_PAYLOAD_CHAR_LIMIT:
        payload_json = payload_json[:PROMPT_PAYLOAD_CHAR_LIMIT] + "...[truncated]"

    section_lines = "\n".join(f"- {section_id}: {title}" for section_id, title in REQUIRED_SECTIONS)
    return f"""Create a compact but useful marketing plan deck as STRICT JSON only.

Language: {lang_name}.
No markdown. No comments. No surrounding text.
Keep the JSON compact enough to fit in one response, but every required field must contain useful client-facing content.

Required section ids:
{section_lines}

JSON shape:
{{
  "cover": {{"title": "...", "subtitle": "...", "chips": ["..."]}},
  "research_summary": {{"sources_used": ["..."], "limitations": ["..."]}},
  "monthly_work_plan": {{
    "client_focus_questions": ["..."],
    "calendar_context": {{"countries": ["..."], "religions_considered": ["..."], "seasonal_notes": ["..."]}},
    "daily_story_direction": ["..."],
    "content_mix": [
      {{"type": "attraction", "percentage": 70}},
      {{"type": "trust", "percentage": 20}},
      {{"type": "sales", "percentage": 10}}
    ],
    "items": [
      {{"title": "...", "objective": "attraction|trust|sales", "platforms": ["instagram","facebook"], "placement": "post|reel|story|ad", "recommended_output": {{"format": "image|video|carousel|mixed", "production_mode": "AI|manual|UGC"}}, "prompt": "...", "needs_user_asset": false, "notes": "..."}}
    ]
  }},
  "paid_funnel": {{
    "stages": [
      {{"stage": "Awareness", "goal": "...", "content_ideas": [{{"title": "...", "recommended_outputs": ["video"], "prompt": "..."}}]}}
    ]
  }},
  "sections": [
    {{"id": "executive_summary", "title": "...", "summary": "...", "bullets": ["..."], "cards": [{{"title": "...", "body": "...", "points": ["..."]}}], "metrics": [{{"label": "...", "value": "..."}}]}}
  ]
}}

Rules:
- monthly_work_plan.items: exactly 8 practical content items.
- paid_funnel.stages: include exactly Awareness, Consideration, Conversion, Loyalty, Ambassador; each stage has 2 content_ideas.
- sections: include every required section id exactly once.
- Each section: 1 short summary, 3 bullets, 1 card, 1 metric.
- Do not leave arrays empty.

Business/profile data:
{payload_json}
"""


def build_rule_based_marketing_plan_json(payload: dict[str, Any], language: str) -> dict[str, Any]:
    """Last-resort complete deck so provider JSON failures never publish an empty shell."""
    suite = _dict(payload.get("suite"))
    brand = _dict(payload.get("brand"))
    strategy = _dict(payload.get("strategy"))
    planning_inputs = _dict(payload.get("planning_inputs"))
    is_ar = str(language or "").startswith("ar")
    name = str(brand.get("name") or suite.get("name") or "OneShare client").strip()
    industry = str(brand.get("industry") or brand.get("category") or "business").strip()
    services = _text_list(
        brand.get("services") or brand.get("products") or strategy.get("services") or strategy.get("products"),
        8,
    )
    audience = str(
        strategy.get("target_audience")
        or brand.get("target_audience")
        or brand.get("audience")
        or ("الجمهور المحلي المناسب" if is_ar else "the most relevant local audience")
    ).strip()
    focus = str(planning_inputs.get("near_term_focus") or planning_inputs.get("planning_notes") or "").strip()
    service_text = "، ".join(services[:4]) if services else ("الخدمات الأساسية" if is_ar else "core services")

    if is_ar:
        cover_title = f"الخطة التسويقية – {name}"
        subtitle = f"خطة نمو عملية لـ {name} في مجال {industry} مبنية على البروفايل، القنوات الرقمية، وافتراضات تحتاج تأكيداً من العميل."
        sources = ["بروفايل السوت", "بيانات البراند", "الروابط والحسابات المتصلة", "مدخلات التخطيط من العميل"]
        limitations = [
            "تحتاج الخطة لتأكيد الميزانية الشهرية قبل إطلاق الحملات.",
            "يجب تأكيد العروض أو الخدمات التي يريد العميل التركيز عليها هذا الشهر.",
            "الأرقام النهائية تعتمد على بيانات الحسابات الإعلانية بعد الربط الكامل.",
        ]
        section_copy = {
            "executive_summary": ("الملخص التنفيذي", f"الفرصة الأساسية هي تحويل حضور {name} الرقمي إلى مسار واضح: جذب جمهور مناسب، بناء ثقة، ثم دفع عروض محددة بدون الإكثار من البيع المباشر."),
            "current_situation": ("الوضع الحالي", f"{name} يعمل في مجال {industry} ويحتاج إلى ربط الرسالة التسويقية بالخدمات الأكثر طلباً: {service_text}."),
            "asset_audit": ("تدقيق الأصول الرقمية", "الأولوية هي تثبيت الهوية البصرية، توحيد الرسائل، والتأكد من أن الموقع والحسابات الاجتماعية تقود المستخدم إلى خطوة واضحة."),
            "market_demand": ("الطلب والفرصة في السوق", f"الجمهور يبحث عن حلول واضحة وسريعة الفهم في {industry}. المحتوى يجب أن يشرح المشكلة، النتيجة، ولماذا {name} خيار مناسب."),
            "competitors": ("المنافسون والتموضع", "المنافسة غالباً تعرض خدمات متشابهة؛ الفوز يكون بوضوح العرض، دليل الثقة، وسهولة التواصل."),
            "audience": ("الجمهور المستهدف", f"الجمهور الأساسي: {audience}. يجب مخاطبته بلغته اليومية، مع أمثلة قريبة من واقعه واحتياجاته."),
            "positioning": ("التموضع والرسالة", f"الرسالة المقترحة: {name} يساعد العميل على فهم الخيار الصحيح واتخاذ قرار أسرع بثقة أكبر."),
            "channel_strategy": ("استراتيجية القنوات", "استخدم إنستغرام وفيسبوك للثقة والجذب، جوجل للطلب المباشر، والموقع لتحويل الزائر إلى تواصل أو حجز."),
            "content_strategy": ("استراتيجية المحتوى", "اعتمد مزيج 70% جذب وتعليم، 20% ثقة وإثبات، 10% بيع مباشر فقط حتى لا يشعر الجمهور بالإزعاج."),
            "campaign_ideas": ("أفكار حملات", "ابدأ بحملة وعي حول المشكلة، ثم حملة إثبات نتائج، ثم عرض واضح محدود بزمن أو خدمة محددة."),
            "action_plan": ("خطة التنفيذ", "خلال 30 يوماً: تثبيت الرسالة والمحتوى. خلال 60 يوماً: اختبار الإعلانات. خلال 90 يوماً: توسيع الأفضل أداءً."),
            "kpis": ("مؤشرات القياس", "راقب الوصول، التفاعل، الرسائل، تكلفة المحادثة أو الليد، ونسبة تحويل الزائر إلى طلب."),
            "budget": ("اتجاه الميزانية", "ابدأ بميزانية اختبار صغيرة موزعة بين وعي وتحويل، ثم انقل الميزانية تدريجياً إلى الحملات الأفضل أداءً."),
            "next_steps": ("الخطوات القادمة", "أكد الأولويات الشهرية، جهز الأصول الناقصة، ثم حوّل عناصر الخطة إلى محتوى وجدولة وحملات."),
        }
        monthly_titles = [
            "بوست تعليمي يشرح المشكلة الأساسية",
            "ريل قصير يوضح نتيجة ملموسة",
            "كاروسيل أسئلة وأجوبة",
            "ستوري يومي مع سؤال للجمهور",
            "بوست إثبات ثقة أو تجربة عميل",
            "فيديو قصير عن خدمة محددة",
            "كاروسيل مقارنة قبل وبعد",
            "بوست عرض خفيف بنسبة بيع محدودة",
        ]
        funnel_goals = {
            "Awareness": "تعريف الجمهور بالمشكلة وباسم البراند",
            "Consideration": "إقناع الجمهور أن الحل مناسب له",
            "Conversion": "تحويل المهتم إلى رسالة أو طلب",
            "Loyalty": "إعادة تفعيل العملاء والمتابعين",
            "Ambassador": "تحويل العملاء الراضين إلى مصدر توصيات",
        }
    else:
        cover_title = f"Marketing plan – {name}"
        subtitle = f"A practical growth plan for {name} in {industry}, based on the suite profile and connected channels."
        sources = ["suite profile", "brand data", "connected links/accounts", "planning inputs"]
        limitations = [
            "Monthly budget must be confirmed before campaign launch.",
            "The client should confirm near-term offers and service priorities.",
            "Final metrics depend on connected ad-account data.",
        ]
        section_copy = {
            section_id: (title, f"{title} for {name}: focus on clear offers, trust signals, and measurable next actions.")
            for section_id, title in REQUIRED_SECTIONS
        }
        monthly_titles = [
            "Educational problem explainer",
            "Short proof reel",
            "FAQ carousel",
            "Daily audience question story",
            "Trust proof post",
            "Service-specific short video",
            "Before/after carousel",
            "Soft sales offer post",
        ]
        funnel_goals = {stage: f"Move the audience through {stage.lower()} with clear, measurable content." for stage in FUNNEL_STAGES}

    sections = []
    for section_id, fallback_title in REQUIRED_SECTIONS:
        title, summary = section_copy.get(section_id, (fallback_title, fallback_title))
        sections.append(
            {
                "id": section_id,
                "title": title,
                "summary": summary,
                "bullets": [
                    f"{title}: اربط الرسالة بما يحتاجه الجمهور فعلياً." if is_ar else f"{title}: tie the message to the audience need.",
                    "استخدم دليل ثقة واضح قبل طلب الشراء." if is_ar else "Use a clear trust signal before asking for conversion.",
                    "حوّل كل فكرة إلى مخرج قابل للتوليد أو النشر." if is_ar else "Turn each idea into a generatable or publishable asset.",
                ],
                "cards": [
                    {
                        "title": "توصية عملية" if is_ar else "Practical recommendation",
                        "body": summary,
                        "points": [
                            "ابدأ بقياس أسبوعي" if is_ar else "Start with weekly measurement",
                            "عدّل حسب النتائج" if is_ar else "Adjust based on results",
                        ],
                    }
                ],
                "metrics": [
                    {
                        "label": "مؤشر متابعة" if is_ar else "Tracking metric",
                        "value": "أسبوعي" if is_ar else "weekly",
                    }
                ],
            }
        )

    monthly_items = []
    for index, title in enumerate(monthly_titles, start=1):
        objective = "attraction" if index <= 5 else ("trust" if index <= 7 else "sales")
        fmt = "video" if index in {2, 6} else ("carousel" if index in {3, 7} else "image")
        prompt = (
            f"ولّد {title} لـ {name}. ركّز على {service_text}. استخدم لغة الجمهور، واحفظ البيع المباشر لعناصر قليلة."
            if is_ar
            else f"Generate {title} for {name}. Focus on {service_text} with clear audience language."
        )
        monthly_items.append(
            {
                "id": f"monthly-content-{index}",
                "title": title,
                "objective": objective,
                "platforms": ["instagram", "facebook"],
                "placement": "reel" if fmt == "video" else ("carousel" if fmt == "carousel" else "post"),
                "recommended_output": {"format": fmt, "production_mode": "ai"},
                "prompt": prompt,
                "needs_user_asset": fmt == "video",
                "notes": "يمكن استخدام أصل من العميل إذا توفر." if is_ar else "Use a client asset if available.",
            }
        )

    funnel_stages = []
    for stage in FUNNEL_STAGES:
        funnel_stages.append(
            {
                "stage": stage,
                "goal": funnel_goals[stage],
                "audience": audience,
                "budget_direction": "اختبار صغير ثم توسيع الأفضل أداءً." if is_ar else "Start small, then scale winners.",
                "content_ideas": [
                    {
                        "id": f"{stage.lower()}-1",
                        "title": f"{stage}: فكرة فيديو" if is_ar else f"{stage}: video idea",
                        "recommended_outputs": ["video"],
                        "prompt": f"ولّد فيديو قصير لمرحلة {stage} لـ {name}." if is_ar else f"Generate a short {stage} video for {name}.",
                    },
                    {
                        "id": f"{stage.lower()}-2",
                        "title": f"{stage}: فكرة صورة/كاروسيل" if is_ar else f"{stage}: image/carousel idea",
                        "recommended_outputs": ["image", "carousel"],
                        "prompt": f"ولّد إعلان صورة أو كاروسيل لمرحلة {stage} لـ {name}." if is_ar else f"Generate an image or carousel ad for {stage}.",
                    },
                ],
            }
        )

    return {
        "cover": {
            "title": cover_title,
            "subtitle": subtitle,
            "chips": [industry, "OneShare", "Social", "Paid Ads", "Content"],
            "image_prompt": f"Premium digital marketing plan cover for {name}",
        },
        "research_summary": {
            "sources_used": sources,
            "confidence": "medium",
            "limitations": limitations,
        },
        "monthly_work_plan": {
            "client_focus_questions": [
                "ما المنتجات أو الخدمات أو العروض التي تريد التركيز عليها هذا الشهر؟"
                if is_ar
                else "Which products, services, offers, or campaigns should we focus on this month?"
            ],
            "calendar_context": {
                "countries": _text_list(brand.get("audience_locations") or brand.get("countries"), 4),
                "religions_considered": ["Islam", "Judaism", "Christianity"],
                "seasonal_notes": [
                    "افحص المناسبات المحلية والأعياد قبل الجدولة." if is_ar else "Check local holidays and events before scheduling."
                ],
            },
            "content_mix": [
                {"type": "attraction", "percentage": 70},
                {"type": "trust", "percentage": 20},
                {"type": "sales", "percentage": 10},
            ],
            "daily_story_direction": [
                "اسأل سؤالاً قصيراً للجمهور." if is_ar else "Ask a short audience question.",
                "اعرض دليل ثقة أو نتيجة." if is_ar else "Show proof or a result.",
                "ذكّر بخطوة التواصل بدون ضغط." if is_ar else "Remind users of the next step without pressure.",
            ],
            "items": monthly_items,
        },
        "paid_funnel": {"stages": funnel_stages},
        "sections": sections,
    }


async def parse_or_repair_marketing_plan_json(raw: str, language: str) -> dict[str, Any]:
    parsed = parse_marketing_plan_json(raw)
    if parsed:
        return parsed

    log.warning("Marketing plan AI returned invalid JSON; attempting repair. Raw preview: %.500s", raw)
    repaired = await call_text_ai(
        provider="anthropic",
        model=settings.anthropic_text_model,
        max_tokens=MARKETING_PLAN_REPAIR_MAX_TOKENS,
        messages=[{"role": "user", "content": build_marketing_plan_repair_prompt(raw, language)}],
        system="You repair malformed AI JSON into strict valid JSON only.",
        timeout=MARKETING_PLAN_REPAIR_TIMEOUT_SECONDS,
    )
    return parse_marketing_plan_json(repaired)


async def generate_compact_marketing_plan_json(payload: dict[str, Any], language: str) -> dict[str, Any]:
    log.warning("Marketing plan repair failed; requesting compact fallback JSON.")
    compact_raw = await call_text_ai(
        provider="anthropic",
        model=settings.anthropic_text_model,
        max_tokens=MARKETING_PLAN_REPAIR_MAX_TOKENS,
        messages=[{"role": "user", "content": build_compact_marketing_plan_prompt(payload, language)}],
        system="You create compact, strict, valid JSON marketing strategy decks. Return JSON only.",
        timeout=MARKETING_PLAN_REPAIR_TIMEOUT_SECONDS,
    )
    parsed = parse_marketing_plan_json(compact_raw)
    if parsed:
        return parsed
    log.warning("Compact marketing plan fallback returned invalid JSON; attempting one repair.")
    repaired = await parse_or_repair_marketing_plan_json(compact_raw, language)
    if repaired:
        return repaired
    log.error("All marketing plan AI JSON attempts failed; using rule-based complete fallback deck.")
    return build_rule_based_marketing_plan_json(payload, language)


def normalize_marketing_plan_deck(
    raw: dict[str, Any],
    suite_name: str,
    language: str,
    planning_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cover = _dict(raw.get("cover"))
    raw_sections = _list(raw.get("sections"))
    by_id: dict[str, dict[str, Any]] = {}
    for section in raw_sections:
        if isinstance(section, dict):
            section_id = str(section.get("id") or "").strip()
            if section_id:
                by_id[section_id] = section

    sections = []
    for section_id, fallback_title in REQUIRED_SECTIONS:
        sections.append(_normalize_section(section_id, fallback_title, by_id.get(section_id)))

    extras = []
    for section in raw_sections:
        if isinstance(section, dict):
            section_id = str(section.get("id") or "").strip()
            if section_id and section_id not in {sid for sid, _ in REQUIRED_SECTIONS}:
                extras.append(_normalize_section(section_id, str(section.get("title") or section_id), section))

    return {
        "version": PLAN_VERSION,
        "status": "ready",
        "language": language,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "planning_inputs": planning_inputs or {},
        "cover": {
            "title": str(cover.get("title") or suite_name or "Marketing plan").strip(),
            "subtitle": str(cover.get("subtitle") or "A practical growth plan built from the business profile.").strip(),
            "chips": _string_list(cover.get("chips"), 6),
            "image_prompt": str(cover.get("image_prompt") or "").strip(),
            "image_url": str(cover.get("image_url") or "").strip(),
        },
        "research_summary": _dict(raw.get("research_summary")),
        "monthly_work_plan": _normalize_monthly_work_plan(raw.get("monthly_work_plan")),
        "paid_funnel": _normalize_paid_funnel(raw.get("paid_funnel")),
        "sections": sections + extras[:4],
    }


def marketing_plan_content_score(deck: dict[str, Any]) -> int:
    """Approximate whether the generated deck has real substance, not just titles."""
    score = 0
    cover = _dict(deck.get("cover"))
    if cover.get("subtitle") and cover.get("subtitle") != "A practical growth plan built from the business profile.":
        score += 1
    research = _dict(deck.get("research_summary"))
    score += len(_string_list(research.get("sources_used"), 8))
    score += len(_string_list(research.get("limitations"), 8))

    monthly = _dict(deck.get("monthly_work_plan"))
    score += len(_list(monthly.get("items"))) * 2
    score += len(_string_list(monthly.get("daily_story_direction"), 10))
    calendar = _dict(monthly.get("calendar_context"))
    score += len(_string_list(calendar.get("seasonal_notes"), 8))

    funnel = _dict(deck.get("paid_funnel"))
    for stage in _list(funnel.get("stages")):
        if isinstance(stage, dict):
            if str(stage.get("goal") or "").strip():
                score += 1
            score += len(_list(stage.get("content_ideas"))) * 2

    for section in _list(deck.get("sections")):
        if not isinstance(section, dict):
            continue
        if str(section.get("summary") or "").strip():
            score += 2
        score += len(_string_list(section.get("bullets"), 10))
        score += len(_list(section.get("cards"))) * 2
        score += len(_list(section.get("metrics")))
    return score


def validate_marketing_plan_deck(deck: dict[str, Any]) -> None:
    sections = [section for section in _list(deck.get("sections")) if isinstance(section, dict)]
    by_section_id = {str(section.get("id") or "").strip(): section for section in sections}
    missing_sections = []
    empty_sections = []
    for section_id, _title in REQUIRED_SECTIONS:
        section = by_section_id.get(section_id)
        if not section:
            missing_sections.append(section_id)
            continue
        has_content = any(
            (
                str(section.get("summary") or "").strip(),
                _string_list(section.get("bullets"), 12),
                _list(section.get("cards")),
                _list(section.get("metrics")),
            )
        )
        if not has_content:
            empty_sections.append(section_id)
    if missing_sections or empty_sections:
        details = []
        if missing_sections:
            details.append(f"missing sections: {', '.join(missing_sections)}")
        if empty_sections:
            details.append(f"empty sections: {', '.join(empty_sections)}")
        raise MarketingPlanGenerationError("Marketing plan AI response was incomplete; " + "; ".join(details) + ".")

    monthly_items = _list(_dict(deck.get("monthly_work_plan")).get("items"))
    if len(monthly_items) < 8:
        raise MarketingPlanGenerationError(
            f"Marketing plan AI response was incomplete; monthly work plan has {len(monthly_items)} items."
        )

    funnel_stages = _list(_dict(deck.get("paid_funnel")).get("stages"))
    ideas_by_stage = {
        str(stage.get("stage") or "").strip(): len(_list(stage.get("content_ideas")))
        for stage in funnel_stages
        if isinstance(stage, dict)
    }
    sparse_stages = [
        stage
        for stage in FUNNEL_STAGES
        if ideas_by_stage.get(stage, 0) < 2
    ]
    if sparse_stages:
        raise MarketingPlanGenerationError(
            "Marketing plan AI response was incomplete; paid funnel needs at least 2 ideas for: "
            + ", ".join(sparse_stages)
            + "."
        )

    score = marketing_plan_content_score(deck)
    if score < 18:
        raise MarketingPlanGenerationError(
            f"Marketing plan AI response was empty or incomplete; content score {score}."
        )


async def generate_marketing_plan_deck(
    suite: Suite,
    language: str | None = None,
    planning_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_language = infer_plan_language(suite, language)
    payload = suite_research_payload(suite, planning_inputs)
    prompt = build_marketing_plan_prompt(payload, output_language)
    raw = await call_text_ai(
        provider="anthropic",
        model=settings.anthropic_text_model,
        max_tokens=MARKETING_PLAN_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        system="You create rigorous, client-ready marketing strategy decks. Return JSON only.",
        timeout=MARKETING_PLAN_TIMEOUT_SECONDS,
    )
    parsed = await parse_or_repair_marketing_plan_json(raw, output_language)
    if not parsed:
        parsed = await generate_compact_marketing_plan_json(payload, output_language)
    if not parsed:
        raise MarketingPlanGenerationError("Marketing plan AI response was not valid JSON.")
    deck = normalize_marketing_plan_deck(parsed, suite.name, output_language, planning_inputs=planning_inputs)
    validate_marketing_plan_deck(deck)
    return deck
