# Marketing Strategy Generation — Signup Flow Design

**Date:** 2026-05-15  
**Status:** Approved

---

## Context

The current signup flow collects a business name and links, scrapes brand data, and saves it. It produces a brand profile (colors, services, tone, etc.) but nothing about marketing positioning — no audience breakdown, no USP/ESP, no marketing plan, no messaging framework.

The goal is to produce a complete marketing strategy for every suite during signup: a structured marketing plan and a marketing message that feed into all future content generation. The Arabic prompt template provided by the user is the basis for the marketing plan generation.

---

## New Signup Wizard Steps

The existing 5-step flow gains 3 new steps after brand extraction:

| Step | Name | What Happens |
|------|------|-------------|
| 1 | Name | Enter suite name (unchanged) |
| 2 | Links | Add business links (unchanged) |
| 3 | Extracting | AI scrapes + extracts brand (unchanged) |
| **4** | **Complete Profile** | Form for missing strategy fields (new) |
| **5** | **Generating Strategy** | Loading state — AI generates plan + message (new) |
| **6** | **Strategy Preview** | Shows the generated marketing message (new) |
| 7 | Done | Redirect to suite dashboard (unchanged) |

### Step 4 — Complete Profile

Collects the 5 required strategy fields. Fields the AI already extracted are pre-filled. Only gaps are shown as empty. If AI extraction failed (529 error or network failure), all fields appear empty — the user fills everything manually.

**Required fields:**
- **Services / Products** — pre-filled from `brand.services` / `brand.products` if extracted
- **Target audience** — who they serve: geo, demographics, interests, challenges. Pre-filled from `brand.target_audience`
- **How you help them** — the outcome/problem they solve (new field: `brand.how_they_help`)
- **USP** — rational advantage that differentiates them. Pre-filled from `brand.unique_value`
- **ESP** — emotional benefit the client feels. New field: `brand.esp`

All 5 fields must be non-empty before the user can proceed.

### Step 5 — Generating Strategy

Loading screen. The backend concurrently:
1. Researches competitors via web search (reuses `search_business()` from `multi_scraper.py`)
2. Generates the marketing plan with Claude
3. Generates the marketing message with Claude

Estimated duration: 20-30 seconds.

### Step 6 — Strategy Preview

Displays the marketing message (filled template) as a "your strategy is ready" confirmation. User proceeds to the dashboard where the full marketing plan is accessible via the Strategy tab.

---

## Data Model Changes

### Suite model — new `strategy` column

**File:** `api/models/suite.py`

Add a JSON column alongside the existing `brand` column:
```python
strategy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

The `strategy` dict shape:
```python
{
  "marketing_plan": {
    "services": [...],
    "keywords": [...],
    "competitors": [
      {
        "name": str,
        "website": str | None,
        "social_links": { "instagram": str, "facebook": str, ... },
        "google_profile": str | None,
        "usp": str,
        "esp": str
      }
    ],
    "audience": {
      "problem": str,
      "demographics": { "age": str, "gender": str, "language": str, "social_status": str },
      "geography": { "countries": [...], "regions": [...], "cities": [...] },
      "interests": [...],
      "facebook_interests": [...],   # English, as written in Meta Ads
      "digital_behavior": str,
      "personas": [                  # 10 personas
        { "name": str, "age": int, "profession": str, "needs": str, "challenges": str }
      ]
    },
    "content_themes": [...]
  },
  "marketing_message": str,          # The filled Arabic/English template
  "language": str                    # "ar" | "en" | "ar-Palestinian" etc.
}
```

### Brand model — new fields

**Files:** `api/models/suite.py` (JSON), `web/src/lib/api.ts` (TypeScript interface)

Add to the `Brand` interface and extraction prompt:
- `how_they_help: Optional[str]` — outcome/problem solved
- `esp: Optional[str]` — emotional benefit (how client feels after)

Note: `unique_value` already exists and maps to USP. No rename needed — the manual form field for "USP" saves into `brand.unique_value`.

---

## New Backend Service

### `api/services/strategy_generator.py` (new file)

Two async functions:

**`research_competitors(competitors: list[str], business_name: str) -> list[dict]`**
- Takes up to 4 competitors (capped — already extracted by `extract_brand_from_sources`)
- For each, calls `search_business(competitor_name)` concurrently via `asyncio.gather`
- Parses search snippets to extract: website URL, Instagram/Facebook handles, Google Business URL, detected USP/ESP
- Times out gracefully (15s per competitor) — if a competitor can't be researched, it's included with only its name
- Returns list of competitor dicts

**`generate_strategy(brand: dict, suite_id: str) -> dict`**
- Detects language from `brand.dialect` (Arabic variants → Arabic prompt, else English)
- Builds the marketing plan prompt (the Arabic template structure from user spec)
- Builds the marketing message template (filled with name, services, audience, USP, ESP)
- Calls `anthropic.AsyncAnthropic` for both (can be parallelized with `asyncio.gather`)
- Returns the full strategy dict

---

## New API Endpoint

### `POST /api/v1/onboarding/generate-strategy`

**File:** `api/routers/onboarding.py`

Request body:
```python
class GenerateStrategyRequest(BaseModel):
    suite_id: str
