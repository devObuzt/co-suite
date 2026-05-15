# Marketing Strategy Signup Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the suite signup wizard with a "Complete Profile" step that collects USP/ESP/audience data, then generates and stores a marketing plan + message for every suite.

**Architecture:** Backend-first — add `strategy` JSON column to `suites` table, create `strategy_generator.py` service, add `/onboarding/generate-strategy` endpoint. Frontend adds three new wizard steps (Complete Profile → Generating → Preview) and a Strategy tab in the suite dashboard. Content generator injects the marketing message into every post generation prompt.

**Tech Stack:** FastAPI, SQLAlchemy asyncpg, Anthropic claude-sonnet-4-6, Next.js 15, React, Tailwind, shadcn/ui Tabs

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `api/models/suite.py` | Add `strategy: JSON` column |
| Modify | `api/main.py` | Add `ALTER TABLE IF NOT EXISTS` startup migration |
| Modify | `api/services/brand_ai.py` | Add `how_they_help`, `esp` fields to extraction prompt |
| **Create** | `api/services/strategy_generator.py` | `research_competitors()` + `generate_strategy()` |
| **Create** | `tests/test_strategy_generator.py` | Unit tests for the new service |
| Modify | `api/routers/onboarding.py` | Add `POST /generate-strategy` endpoint |
| Modify | `api/services/content_generator.py` | Inject strategy context into `_build_brand_summary()` |
| Modify | `web/src/lib/api.ts` | Add `MarketingStrategy` type, `how_they_help`, `esp` to `Brand`, `generateStrategy()` method |
| Modify | `web/src/app/(dashboard)/suite/new/page.tsx` | Add `"complete"`, `"strategy"`, `"preview"` steps |
| Modify | `web/src/app/(dashboard)/suite/[id]/page.tsx` | Add Strategy tab |

---

## Task 1: Suite model — add `strategy` column + DB migration

**Files:**
- Modify: `api/models/suite.py`
- Modify: `api/main.py`

- [ ] **Step 1: Add `strategy` column to Suite model**

In `api/models/suite.py`, add this line directly after the `brand` column (line 32):

```python
    # Brand profile (JSON — populated during onboarding)
    brand: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Marketing strategy (JSON — populated after onboarding completes)
    strategy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 2: Add startup migration to create the column in existing DBs**

`create_all` only creates new tables, not new columns. Add a raw ALTER TABLE in `api/main.py`:

Replace the entire `startup()` function:

```python
from sqlalchemy import text

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add strategy column to existing suites tables (idempotent)
        await conn.execute(text(
            "ALTER TABLE suites ADD COLUMN IF NOT EXISTS strategy JSON"
        ))
```

- [ ] **Step 3: Restart the API and verify column exists**

```bash
curl -s http://localhost:8000/health
# Expected: {"status":"ok","app":"co-Suite API"}
```

Then check the column in psql:
```bash
psql postgresql://cosuite:cosuite@localhost:5432/cosuite -c "\d suites" | grep strategy
# Expected: strategy | json | ...
```

- [ ] **Step 4: Commit**

```bash
git add api/models/suite.py api/main.py
git commit -m "feat: add strategy JSON column to suites table"
```

---

## Task 2: Brand extraction — add `how_they_help` and `esp` fields

**Files:**
- Modify: `api/services/brand_ai.py` (lines 119–161, inside `EXTRACTION_PROMPT`)

These two fields must be extracted during brand scraping so the Complete Profile step can pre-fill them.

- [ ] **Step 1: Add the two new fields to `EXTRACTION_PROMPT` JSON schema**

In `api/services/brand_ai.py`, inside `EXTRACTION_PROMPT`, add after `"unique_value"` (after line 150):

```python
  "unique_value": "what makes this business different from competitors",
  "how_they_help": "the specific outcome or problem this business solves for clients (1-2 sentences)",
  "esp": "the emotional benefit the client feels after working with this business (1 sentence, e.g. 'they feel confident and in control')",
```

- [ ] **Step 2: Add extraction rules for the new fields**

In the Rules section of `EXTRACTION_PROMPT` (after the `missing_info` rule, line 171):

```python
- how_they_help: infer from website copy, service descriptions, and social captions — what problem does this solve?
- esp: the emotional feeling the client gets — infer from testimonials, tone, and brand voice.
```

- [ ] **Step 3: Verify extraction still works**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare && \
api/.venv/bin/python -c "
import asyncio
from api.services.brand_ai import extract_brand_from_sources

async def test():
    result = await extract_brand_from_sources([], 'Test Business')
    print('how_they_help:', result.get('how_they_help'))
    print('esp:', result.get('esp'))

asyncio.run(test())
"
```

Expected: both keys present (may be null if no URLs provided, which is fine).

- [ ] **Step 4: Commit**

