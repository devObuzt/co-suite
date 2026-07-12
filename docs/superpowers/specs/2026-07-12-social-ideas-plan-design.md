# Social Content Plan → Idea-Selection Experience (Milestone 1)

**Date:** 2026-07-12
**Status:** Design — pending user review
**Owner surface:** existing Social Content Work Plan (System A), `marketing_plan_generator.py` + work-plans page.

## ملخّص بالعربي (لمراجعة المالك)

منحوّل خطة السوشيال من "توليد محتوى/بوستات" إلى **"عرض أفكار + كيفية تطبيقها"**. المستخدم يحدّد الوتيرة (مثلاً 12/شهر)، النظام يفحص المناسبات وأبحاث السوق (مخزّنة ومعاد استخدامها حسب الدولة+اللغة)، يولّد **ضعف العدد أفكار (24)**، ويعرضها كـ**تغذية واحدة مع فلاتر**؛ المستخدم يختار 12، يدوّن ملاحظات، ويختار أصول التطبيق (الوسط مختار مسبقاً). المخرج = أفكار مختارة محفوظة. **مؤجّل:** توليد المحتوى، التقويم، الترندات، التسعير.

---

## 1. Goal & problem

Today the social work plan generates near-final content items laid out on a calendar. We want it to instead surface **ideas with implementation approaches** the user curates: over-generate, let the user pick a target set, capture notes, and recommend the digital assets each idea needs. This also seeds a later services/pricing layer.

## 2. Scope

**In (Milestone 1 — one month, full vertical slice):**
- Cadence recommendation at start (reuse existing) → sets target count `N`.
- Research phase: occasions/holidays + market research, cached & reused by `(country, language)`.
- Idea generation reshaped to **ideas, not content**, over-generating `2N`.
- Idea-selection gallery: single feed + filter chips, inline-accordion cards, sticky counter `x/N`, per-idea notes, how-to-apply asset chips (recommended "middle" set preselected).
- Persist the selected ideas (+ notes + chosen assets) on the suite.

**Out (deferred, explicitly):**
- Actual content/media generation from selected ideas.
- Calendar/scheduling view (removed from this surface for now).
- Trends/virals research (`kind` reserved for it).
- Services/pricing derived from selected assets.
- Behavioral learning / auto-rules for client stories.

## 3. Confirmed decisions

1. Reshape existing System A work plan; **replace the calendar with an idea-selection gallery**.
2. Reusable research store: new `research_cache` table, key `(kind, country, language, period)`, shared across suites, extensible (`kind` reserved for `trends` later). Stores **occasions + market research**.
3. Occasions sourcing: **hybrid** — LLM proposes, web search (SerpAPI) verifies movable/sports dates.
4. How-to-apply: **asset chips**, AI recommends a **balanced "middle" set preselected**; user toggles. Asset taxonomy **extended**.
5. Client story: **AI-generated illustrative example**, explicitly labeled "مثال توضيحي حالياً", user-editable. Behavioral learning later.
6. Over-generate **2×** the cadence target.
7. Idea card: **inline accordion expansion (Option A)**, **mobile-first**.
8. Gallery: **single feed + filter chips** (الكل/جذب/ثقة/مبيعات/مناسبات); occasions surfaced first.

## 4. Architecture & data flow

```
User opens plan → cadence recommendation → target N (e.g. 12)
        │
        ▼
Research phase (new), keyed by brand.country + brand.audience_language:
  occasions  = research_cache.get(kind="occasions", country, lang, period="YYYY-MM")
               miss → occasions_service (LLM propose + SerpAPI verify) → store
  market     = research_cache.get(kind="market", country, lang, period=null)
               miss → market_service (reuse strategy research) → store
        │
        ▼
Occasion→brand relevance filter (keep occasions matching brand field/industry)
        │
        ▼
Idea generation (modified prompts): request 2N IDEAS (not content),
  weaving relevant occasions (occasion-tied) + evergreen, keeping the
  attraction/trust/sales 70/20/10 objective mix and production/format concept.
  Each idea → new idea shape (below), with a preselected "middle" asset set.
        │
        ▼
Gallery (single feed + filters): user selects N, edits notes, toggles assets
        │
        ▼
Persist selected ideas (+notes+assets) on suite.strategy
```

- Built on top of `generate_social_content_work_plan` (`marketing_plan_generator.py:2087`); the scheduling/`build_social_plan_schedule` step is replaced by selection.
- Research runs **before** generation; results injected into the prompt context (`_social_content_plan_context`).
- All provider calls wrapped in `external_call()` per project convention.

## 5. Data model