```

Behavior:
1. Auth check (existing pattern via `get_current_user`)
2. Load suite + brand from DB
3. Validate all 5 required fields present in `brand`
4. Call `generate_strategy(brand, suite_id)`
5. Save result to `suite.strategy`
6. Return `{ "strategy": strategy_dict }`

Wrapped in try/except → raises `HTTPException(503)` for Anthropic overload, `HTTPException(500)` for other failures. (Same pattern as the fix applied to `extract-brand`.)

---

## Frontend Changes

### `web/src/app/(dashboard)/suite/new/page.tsx`

Add steps: `"complete"`, `"strategy"`, `"preview"` to the Step type and STEPS array.

**Step "complete"** — form with 5 fields (pre-filled from brand extraction results).  
**Step "strategy"** — loading screen with animated progress messages.  
**Step "preview"** — displays `strategy.marketing_message` in a card with a "Go to dashboard" button.

The existing `handleExtract` error handler redirects to the **"complete"** step on failure (instead of returning to "links") — this is the AI fallback path. The "complete" step form works with or without prior extraction data.

**Strategy generation failure (step 5):** If `generate-strategy` fails (503 overloaded), the user sees an inline error with a "Try again" button — they do not lose their filled form data. The "complete" step data is held in React state throughout.

### `web/src/lib/api.ts`

Add to `onboarding`:
```typescript
generateStrategy: (data: { suite_id: string }) =>
  request<{ strategy: MarketingStrategy }>("/onboarding/generate-strategy", {
    method: "POST",
    body: JSON.stringify(data),
  }),
```

Add `MarketingStrategy` TypeScript interface matching the strategy dict shape above.

Add `how_they_help?: string` and `esp?: string` to the `Brand` interface.

### `web/src/app/(dashboard)/suite/[id]/page.tsx`

Add a "Strategy" tab to the suite dashboard tabs. Tab is present but not highlighted in the nav. It renders:
- Marketing message (boxed, prominent)
- Full marketing plan in structured sections
- Regenerate button (`POST /onboarding/generate-strategy`)

---

## Content Generation Integration

**File:** `api/services/content_generator.py`

When building the brand summary for Claude, check if `suite.strategy` exists. If it does, append to the prompt:

```
MARKETING STRATEGY CONTEXT:
Marketing message: {strategy['marketing_message']}
Target audience summary: {strategy['marketing_plan']['audience']['problem']}
USP: {brand['unique_value']}
ESP: {brand['esp']}
Content themes: {', '.join(strategy['marketing_plan']['content_themes'])}
```

No other changes to content generation logic.

---

## Marketing Plan Prompt Structure

The Claude prompt builds the marketing plan using this Arabic template (or English equivalent):

```
النص التعريفي:
أنت خبير تسويق إلكتروني، وأنا عميلك: {brand.name}
أقدم هذه الخدمات/المنتجات: {brand.services joined}
جمهوري المستهدف هو: {brand.target_audience}
أنا أساعدهم في: {brand.how_they_help}

بناءً على هذا النص، أعطني خطة تسويقية ناجحة تشمل:
1. خدماتي ومنتجاتي
2. الكلمات المفتاحية التي قد يستخدمها جمهوري
3. جدول المنافسين (لكل منافس: اسمه، موقعه، روابط صفحاته الاجتماعية، Google Profile إن وُجد، USP، ESP)
4. تحديد جمهور الهدف:
   - المشكلة والحاجة التي أحلها
   - الديموغرافيا: العمر | الجنس | اللغة | الحالة الاجتماعية
   - الجغرافيا: الدولة | المنطقة | المدينة
   - الاهتمامات (جدول بالهوايات ونمط الحياة + جدول بالاهتمامات كما تظهر في Facebook Ads بالإنجليزي)
   - السلوك الرقمي (المنصات التي يستخدمها الجمهور)
   - 10 شخصيات من الجمهور المستهدف (جدول: الاسم، العمر، المهنة، الاحتياجات، التحديات)
5. المحاور المقترحة للمحتوى
```

The marketing message template:
```
بالنسبة لـ {target_audience} الذين {problem/need}
فإن {brand.name} هي {services_type}
التي توفّر {brand.unique_value (USP)}
حتى يشعروا بـ {brand.esp (ESP)}
```

Claude is instructed to return a structured JSON for the marketing plan (so it can be rendered section-by-section) and a plain string for the marketing message.

---

## Verification

1. **Happy path — with links:** Create a suite with a real business URL → extraction runs → Complete Profile shows pre-filled fields → user fills gaps → strategy generates → marketing message displayed → suite dashboard has Strategy tab
2. **Happy path — no links (manual):** Skip all links → lands on Complete Profile with empty fields → fill all manually → strategy generates → same outcome
3. **AI failure fallback:** If extraction returns 529 → user lands on Complete Profile with empty form → fills manually → strategy generates normally
4. **Strategy tab:** After signup, open suite dashboard → Strategy tab shows marketing message + full plan
5. **Content generation:** Generate posts → verify the prompt sent to Claude includes the marketing message context (check uvicorn logs with `DEBUG=true`)
6. **Language detection:** Arabic business → plan generated in Arabic. English business → plan generated in English.