```bash
git add api/services/brand_ai.py
git commit -m "feat: extract how_they_help and esp fields during brand scraping"
```

---

## Task 3: Create strategy generator service (TDD)

**Files:**
- Create: `api/services/strategy_generator.py`
- Create: `tests/__init__.py`
- Create: `tests/test_strategy_generator.py`

- [ ] **Step 1: Install test dependencies**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/api
.venv/bin/pip install pytest pytest-asyncio
```

- [ ] **Step 2: Create `tests/__init__.py`**

```bash
mkdir -p /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/tests
touch /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/tests/__init__.py
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_strategy_generator.py`:

```python
"""Unit tests for the strategy generator service."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── _is_arabic ────────────────────────────────────────────────────────────────

def test_is_arabic_detects_arabic_dialects():
    from api.services.strategy_generator import _is_arabic
    assert _is_arabic({"dialect": "Palestinian Arabic"}) is True
    assert _is_arabic({"dialect": "Gulf Arabic"}) is True
    assert _is_arabic({"dialect": "MSA"}) is True


def test_is_arabic_returns_false_for_english_and_null():
    from api.services.strategy_generator import _is_arabic
    assert _is_arabic({"dialect": "English"}) is False
    assert _is_arabic({"dialect": None}) is False
    assert _is_arabic({}) is False


# ── research_competitors ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_research_competitors_caps_at_four():
    with patch("api.services.strategy_generator.search_business", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = "some snippets"
        from api.services.strategy_generator import research_competitors
        result = await research_competitors(
            ["A", "B", "C", "D", "E"],  # 5 names
            "My Business",
        )
    assert len(result) == 4
    assert "E" not in result


@pytest.mark.asyncio
async def test_research_competitors_returns_empty_string_on_failure():
    with patch("api.services.strategy_generator.search_business", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = Exception("network error")
        from api.services.strategy_generator import research_competitors
        result = await research_competitors(["BadComp"], "My Business")
    assert result["BadComp"] == ""


@pytest.mark.asyncio
async def test_research_competitors_empty_list_returns_empty_dict():
    from api.services.strategy_generator import research_competitors
    result = await research_competitors([], "My Business")
    assert result == {}


# ── generate_strategy ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_strategy_returns_required_keys():
    mock_payload = {
        "marketing_plan": {
            "services": ["s1"],
            "keywords": ["k1"],
            "competitors": [],
            "audience": {
                "problem": "test problem",
                "demographics": {"age": "25-45", "gender": "all", "language": "English", "social_status": "middle"},
                "geography": {"countries": ["US"], "regions": [], "cities": []},
                "interests": ["tech"],
                "facebook_interests": ["Technology"],
                "digital_behavior": "active on Instagram",
                "personas": [],
            },
            "content_themes": ["t1"],
        },
        "marketing_message": "Test message",
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(mock_payload))]

    with patch("api.services.strategy_generator.research_competitors", new_callable=AsyncMock) as mock_rc, \
         patch("api.services.strategy_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_rc.return_value = {}
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_instance

        from api.services.strategy_generator import generate_strategy
        result = await generate_strategy({
            "name": "Test Co",
            "dialect": "English",
            "services": ["service"],
            "target_audience": "businesses",
            "how_they_help": "save time",
            "unique_value": "AI-powered",
            "esp": "feel confident",
            "competitors": [],
        })

    assert "marketing_plan" in result
    assert "marketing_message" in result
    assert "language" in result
    assert result["language"] == "en"


@pytest.mark.asyncio
async def test_generate_strategy_detects_arabic_language():
    mock_payload = {"marketing_plan": {}, "marketing_message": "رسالة"}
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(mock_payload))]

    with patch("api.services.strategy_generator.research_competitors", new_callable=AsyncMock) as mock_rc, \
         patch("api.services.strategy_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_rc.return_value = {}
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_instance

        from api.services.strategy_generator import generate_strategy
        result = await generate_strategy({
            "name": "مشروع",
            "dialect": "Palestinian Arabic",
            "services": [],
            "competitors": [],
        })

    assert result["language"] == "ar"
```

- [ ] **Step 4: Run tests — expect import failures (the module doesn't exist yet)**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare
api/.venv/bin/python -m pytest tests/test_strategy_generator.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'api.services.strategy_generator'`

- [ ] **Step 5: Create `api/services/strategy_generator.py`**

```python
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
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

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    data = _parse_json(raw)

    return {
        "marketing_plan": data.get("marketing_plan", {}),
        "marketing_message": data.get("marketing_message", ""),
        "language": "ar" if is_ar else "en",
    }
```

- [ ] **Step 6: Add `pytest.ini` so pytest finds the project**

Create `/Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
pythonpath = .
```

- [ ] **Step 7: Run tests — expect them to pass**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare
api/.venv/bin/python -m pytest tests/test_strategy_generator.py -v
```

Expected output:
```
PASSED tests/test_strategy_generator.py::test_is_arabic_detects_arabic_dialects
PASSED tests/test_strategy_generator.py::test_is_arabic_returns_false_for_english_and_null
PASSED tests/test_strategy_generator.py::test_research_competitors_caps_at_four
PASSED tests/test_strategy_generator.py::test_research_competitors_returns_empty_string_on_failure
PASSED tests/test_strategy_generator.py::test_research_competitors_empty_list_returns_empty_dict
PASSED tests/test_strategy_generator.py::test_generate_strategy_returns_required_keys
PASSED tests/test_strategy_generator.py::test_generate_strategy_detects_arabic_language
7 passed
```

- [ ] **Step 8: Commit**

```bash
git add api/services/strategy_generator.py tests/ pytest.ini
git commit -m "feat: add strategy generator service with competitor research"
```

---

## Task 4: Onboarding router — `POST /generate-strategy` endpoint

**Files:**
- Modify: `api/routers/onboarding.py`

- [ ] **Step 1: Add the import and request model**

At the top of `api/routers/onboarding.py`, add this import:

```python
from ..services.strategy_generator import generate_strategy as _generate_strategy
```

After the `SaveBrandRequest` class, add:

```python
class GenerateStrategyRequest(BaseModel):
    suite_id: str
```

- [ ] **Step 2: Add the endpoint**

After the `save_brand` endpoint, add:

```python
@router.post("/generate-strategy")
async def generate_strategy_endpoint(
    data: GenerateStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = suite.brand or {}
    required = ["services", "target_audience", "how_they_help", "unique_value", "esp"]
    missing = [f for f in required if not brand.get(f)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required brand fields: {', '.join(missing)}"
        )

    try:
        strategy = await _generate_strategy(brand)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Strategy generation failed for suite %s", data.suite_id)
        err_str = str(e).lower()
        if "529" in str(e) or "overloaded" in err_str:
            raise HTTPException(status_code=503, detail="The AI service is temporarily busy. Please try again in a few seconds.")
        raise HTTPException(status_code=500, detail="Strategy generation failed. Please try again.")

    suite.strategy = strategy
    await db.commit()
    return {"strategy": strategy}
```

- [ ] **Step 3: Test the endpoint manually**

```bash
TOKEN="<get a fresh token via POST /api/v1/auth/login>"
SUITE_ID="<suite_id for a suite that has brand saved with all required fields>"

curl -s -X POST http://localhost:8000/api/v1/onboarding/generate-strategy \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Origin: http://localhost:3000" \
  -d "{\"suite_id\":\"$SUITE_ID\"}" | python3 -m json.tool | head -30
```

Expected: JSON with `strategy.marketing_plan`, `strategy.marketing_message`, `strategy.language`

- [ ] **Step 4: Commit**

```bash
git add api/routers/onboarding.py
git commit -m "feat: add generate-strategy endpoint"
```

---

## Task 5: Content generator — inject strategy context

**Files:**
- Modify: `api/services/content_generator.py` (function `_build_brand_summary`, lines 31-52)

The content generator currently takes only the `brand` dict. We need it to also accept the optional `strategy` dict.

- [ ] **Step 1: Update `_build_brand_summary` signature and body**

Replace the entire `_build_brand_summary` function (lines 31-52):

```python
def _build_brand_summary(brand: dict, strategy: Optional[dict] = None) -> str:
    """Build Claude-friendly brand summary from a suite's brand + strategy dicts."""
    name = brand.get("name") or brand.get("tagline", "Business")
    desc = brand.get("description") or brand.get("tagline", "")
    industry = brand.get("industry", "")
    tone = brand.get("tone", "professional and friendly")
    services = brand.get("services") or []
    audience = brand.get("target_audience", "general audience")
    colors = brand.get("colors") or {}
    primary_color = colors.get("primary", "#333333")

    services_str = ", ".join(services[:8]) if services else "general services"

    summary = (
        f"Business name: {name}\n"
        f"Industry: {industry}\n"
        f"Description: {desc}\n"
        f"Services: {services_str}\n"
        f"Brand tone: {tone}\n"
        f"Target audience: {audience}\n"
        f"Primary brand color: {primary_color}"
    )

    if strategy:
        plan = strategy.get("marketing_plan") or {}
        audience_data = plan.get("audience") or {}
        summary += (
            f"\n\nMARKETING STRATEGY CONTEXT:"
            f"\nMarketing message: {strategy.get('marketing_message', '')}"
            f"\nCore audience problem: {audience_data.get('problem', '')}"
            f"\nUSP: {brand.get('unique_value', '')}"
            f"\nESP: {brand.get('esp', '')}"
            f"\nContent themes: {', '.join(plan.get('content_themes') or [])}"
        )

    return summary