### New table `research_cache` (shared, extensible)
```
id            uuid pk
kind          text   -- "occasions" | "market"  (reserved: "trends")
country       text   -- normalized code/name from brand.location
language      text   -- audience language code from brand.audience_languages[0]
period        text?  -- "2026-08" for occasions; null for general market
data          jsonb
source        text   -- "llm" | "web" | "hybrid"
created_at    timestamptz
refreshed_at  timestamptz
expires_at    timestamptz?   -- occasions expire after the period; market ~90d
UNIQUE(kind, country, language, period)
```
- `occasions.data`: `[{title, type: religious|national|school|sports|seasonal|commercial, date_or_window, confidence: high|medium|low, verified_by: "web"|"llm"}]`
- `market.data`: `{audience_behavior, local_trends, competitors_summary}`

### Idea shape (stored in `suite.strategy`, no new per-idea table this milestone)
```
id, objective_type: attraction|trust|sales,
title, short_description,
occasion_ref?: {title, date_or_window},
client_story: {text, example, is_illustrative: true},
apply_assets: [{asset_type, recommended: bool}],   -- recommended=true is the "middle" set
user_notes?: string,
selected: bool
```
Plan wrapper keeps existing fields (`language, dialect, cadence`) and adds `target_count: N`, `candidates` (the 2N), `selected_ids`.

### Extended asset taxonomy `APPLY_ASSET_TYPES`
`ugc, talking_head, image, banner, carousel, ai_video, landing_page, webinar, website, app, digital_asset_other`
(extends the current production_mode set which lacked landing_page/webinar/website/app.)

## 6. Components

- **`occasions_service`** (new): `get_occasions(country, language, period)` → cache-or-fetch. Fetch = LLM proposes candidate occasions for the country+period; SerpAPI verifies dates for movable/sports/school events; low-confidence unverifiable items kept but flagged `confidence: low`. Idempotent upsert into `research_cache`.
- **`market_research`** (new thin wrapper): reuse existing `strategy_generator` research; cache under `research_cache`.
- **`occasion_match`** (new, pure): filter occasions to those relevant to the brand field/industry; returns a ranked shortlist.
- **Prompt changes** (`build_social_content_plan_prompt`, `DEFAULT_SOCIAL_WORK_PLAN_PROMPTS`): request ideas not content; inject occasions + market context; emit the new idea shape incl. the preselected middle asset set. Keep agency identity/dialect rules.
- **Idea gallery UI** (replaces `SocialPlanCalendar`): single scrollable feed, sticky header with counter `x/N`, filter chips, inline-accordion cards (compact → expand: story, notes, asset chips, select/add).
- **Endpoints**: reuse `.../social-content-plan/generate` (now returns candidates), `.../selection` (persist selected + notes + assets). Add asset-toggle/notes into the selection payload.

## 7. Selection semantics

- Target `N` = recommended cadence (editable at start).
- Generate `2N` candidates; objective mix 70/20/10 preserved across the `2N`.
- Occasion-tied ideas: each strongly-relevant occasion in the period yields ≥1 idea; remainder evergreen.
- Counter shows `selected/N`. `N` is a **target**, not a hard cap: user may select up to `N` freely; selecting beyond `N` is allowed but visually flagged (soft cap). Zero selection allowed (draft).

## 8. Error handling

- **Research miss + provider failure:** occasions/market fetch failure → proceed with empty occasions and a warning surfaced in the plan `warnings[]`; ideas still generate (evergreen only).
- **SerpAPI verification failure:** keep LLM-proposed occasions flagged `confidence: low`; never block generation.
- **Idea generation failure:** existing `_fallback_social_content_items` path adapted to the new idea shape (templated ideas), so the gallery always has content.
- **Missing brand country/language:** fall back to `infer_plan_language` + a global/neutral occasions set; warn.
- **Cache staleness:** occasions past `period` and market past `expires_at` are refetched.

## 9. Testing

- **Unit (pure):** `occasion_match` relevance filter; asset "middle" set derivation; over-generation count math (`2N`, mix split); idea-shape normalization; `research_cache` upsert idempotency (unique key).
- **Service:** `occasions_service` cache hit vs miss (mock LLM + SerpAPI); market cache reuse; generation with/without occasions; fallback path yields valid idea shape.
- **Prompt:** snapshot the reshaped prompt asserts it requests ideas (no ready caption/script) and includes injected occasions.
- **API:** generate returns `2N` candidates with the new shape; selection persists notes + chosen assets; warnings populated on research failure.
- **Manual (user-verify):** run a month plan for a real suite; confirm occasions surface, ideas are ideas (not posts), gallery selection + counter + notes + asset chips work on mobile.

## 10. Open items / future

- Behavioral learning + rules for client stories.
- Trends/virals (`kind="trends"` reuses `research_cache`).
- Content/media generation from selected ideas.
- Services/pricing from selected assets (the "middle" set is the pricing basis).
- Calendar/scheduling reintroduction (optional).
