# Marketing Plan Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production MVP for generating, viewing, sharing, password-protecting, and downloading a Suite marketing plan.

**Architecture:** Store the first version inside `Suite.strategy.marketing_plan_deck` to avoid a migration. Add a focused backend service for plan generation and sharing, a router for authenticated/public access, and shared frontend components for the internal and public renderers.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, existing `Suite.strategy` JSON, existing `call_text_ai`, Next.js App Router, browser print CSS for PDF export.

## Global Constraints

- Strategic plan writing uses Claude through `call_text_ai(provider="anthropic")`.
- Do not add a database migration for MVP unless `Suite.strategy` cannot safely hold the data.
- Arabic/Hebrew pages must render RTL using `dir="rtl"` and `dir="auto"` for mixed content.
- Public share links must not expose owner-only controls.
- Passwords must be hashed with existing security helpers or `passlib` if already available; never store plaintext.
- Use existing project patterns and do not refactor unrelated dashboard pages.

---

## File Structure

- Create: `api/services/marketing_plan_generator.py` - builds research context, prompts Claude, normalizes plan deck JSON.
- Create: `api/routers/marketing_plans.py` - authenticated and public endpoints for plan generation/share/unlock.
- Modify: `api/main.py` - include the new router.
- Modify: `web/src/lib/api.ts` - add plan deck types and API client methods.
- Create: `web/src/components/marketing-plan/MarketingPlanView.tsx` - shared plan renderer.
- Create: `web/src/app/(dashboard)/suite/[id]/marketing-plan/page.tsx` - internal plan studio page.
- Create: `web/src/app/marketing-plans/share/[token]/page.tsx` - public shared plan page.
- Modify: `web/src/components/suite/SuiteNav.tsx` - add navigation link to Marketing Plan.
- Modify: `web/src/app/globals.css` - add print styles for PDF export.
- Test: `tests/test_marketing_plan_generator.py`
- Test: `tests/test_marketing_plan_router.py`

---

### Task 1: Backend Plan Data Contract

**Files:**
- Create: `api/services/marketing_plan_generator.py`
- Test: `tests/test_marketing_plan_generator.py`

**Interfaces:**
- Produces: `normalize_plan_deck(raw: dict, suite_name: str, language: str) -> dict`
- Produces: `build_marketing_plan_prompt(suite_payload: dict, language: str) -> str`

- [ ] **Step 1: Write tests for deck normalization**

Create `tests/test_marketing_plan_generator.py` with tests that pass partial AI output and assert required sections are present.

- [ ] **Step 2: Implement `normalize_plan_deck`**

Return an object with `version`, `language`, `status`, `generated_at`, `cover`, `sections`, `research_summary`.

- [ ] **Step 3: Implement prompt builder**

