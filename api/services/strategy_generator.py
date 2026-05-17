"""Marketing strategy generator — builds marketing plan and message from brand data."""
import asyncio
import json
import logging
import re
from typing import Optional

import anthropic

from ..core.config import settings
from .multi_scraper import search_business

log = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if present
    if "```" in raw:
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        raw = raw.strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fallback: extract first JSON object from mixed text
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            log.warning("_parse_json: could not parse JSON from model output: %.200s", raw)
    else:
        log.warning("_parse_json: no JSON found in model output: %.200s", raw)
    return {}


def _is_arabic(brand: dict) -> bool:
    dialect = (brand.get("dialect") or "").lower()
    return "arabic" in dialect or dialect == "msa"


# ── Competitor research ───────────────────────────────────────────────────────

async def research_competitors(
    competitors: list[str],
    business_name: str,
) -> dict[str, str]:
    """Web-search each competitor (max 4) and return snippets keyed by name."""
    if not competitors:
        return {}
    capped = competitors[:4]

    async def _safe_search(name: str) -> tuple[str, str]:
        try:
            snippets = await search_business(name)
            return name, snippets
        except Exception as e:
            log.warning("Competitor search failed for %s: %s", name, e)
            return name, ""

    results = await asyncio.gather(*[_safe_search(n) for n in capped])
    return dict(results)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_strategy_prompt(brand: dict, competitor_snippets: dict[str, str], is_ar: bool) -> str:
    name = brand.get("name", "")
    industry = brand.get("industry", "")
    services = ", ".join(brand.get("services") or [])
    products = ", ".join(brand.get("products") or [])
    offerings = ", ".join(filter(None, [services, products])) or "Not specified"
    target = brand.get("target_audience", "")
    how_help = brand.get("how_they_help", "")
    usp = brand.get("unique_value", "")
    esp = brand.get("esp", "")
    location = brand.get("location", "")
    dialect = brand.get("dialect", "")

    comp_context = ""
    for comp_name, snippets in competitor_snippets.items():
        comp_context += f"\n## {comp_name}\n{snippets[:500]}\n"
    if not comp_context:
        comp_context = "No competitor data available from web search."

    if is_ar:
        return f"""أنت خبير تسويق إلكتروني. أنا عميلك.

النص التعريفي:
- الاسم: {name}
- الصناعة: {industry}
- الخدمات/المنتجات: {offerings}
- الجمهور المستهدف: {target}
- كيف أساعدهم: {how_help}
- USP (ما يميزني): {usp}
- ESP (ما يشعر به عملائي): {esp}
- الموقع الجغرافي: {location}
- اللهجة المستخدمة في المحتوى: {dialect}

معلومات المنافسين (نتائج البحث على الويب):
{comp_context}

---

المطلوب: أعد JSON صالح فقط بهذا الشكل الكامل (لا شرح، لا markdown):

{{
  "marketing_plan": {{
    "services": ["الخدمات والمنتجات"],
    "keywords": ["كلمة مفتاحية 1", "كلمة مفتاحية 2"],
    "competitors": [
      {{
        "name": "اسم المنافس",
        "website": "url أو null",
        "social_links": {{"instagram": "url أو null", "facebook": "url أو null", "tiktok": "url أو null"}},
        "google_profile": "url أو null",
        "usp": "ما يميزه",
        "esp": "ما يشعر به عميله"
      }}
    ],
    "audience": {{
      "problem": "المشكلة/الحاجة التي أحلها",
      "demographics": {{"age": "المدى العمري", "gender": "الجنس", "language": "اللغة", "social_status": "الحالة الاجتماعية"}},
      "geography": {{"countries": ["الدولة"], "regions": ["المنطقة"], "cities": ["المدينة"]}},
      "interests": ["اهتمام 1", "اهتمام 2"],
      "facebook_interests": ["Interest 1 in English", "Interest 2 in English"],
      "digital_behavior": "وصف السلوك الرقمي للجمهور",
      "personas": [
        {{"name": "الاسم", "age": 30, "profession": "المهنة", "needs": "الاحتياجات", "challenges": "التحديات"}}
      ]
    }},
    "content_themes": ["محور المحتوى 1", "محور المحتوى 2"]
  }},
  "marketing_message": "بالنسبة لـ [الجمهور] الذين [المشكلة]، فإن {name} هي [نوع الخدمات] التي توفّر [USP] حتى يشعروا بـ [ESP]"
}}

قواعد مهمة:
- 10 شخصيات بالضبط في personas
- facebook_interests بالإنجليزي كما تظهر في Meta Ads Manager
- الرسالة التسويقية: استبدل كل القيم داخل [] بالمحتوى الفعلي
- أعد JSON صالح فقط، بلا شرح أو markdown"""

    else:
        return f"""You are a digital marketing expert. I am your client.

Business brief:
- Name: {name}
- Industry: {industry}
- Services/Products: {offerings}
- Target audience: {target}
- How I help them: {how_help}
- USP (what makes me unique): {usp}
- ESP (how my clients feel): {esp}
- Location: {location}

Competitor research (from web search):
{comp_context}

---

Required: Return ONLY valid JSON with this exact structure (no explanation, no markdown):

{{
  "marketing_plan": {{
    "services": ["service1", "service2"],
    "keywords": ["keyword1", "keyword2"],
    "competitors": [
      {{
        "name": "competitor name",
        "website": "url or null",
        "social_links": {{"instagram": "url or null", "facebook": "url or null", "tiktok": "url or null"}},
        "google_profile": "url or null",
        "usp": "what makes them unique",
        "esp": "how their customer feels"
      }}
    ],
    "audience": {{
      "problem": "the problem/need I solve",
      "demographics": {{"age": "age range", "gender": "gender", "language": "language", "social_status": "social status"}},
      "geography": {{"countries": ["country"], "regions": ["region"], "cities": ["city"]}},
      "interests": ["interest1", "interest2"],
      "facebook_interests": ["Interest 1 in English", "Interest 2 in English"],
      "digital_behavior": "description of audience digital behavior",
      "personas": [
        {{"name": "Name", "age": 30, "profession": "Profession", "needs": "Needs", "challenges": "Challenges"}}
      ]
    }},
    "content_themes": ["content theme 1", "content theme 2"]
  }},
  "marketing_message": "For [audience] who [problem], {name} is [services type] that provides [USP] so they feel [ESP]"
}}

Important rules:
- Write exactly 10 personas
- facebook_interests must be in English exactly as they appear in Meta Ads Manager
- marketing_message: replace all values inside [] with actual content
- Return ONLY valid JSON, no explanation or markdown"""


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_strategy(brand: dict) -> dict:
    """Generate full marketing strategy (plan + message) from brand data."""
    competitor_snippets = await research_competitors(
        brand.get("competitors") or [], brand.get("name", "")
    )
    is_ar = _is_arabic(brand)
    prompt = _build_strategy_prompt(brand, competitor_snippets, is_ar)

    response = await _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    if not response.content:
        raise ValueError("Anthropic returned an empty response content list")
    raw = response.content[0].text
    data = _parse_json(raw)

    return {
        "marketing_plan": data.get("marketing_plan", {}),
        "marketing_message": data.get("marketing_message", ""),
        "language": "ar" if is_ar else "en",
    }
