# Staged Marketing Plan Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first staged marketing plan workspace with editable services/products, generated keywords, mock competitor cards, generate-more actions, and stage detail pages.

**Architecture:** Keep Suite profile data as the source for services/products and store generated stage outputs in `suite.strategy.marketing_intelligence`. Replace the existing market tab-centric UI with reusable stage widgets that work on the main page and detail pages.

**Tech Stack:** FastAPI, SQLAlchemy async models, existing JSON Suite `brand` and `strategy`, Next.js App Router, React client components, existing API helper.

## Global Constraints

- `Regenerate` is out of scope.
- No token charging in this slice.
- Stage actions must not use the full strategic marketing plan job progress state.
- SerpAPI is not implemented yet; competitor cards use final-shape mock data.
- Services/products edits update `suite.brand.services`.

---

### Task 1: Backend Stage Contracts

**Files:**
- Modify: `api/services/marketing_plan_generator.py`
- Modify: `api/routers/marketing_plans.py`
- Test: `tests/test_marketing_plan_routes.py`

**Interfaces:**
- Produces: `MarketingPlanStageRequest`, keyword generate endpoints, competitor generate-more endpoint, competitor classification endpoint.
- Consumes: existing `_marketing_plan_response(...)`.

- [x] Add normalization preservation for `keywords` and competitor card metadata.
- [x] Add helpers for fallback keywords and final-shape mock competitors.
- [x] Add tests for service update payloads, keyword append without duplicates, competitor append, and competitor tag persistence.
- [x] Run backend route tests.

### Task 2: Frontend API Contract

**Files:**
- Modify: `web/src/lib/api.ts`

**Interfaces:**
- Produces: typed `MarketingKeyword`, extended `MarketingCompetitor`, and API functions for stage generation.

- [x] Extend TypeScript interfaces.
- [x] Add `generateKeywords`, `generateMoreKeywords`, `generateMoreCompetitors`, and `updateCompetitor`.
- [x] Reuse existing `api.suites.updateBrand` for services/products.

### Task 3: Stage UI

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/marketing-plan/page.tsx`
- Create: `web/src/components/marketing-plan/MarketingPlanStages.tsx`

**Interfaces:**
- Consumes: frontend API contract and `Brand`.
- Produces: stage cards and widgets reusable by main and detail pages.

- [x] Build services/products editor with add, edit, delete, and save to Suite brand.
- [x] Build keywords stage with Generate and Generate More.
- [x] Build competitor stage with source icons, short URL, open/copy/preview, and multi-select tags.
- [x] Build demand/supply stage with existing generate action.

### Task 4: Detail Pages

**Files:**
- Create: `web/src/app/(dashboard)/suite/[id]/marketing-plan/[stage]/page.tsx`

**Interfaces:**
- Consumes: same stage components as the main page.

- [x] Route stage slugs to services, keywords, competitors, and demand-supply.
- [x] Display the same stage widget in detail mode.

### Task 5: Verification

**Files:**
- All touched files.

- [x] Run `pytest -p no:cacheprovider tests/test_marketing_plan_routes.py tests/test_marketing_plan_generator.py tests/test_generation_jobs.py -q`.
- [x] Run `cd web && npm run build`.
- [x] Commit changes in scoped commits.