```

- [ ] **Step 2: Pass strategy into `_build_brand_summary` from `_generate_ideas`**

In the same file, find the `_generate_ideas` function. Its signature is:

```python
def _generate_ideas(brand: dict, count: int = 3, recent_topics: list[str] | None = None) -> list[dict]:
```

Update it to accept and pass strategy:

```python
def _generate_ideas(brand: dict, count: int = 3, recent_topics: list[str] | None = None, strategy: Optional[dict] = None) -> list[dict]:
```

And update the call inside it from:
```python
    system = _PROMPTS["idea_generator_system"].format(
        brand_summary=_build_brand_summary(brand)
    )
```
to:
```python
    system = _PROMPTS["idea_generator_system"].format(
        brand_summary=_build_brand_summary(brand, strategy)
    )
```

- [ ] **Step 3: Pass `suite.strategy` into `_generate_ideas` from wherever it's called**

Search for calls to `_generate_ideas` in `content_generator.py`:

```bash
grep -n "_generate_ideas" /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/api/services/content_generator.py
```

For each call site that has access to the `suite` object, update it to pass `strategy=suite.strategy`. The call site likely looks like:

```python
ideas = _generate_ideas(suite.brand, count=3, recent_topics=topics)
```

Change to:

```python
ideas = _generate_ideas(suite.brand, count=3, recent_topics=topics, strategy=suite.strategy)
```

- [ ] **Step 4: Commit**

```bash
git add api/services/content_generator.py
git commit -m "feat: inject marketing strategy context into content generation prompts"
```

---

## Task 6: Frontend — update types and API client

**Files:**
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Add `how_they_help` and `esp` to the `Brand` interface**

In `api.ts`, find the `Brand` interface and add two fields:

```typescript
export interface Brand {
  name?: string;
  tagline?: string;
  description?: string;
  services?: string[];
  products?: string[];
  colors?: { primary?: string; secondary?: string; accent?: string };
  tone?: string;
  industry?: string;
  location?: string;
  logo_url?: string;
  logo_description?: string;
  target_audience?: string;
  competitors?: string[];
  social_links?: { instagram?: string; facebook?: string; tiktok?: string };
  unique_value?: string;    // USP
  how_they_help?: string;   // new — outcome/problem solved
  esp?: string;             // new — emotional benefit
  dialect?: string;
  // AI suggestions
  color_palette?: { primary: string; secondary: string; accent: string; reasoning?: string };
  font_suggestions?: string[];
  logo_concepts?: { concept: string }[];
}
```

- [ ] **Step 2: Add the `MarketingStrategy` interface**

After the `Brand` interface, add:

```typescript
export interface CompetitorEntry {
  name: string;
  website: string | null;
  social_links: { instagram: string | null; facebook: string | null; tiktok: string | null };
  google_profile: string | null;
  usp: string;
  esp: string;
}