The prompt must request valid JSON only and include all sections from the design spec.

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/private/tmp pytest -p no:cacheprovider tests/test_marketing_plan_generator.py -q`
Expected: PASS.

---

### Task 2: Claude Generation Service

**Files:**
- Modify: `api/services/marketing_plan_generator.py`
- Test: `tests/test_marketing_plan_generator.py`

**Interfaces:**
- Produces: `async generate_marketing_plan_deck(suite: Suite, language: str = "en") -> dict`

- [ ] **Step 1: Add mocked Claude test**

Patch `call_text_ai` to return JSON and assert `provider="anthropic"` is passed.

- [ ] **Step 2: Build suite payload**

Collect `suite.name`, `suite.brand`, `suite.strategy`, `suite.connections`, source links, services, competitors, and available analytics summaries.

- [ ] **Step 3: Call Claude**

Use `await call_text_ai(provider="anthropic", max_tokens=8000, messages=[...])`.

- [ ] **Step 4: Parse and normalize**

Use existing JSON extraction style from `strategy_generator.py`; return a normalized deck even when some fields are missing.

---

### Task 3: Authenticated API Endpoints

**Files:**
- Create: `api/routers/marketing_plans.py`
- Modify: `api/main.py`
- Test: `tests/test_marketing_plan_router.py`

**Interfaces:**
- `GET /api/v1/suites/{suite_id}/marketing-plan`
- `POST /api/v1/suites/{suite_id}/marketing-plan/generate`
- `POST /api/v1/suites/{suite_id}/marketing-plan/share`

- [ ] **Step 1: Add router tests for owner access**

Assert non-owner gets 404 or 403 following existing suite router style.

- [ ] **Step 2: Implement `get_marketing_plan`**

Return existing `suite.strategy.marketing_plan_deck` or `{status:"missing"}`.

- [ ] **Step 3: Implement `generate_marketing_plan`**

Call service, save under `suite.strategy["marketing_plan_deck"]`, commit, return deck.

- [ ] **Step 4: Implement `share_marketing_plan`**

Generate token with `secrets.token_urlsafe(24)`. If password exists, hash it. Store under deck `share`.

---

### Task 4: Public Share API

**Files:**
- Modify: `api/routers/marketing_plans.py`
- Test: `tests/test_marketing_plan_router.py`

**Interfaces:**
- `GET /api/v1/marketing-plans/share/{token}`
- `POST /api/v1/marketing-plans/share/{token}/unlock`

- [ ] **Step 1: Test public locked response**

A password-protected plan returns `{locked:true, title, business_name}` without sections.

- [ ] **Step 2: Test unlock**

Correct password returns the plan. Wrong password returns 401.

- [ ] **Step 3: Implement token lookup**

Search suites where `strategy` contains a matching share token. For MVP, select all suites and filter in Python if JSON querying is not portable.

---

### Task 5: Frontend API Client and Types

**Files:**
- Modify: `web/src/lib/api.ts`

**Interfaces:**
- `api.marketingPlans.get(suiteId)`
- `api.marketingPlans.generate(suiteId, { language })`
- `api.marketingPlans.share(suiteId, { password })`
- `api.marketingPlans.publicGet(token)`
- `api.marketingPlans.unlock(token, password)`

- [ ] **Step 1: Add TypeScript interfaces**

Define `MarketingPlanDeck`, `MarketingPlanSection`, `MarketingPlanShare`.

- [ ] **Step 2: Add client methods**

Follow existing `api.suites` and `api.onboarding` patterns.

- [ ] **Step 3: Run web build**

Run: `npm run build` in `web`.
Expected: PASS.

---

### Task 6: Shared Plan Renderer

**Files:**
- Create: `web/src/components/marketing-plan/MarketingPlanView.tsx`
- Modify: `web/src/app/globals.css`

**Interfaces:**
- `MarketingPlanView({ deck, publicMode }: { deck: MarketingPlanDeck; publicMode?: boolean })`

- [ ] **Step 1: Build cover renderer**

Show image/color split cover inspired by reference PDFs, with business name, subtitle, chips, and date.

- [ ] **Step 2: Build section renderer**

Render sections with title, summary, bullets, cards, and metric blocks based on section shape.

- [ ] **Step 3: Add print CSS**

Hide controls on print, preserve page breaks, set white background, and avoid clipping.

---

### Task 7: Internal Plan Studio Page

**Files:**
- Create: `web/src/app/(dashboard)/suite/[id]/marketing-plan/page.tsx`
- Modify: `web/src/components/suite/SuiteNav.tsx`

**Interfaces:**
- Consumes: frontend API client methods from Task 5.
- Produces: user-facing marketing plan page.

- [ ] **Step 1: Load current deck**

Show missing state with CTA when no plan exists.

- [ ] **Step 2: Add Generate/Refresh action**

Call generate endpoint and show progress state.

- [ ] **Step 3: Add share controls**

Password input, create/update share link, copy URL.

- [ ] **Step 4: Add Download PDF action**

Use `window.print()`.

---

### Task 8: Public Share Page

**Files:**
- Create: `web/src/app/marketing-plans/share/[token]/page.tsx`

**Interfaces:**
- Consumes: public API methods from Task 5.

- [ ] **Step 1: Load public token**

If unlocked, render `MarketingPlanView` in public mode.

- [ ] **Step 2: Add password gate**

If locked, show branded password form. On success, render plan.

- [ ] **Step 3: Handle invalid token**

Show branded not-found message.

---

### Task 9: Verification and Commit

**Files:**
- All files from previous tasks.

- [ ] **Step 1: Run backend tests**

Run: `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/private/tmp pytest -p no:cacheprovider tests/test_marketing_plan_generator.py tests/test_marketing_plan_router.py -q`
Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run: `npm run build` in `web`.
Expected: PASS.

- [ ] **Step 3: Manual QA**

Check Arabic RTL internal page, public locked page, unlocked page, and print preview.

- [ ] **Step 4: Commit only related files**

Stage only files listed in this plan. Do not stage unrelated dirty files.

---

## Self-Review

Spec coverage: all MVP requirements are mapped to Tasks 1-9.
Placeholder scan: no TBD/TODO language remains.
Type consistency: backend `marketing_plan_deck` maps to frontend `MarketingPlanDeck` and shared renderer.
Scope check: backend PDF rendering and multiple plan versions are deferred to keep this MVP shippable.