export interface AudiencePersona {
  name: string;
  age: number;
  profession: string;
  needs: string;
  challenges: string;
}

export interface MarketingPlan {
  services: string[];
  keywords: string[];
  competitors: CompetitorEntry[];
  audience: {
    problem: string;
    demographics: { age: string; gender: string; language: string; social_status: string };
    geography: { countries: string[]; regions: string[]; cities: string[] };
    interests: string[];
    facebook_interests: string[];
    digital_behavior: string;
    personas: AudiencePersona[];
  };
  content_themes: string[];
}

export interface MarketingStrategy {
  marketing_plan: MarketingPlan;
  marketing_message: string;
  language: string;
}
```

- [ ] **Step 3: Add `strategy` field to the `Suite` interface**

Find the `Suite` interface and add:

```typescript
export interface Suite {
  id: string;
  name: string;
  slug: string;
  status: "onboarding" | "active" | "suspended";
  brand: Brand | null;
  strategy: MarketingStrategy | null;    // new
}
```

- [ ] **Step 4: Add `generateStrategy` to the `onboarding` API**

In the `api.onboarding` object, add:

```typescript
generateStrategy: (data: { suite_id: string }) =>
  request<{ strategy: MarketingStrategy }>("/onboarding/generate-strategy", {
    method: "POST",
    body: JSON.stringify(data),
  }),
```

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat: add MarketingStrategy types and generateStrategy API method"
```

---

## Task 7: Frontend — three new signup wizard steps

**Files:**
- Modify: `web/src/app/(dashboard)/suite/new/page.tsx`

This is the largest frontend change. The existing `"review"` step is replaced by three new steps. The full updated file is below.

- [ ] **Step 1: Update the Step type and STEPS array**

Find and replace at the top of the file:

```typescript
// Old:
type Step = "name" | "links" | "extracting" | "review" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "links", label: "Links" },
  { key: "extracting", label: "Analyzing" },
  { key: "review", label: "Review" },
  { key: "done", label: "Done" },
];
```

```typescript
// New:
type Step = "name" | "links" | "extracting" | "complete" | "strategy" | "preview" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "links", label: "Links" },
  { key: "extracting", label: "Analyzing" },
  { key: "complete", label: "Profile" },
  { key: "strategy", label: "Strategy" },
  { key: "preview", label: "Preview" },
  { key: "done", label: "Done" },
];
```

- [ ] **Step 2: Add new state variables**

Inside `NewSuitePage`, after the existing `useState` declarations, add:

```typescript
const [completeData, setCompleteData] = useState({
  businessName: "",
  services: "",
  targetAudience: "",
  howTheyHelp: "",
  usp: "",
  esp: "",
});
const [strategy, setStrategy] = useState<import("@/lib/api").MarketingStrategy | null>(null);
const [strategyError, setStrategyError] = useState("");
```

- [ ] **Step 3: Update `handleExtract` to go to "complete" step on both success and failure**

Replace the current `handleExtract` function:

```typescript
async function handleExtract(e: React.FormEvent) {
  e.preventDefault();
  setError("");
  const urls = links.map((l) => l.url).filter(Boolean);
  if (urls.length === 0) {
    setError("Add at least one link so we can research your business");
    return;
  }
  setStep("extracting");
  setExtractLog("Scraping your links…");
  const t1 = setTimeout(() => setExtractLog("Searching the web for more info about your business…"), 4000);
  const t2 = setTimeout(() => setExtractLog("Analyzing brand colors, services, and identity with AI…"), 9000);
  try {
    const res = await api.onboarding.extractBrand({
      suite_id: suiteId,
      urls,
      business_name: businessName || suiteName,
    });
    clearTimeout(t1);
    clearTimeout(t2);
    setBrand(res.brand);
    // Pre-fill the complete profile form from extraction
    setCompleteData({
      businessName: res.brand?.name || suiteName,
      services: (res.brand?.services || []).join(", "),
      targetAudience: res.brand?.target_audience || "",
      howTheyHelp: res.brand?.how_they_help || "",
      usp: res.brand?.unique_value || "",
      esp: res.brand?.esp || "",
    });
    setStep("complete");
  } catch {
    clearTimeout(t1);
    clearTimeout(t2);
    // AI failed — go to complete step with empty form for manual entry
    setCompleteData({
      businessName: suiteName,
      services: "",
      targetAudience: "",
      howTheyHelp: "",
      usp: "",
      esp: "",
    });
    setStep("complete");
  }
}
```

- [ ] **Step 4: Add `handleCompleteProfile` and `runGenerateStrategy` functions**

After `handleExtract`, add:

```typescript
async function handleCompleteProfile(e: React.FormEvent) {
  e.preventDefault();
  setError("");
  const updatedBrand = {
    ...(brand || {}),
    name: completeData.businessName,
    services: completeData.services.split(",").map((s) => s.trim()).filter(Boolean),
    target_audience: completeData.targetAudience,
    how_they_help: completeData.howTheyHelp,
    unique_value: completeData.usp,
    esp: completeData.esp,
  };
  setBrand(updatedBrand);
  try {
    await api.onboarding.saveBrand({ suite_id: suiteId, brand: updatedBrand });
    setStep("strategy");
    await runGenerateStrategy();
  } catch (err: unknown) {
    setError(err instanceof Error ? err.message : "Failed to save profile");
  }
}

async function runGenerateStrategy() {
  setStrategyError("");
  try {
    const res = await api.onboarding.generateStrategy({ suite_id: suiteId });
    setStrategy(res.strategy);
    setStep("preview");
  } catch (err: unknown) {
    setStrategyError(err instanceof Error ? err.message : "Strategy generation failed. Please try again.");
  }
}
```

- [ ] **Step 5: Add the three new step render blocks**

Remove the existing `{step === "review" && ...}` block entirely. Add the three new blocks before `{step === "done" && ...}`:

```tsx
{/* ── Step 4: Complete Profile ── */}
{step === "complete" && (
  <form onSubmit={handleCompleteProfile} className="space-y-4">
    <Card className="bg-zinc-900 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle>Complete your business profile</CardTitle>
        <CardDescription className="text-zinc-400">
          We need these details to build your marketing strategy. Pre-filled fields come from our research — review and correct them.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label className="text-zinc-300">Business name</Label>
          <Input
            value={completeData.businessName}
            onChange={(e) => setCompleteData((d) => ({ ...d, businessName: e.target.value }))}
            required
            className="bg-zinc-800 border-zinc-700 text-white"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-zinc-300">Services / Products <span className="text-zinc-500 text-xs">(comma-separated)</span></Label>
          <Input
            value={completeData.services}
            onChange={(e) => setCompleteData((d) => ({ ...d, services: e.target.value }))}
            placeholder="e.g. Social media management, Content creation, Ads"
            required
            className="bg-zinc-800 border-zinc-700 text-white"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-zinc-300">Target audience</Label>
          <textarea
            value={completeData.targetAudience}
            onChange={(e) => setCompleteData((d) => ({ ...d, targetAudience: e.target.value }))}
            placeholder="Who do you serve? Include location, age, profession, interests…"
            required
            rows={2}
            dir="auto"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-white text-sm placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-zinc-300">How do you help them?</Label>
          <textarea
            value={completeData.howTheyHelp}
            onChange={(e) => setCompleteData((d) => ({ ...d, howTheyHelp: e.target.value }))}
            placeholder="What problem do you solve? What outcome do you deliver?"
            required
            rows={2}
            dir="auto"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-white text-sm placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-zinc-300">USP — What makes you unique?</Label>
          <Input
            value={completeData.usp}
            onChange={(e) => setCompleteData((d) => ({ ...d, usp: e.target.value }))}
            placeholder="Your rational advantage over competitors"
            required
            className="bg-zinc-800 border-zinc-700 text-white"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-zinc-300">ESP — How does the client feel after working with you?</Label>
          <Input
            value={completeData.esp}
            onChange={(e) => setCompleteData((d) => ({ ...d, esp: e.target.value }))}
            placeholder="e.g. They feel confident, in control, and proud of their brand"
            required
            className="bg-zinc-800 border-zinc-700 text-white"
          />
        </div>
        {error && (
          <div className="flex items-center gap-2 text-red-400 text-sm bg-red-950/40 border border-red-900 rounded-lg px-4 py-2.5">
            <AlertCircle size={14} /> {error}
          </div>
        )}
      </CardContent>
    </Card>
    <Button type="submit" className="bg-indigo-600 hover:bg-indigo-500 gap-2">
      <ChevronRight size={15} /> Build my marketing strategy
    </Button>
  </form>
)}

{/* ── Step 5: Generating Strategy ── */}
{step === "strategy" && (
  <div className="text-center py-16 space-y-4">
    {strategyError ? (
      <div className="space-y-4">
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-900 rounded-lg px-4 py-3">
          {strategyError}
        </div>
        <Button onClick={runGenerateStrategy} className="bg-indigo-600 hover:bg-indigo-500">
          Try again
        </Button>
      </div>
    ) : (
      <>
        <Loader2 size={44} className="text-indigo-400 animate-spin mx-auto" />
        <div>
          <p className="text-white font-medium text-lg">Building your marketing strategy…</p>
          <p className="text-zinc-400 text-sm mt-2">Researching competitors, building audience profiles, generating your marketing message</p>
        </div>
        <div className="flex flex-col items-center gap-1.5 text-xs text-zinc-600 mt-6">
          <span>🔍 Researching your competitors</span>
          <span>👥 Mapping your target audience</span>
          <span>💡 Generating 10 customer personas</span>
          <span>✍️ Writing your marketing message</span>
        </div>
      </>
    )}
  </div>
)}

{/* ── Step 6: Strategy Preview ── */}
{step === "preview" && strategy && (
  <div className="space-y-4">
    <Card className="bg-zinc-900 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle>Your marketing strategy is ready</CardTitle>
        <CardDescription className="text-zinc-400">
          Your marketing message and full plan are saved. Access them anytime from the Strategy tab in your dashboard.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="bg-indigo-950/40 border border-indigo-800 rounded-lg p-4">
          <p className="text-indigo-300 text-xs font-medium mb-2 uppercase tracking-wide">Your marketing message</p>
          <p className="text-white text-sm leading-relaxed" dir="auto">{strategy.marketing_message}</p>
        </div>
        {strategy.marketing_plan?.content_themes?.length > 0 && (
          <div>
            <p className="text-zinc-400 text-xs mb-2">Content themes</p>
            <div className="flex flex-wrap gap-1.5">
              {strategy.marketing_plan.content_themes.map((t) => (
                <Badge key={t} variant="outline" className="border-zinc-700 text-zinc-300 text-xs">{t}</Badge>
              ))}
            </div>
          </div>
        )}
        <Button
          onClick={() => { setStep("done"); setTimeout(() => router.push(`/suite/${suiteId}`), 800); }}
          className="bg-indigo-600 hover:bg-indigo-500 gap-2 w-full"
        >
          <CheckCircle2 size={14} /> Go to my suite dashboard
        </Button>
      </CardContent>
    </Card>
  </div>
)}
```

- [ ] **Step 6: Remove the old `{step === "review" && ...}` block**

Delete the entire `{step === "review" && brand && (...)}` block (it starts with `{step === "review" && brand && (` and ends with its closing `)}`) from the render section. Also delete the `handleSave` function from the component since it's no longer used.

- [ ] **Step 7: Verify the page compiles**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/web
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 8: Test the flow in browser**

Open `http://localhost:3000/suite/new` and walk through all 7 steps. Verify:
- Step 1 (Name) → creates suite, gets suite_id
- Step 2 (Links) → add a real URL
- Step 3 (Extracting) → shows loading, then goes to "complete"
- Step 4 (Complete) → fields pre-filled from extraction, can edit all 5
- Submit → shows "strategy" loading step
- Strategy loads → shows "preview" with marketing message
- Click "Go to dashboard" → redirects to `/suite/<id>`

- [ ] **Step 9: Commit**

```bash
git add web/src/app/\(dashboard\)/suite/new/page.tsx
git commit -m "feat: add Complete Profile, Generating Strategy, and Strategy Preview steps to signup wizard"
```

---

## Task 8: Frontend — Strategy tab in suite dashboard

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`

- [ ] **Step 1: Add `MarketingStrategy` to the import from `@/lib/api`**

Find the import line:
```typescript
import { api, Suite, Post, Connections, AnalyticsData, InsightPoint } from "@/lib/api";
```

Add `MarketingStrategy` to it:
```typescript
import { api, Suite, Post, Connections, AnalyticsData, InsightPoint, MarketingStrategy, AudiencePersona, CompetitorEntry } from "@/lib/api";
```

- [ ] **Step 2: Add a `Map` icon import**

In the lucide-react import, add `Map` and `Target`:
```typescript
import {
  Zap, BarChart3, Calendar, Settings, Globe, AtSign, Share2,
  Loader2, CheckCircle2, XCircle, RefreshCw, Hash, ImageIcon, LayoutList, Video,
  Link2, Link2Off, CreditCard, Map, Target,
} from "lucide-react";
```

- [ ] **Step 3: Add the Strategy tab trigger**

Find the `<TabsList>` component in the file and add the Strategy trigger. Look for the existing tab triggers (they look like `<TabsTrigger value="content">Content</TabsTrigger>`) and add:

```tsx
<TabsTrigger value="strategy" className="...existing classes...">
  <Target size={14} className="mr-1.5" /> Strategy
</TabsTrigger>
```

Match the className of existing triggers in the file.

- [ ] **Step 4: Add the Strategy tab content**

After the last `<TabsContent>` block and before the closing `</Tabs>`, add:

```tsx
{/* ── Strategy Tab ── */}
<TabsContent value="strategy">
  <StrategyPanel strategy={suite.strategy} suiteId={id} onRegenerate={async () => {
    try {
      const res = await api.onboarding.generateStrategy({ suite_id: id });
      setSuite((s) => s ? { ...s, strategy: res.strategy } : s);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Regeneration failed");
    }
  }} />
</TabsContent>
```

- [ ] **Step 5: Add the `StrategyPanel` component**

At the bottom of the file (before `export default`), add this component:

```tsx
function StrategyPanel({
  strategy,
  suiteId,
  onRegenerate,
}: {
  strategy: MarketingStrategy | null;
  suiteId: string;
  onRegenerate: () => Promise<void>;
}) {
  const [regenerating, setRegenerating] = React.useState(false);

  if (!strategy) {
    return (
      <Card className="bg-zinc-900 border-zinc-800 text-white">
        <CardContent className="py-12 text-center">
          <Target size={36} className="text-zinc-600 mx-auto mb-3" />
          <p className="text-zinc-400 text-sm">No marketing strategy yet.</p>
          <p className="text-zinc-500 text-xs mt-1">Complete your suite setup to generate one.</p>
        </CardContent>
      </Card>
    );
  }

  const plan = strategy.marketing_plan;
  const audience = plan?.audience;

  return (
    <div className="space-y-4">
      {/* Marketing message */}
      <Card className="bg-indigo-950/40 border-indigo-800 text-white">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-indigo-300 font-medium">Marketing Message</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-white text-sm leading-relaxed" dir="auto">{strategy.marketing_message}</p>
        </CardContent>
      </Card>

      {/* Audience overview */}
      {audience && (
        <Card className="bg-zinc-900 border-zinc-800 text-white">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 font-normal">Target Audience</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {audience.problem && (
              <div>
                <p className="text-zinc-500 text-xs mb-1">Core problem we solve</p>
                <p className="text-white text-sm" dir="auto">{audience.problem}</p>
              </div>
            )}
            {audience.demographics && (
              <div className="grid grid-cols-2 gap-2 text-xs">
                {Object.entries(audience.demographics).map(([k, v]) => (
                  <div key={k} className="bg-zinc-800 rounded px-2 py-1.5">
                    <span className="text-zinc-500 capitalize">{k.replace("_", " ")}: </span>
                    <span className="text-zinc-300">{v as string}</span>
                  </div>
                ))}
              </div>
            )}
            {audience.facebook_interests?.length > 0 && (
              <div>
                <p className="text-zinc-500 text-xs mb-1.5">Meta Ads interests (copy-paste ready)</p>
                <div className="flex flex-wrap gap-1">
                  {audience.facebook_interests.map((i) => (
                    <span key={i} className="text-xs bg-blue-950/60 text-blue-300 border border-blue-800 px-2 py-0.5 rounded">{i}</span>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Content themes */}
      {plan?.content_themes?.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800 text-white">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 font-normal">Content Themes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1.5">
              {plan.content_themes.map((t) => (
                <Badge key={t} variant="outline" className="border-zinc-700 text-zinc-300 text-xs" dir="auto">{t}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Competitors */}
      {plan?.competitors?.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800 text-white">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 font-normal">Competitor Analysis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {plan.competitors.map((c: CompetitorEntry) => (
              <div key={c.name} className="border border-zinc-800 rounded-lg p-3 space-y-1">
                <p className="text-white text-sm font-medium">{c.name}</p>
                {c.website && <p className="text-indigo-400 text-xs">{c.website}</p>}
                {c.usp && <p className="text-zinc-400 text-xs"><span className="text-zinc-500">USP: </span>{c.usp}</p>}
                {c.esp && <p className="text-zinc-400 text-xs"><span className="text-zinc-500">ESP: </span>{c.esp}</p>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Personas */}
      {audience?.personas?.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800 text-white">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 font-normal">Customer Personas</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead>
                  <tr className="border-b border-zinc-800">
                    {["Name", "Age", "Profession", "Needs", "Challenges"].map((h) => (
                      <th key={h} className="pb-2 pr-4 text-zinc-500 font-normal">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {audience.personas.map((p: AudiencePersona) => (
                    <tr key={p.name} className="border-b border-zinc-900">
                      <td className="py-2 pr-4 text-white" dir="auto">{p.name}</td>
                      <td className="py-2 pr-4 text-zinc-300">{p.age}</td>
                      <td className="py-2 pr-4 text-zinc-300" dir="auto">{p.profession}</td>
                      <td className="py-2 pr-4 text-zinc-400" dir="auto">{p.needs}</td>
                      <td className="py-2 pr-4 text-zinc-400" dir="auto">{p.challenges}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Regenerate */}
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          className="border-zinc-700 text-zinc-400 hover:bg-zinc-800 gap-2"
          disabled={regenerating}
          onClick={async () => {
            setRegenerating(true);
            await onRegenerate();
            setRegenerating(false);
          }}
        >
          {regenerating ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Regenerate strategy
        </Button>
      </div>
    </div>
  );
}
```

You will need to add `import React from "react"` at the top if not already imported, since the `StrategyPanel` uses `React.useState`.

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd /Users/wisamsholy/Documents/GitHub/Claudeai/oneshare/web
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 7: Test the Strategy tab in the browser**

Open `http://localhost:3000/suite/<suite_id>` for a suite that has completed strategy generation. Click the "Strategy" tab. Verify:
- Marketing message displayed
- Audience demographics shown
- Meta Ads interests shown
- Content themes shown
- Competitor analysis shown
- Personas table renders
- "Regenerate strategy" button works

- [ ] **Step 8: Commit**

```bash
git add web/src/app/\(dashboard\)/suite/\[id\]/page.tsx
git commit -m "feat: add Strategy tab to suite dashboard"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All spec requirements mapped to tasks:
  - 3 new signup steps → Task 7
  - `how_they_help` + `esp` brand fields → Tasks 2 + 6
  - `strategy` DB column → Task 1
  - Competitor research → Task 3 (`research_competitors`)
  - Marketing plan generation → Task 3 (`generate_strategy`)
  - Marketing message generation → Task 3 (combined in one Claude call)
  - Language detection (Arabic vs English) → Task 3 (`_is_arabic`)
  - Strategy tab in dashboard → Task 8
  - Content generation injection → Task 5
  - AI failure fallback → Task 7 (`handleExtract` catch goes to "complete")
  - Strategy generation retry → Task 7 ("Try again" button in "strategy" step)

- [x] **No placeholders:** All code blocks complete, all commands include expected output.

- [x] **Type consistency:** `MarketingStrategy` defined in Task 6, used in Tasks 7 and 8. `CompetitorEntry` and `AudiencePersona` defined in Task 6, imported in Task 8. `how_they_help` and `esp` added to `Brand` in Task 6, read in Task 3 (`brand.get("how_they_help")`). `generate_strategy` function name in Task 3 matches import alias `_generate_strategy` in Task 4.
