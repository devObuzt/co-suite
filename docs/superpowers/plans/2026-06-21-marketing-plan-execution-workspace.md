# Marketing Plan Execution Workspace Implementation Plan

> **For agentic workers:** implement this plan in small slices. Do not replace the existing marketing plan page in one jump. Preserve the current deck, share link, PDF, and generation queue behavior while adding the execution layer.

## Goal

Upgrade Marketing Plan Studio into a practical execution product:

- Market Intelligence: competitors, links, demand/supply, opportunities.
- Strategy Deck: editable client-facing plan.
- Dynamic Action Plan: social calendar items and paid funnel campaign items.
- Apply Workspace: execute full plan, social plan, or ads plan.

## Current Anchors

- Backend generator: `api/services/marketing_plan_generator.py`
- Backend router: `api/routers/marketing_plans.py`
- Generation queue: `api/services/durable_generation_queue.py`
- Internal page: `web/src/app/(dashboard)/suite/[id]/marketing-plan/page.tsx`
- Shared renderer: `web/src/components/marketing-plan/MarketingPlanView.tsx`
- Public page: `web/src/app/marketing-plans/share/[token]/page.tsx`
- Frontend API: `web/src/lib/api.ts`

## Constraints

- Claude is primary for analysis and plan/action reasoning.
- Do not save blank/empty plans.
- Do not create one huge JSON prompt for everything.
- Owner-only execution controls must not appear on public share pages.
- Keep Arabic/Hebrew RTL strong and avoid English-only placeholders.
- Avoid new migrations in the first slice unless `Suite.strategy` becomes unsafe.
- Every async task must expose job status and progress.

---

## Slice 1: Data Contract And UI Shell

**Purpose:** add the structure without requiring all AI/research features to be perfect.

### Backend

- [ ] Add normalizers in `api/services/marketing_plan_generator.py`:
  - `normalize_marketing_intelligence(raw, suite_payload, language)`.
  - `normalize_marketing_action_plan(raw, suite_payload, language)`.
- [ ] Add helper getters/savers:
  - `suite.strategy["marketing_intelligence"]`.
  - `suite.strategy["marketing_action_plan"]`.
- [ ] Add minimal tests proving empty AI output becomes useful but clearly flagged fallback data.

### Frontend

- [ ] Extend API types in `web/src/lib/api.ts`:
  - `MarketingIntelligence`.
  - `MarketingCompetitor`.
  - `MarketingActionPlan`.
  - `MarketingActionItem`.
  - `MarketingApplicationRun`.
- [ ] Refactor the internal plan page into major sections:
  - Market.
  - Strategy.
  - Social Plan.
  - Ads Funnel.
  - Apply.
- [ ] Preserve the existing deck renderer inside Strategy.
- [ ] Add empty/skeleton UI for intelligence and action plan sections.

### Verification

- [ ] `pytest -q tests/test_marketing_plan_generator.py`
- [ ] `npm run build` in `web`
- [ ] Manual mobile smoke for Arabic RTL internal plan page.

---

## Slice 2: Competitor And Demand Intelligence

**Purpose:** show sources and research before recommendations.

### Backend

- [ ] Add a dedicated `generate_marketing_intelligence(...)` flow.
- [ ] Build intelligence context from:
  - Suite links.
  - Existing scraped source summaries.
  - Existing competitor candidates from strategy/profile.
  - Google/Meta connection summaries when available.
  - Search/scraper services where already supported.
- [ ] Prompt Claude for:
  - Competitors with platform/source/link/relevance/confidence.
  - Demand signals.
  - Supply signals.
  - Opportunities.
  - Warnings for unavailable sources.
- [ ] Store under `suite.strategy["marketing_intelligence"]`.
- [ ] Add endpoint:
  - `POST /api/v1/suites/{suite_id}/marketing-plan/generate-intelligence`

### Frontend

- [ ] Render competitor cards with platform tabs:
  - Google.
  - Instagram.
  - Facebook.
  - TikTok.
  - Website.
  - Other.
- [ ] Render demand/supply cards.
- [ ] Render opportunities.
- [ ] Show failed/unavailable source warnings instead of hiding them.

### Verification

- [ ] Backend unit tests for intelligence normalizer.
- [ ] API route test for storing/retrieving intelligence.
- [ ] Mobile/desktop visual smoke with fallback intelligence data.

---

## Slice 3: Dynamic Social And Ads Action Plan

**Purpose:** replace static paragraphs with actionable, editable plan items.

### Backend

- [ ] Add `generate_marketing_action_plan(...)`.
- [ ] Input:
  - Suite profile.
  - Marketing intelligence.
  - Strategy deck.
  - Planning inputs from the user.
- [ ] Generate:
  - `social_items[]`
  - `ad_funnel_items[]`
  - `planning_questions[]`
  - `warnings[]`
- [ ] Validate:
  - Social plan has a balanced 70/20/10 content mix.
  - Paid plan covers Awareness, Consideration, Conversion, Loyalty, Ambassador.
  - Every item has `required_assets`, `output_types`, and `status`.
- [ ] Add endpoints:
  - `POST /api/v1/suites/{suite_id}/marketing-plan/generate-action-plan`
  - `PATCH /api/v1/suites/{suite_id}/marketing-plan/actions/{item_id}`

### Frontend

- [ ] Social Plan:
  - Calendar/list hybrid.
  - Editable item cards.
  - Filters by status, output type, channel, objective.
- [ ] Ads Funnel:
  - Funnel columns/cards.
  - Editable campaign/action cards.
- [ ] Each item shows:
  - Generate now if possible.
  - Upload required asset if blocked.
  - Edit details.
  - Schedule later.

### Verification

- [ ] Tests for required item fields.
- [ ] Frontend build.
- [ ] Manual QA: edit item, refresh page, edit persists.

---

## Slice 4: Apply Workspace

**Purpose:** move execution into a dedicated flow after the user chooses scope.

### Backend

- [ ] Add `marketing_application_runs` object in Suite strategy.
- [ ] Add endpoint:
  - `POST /api/v1/suites/{suite_id}/marketing-plan/apply`
- [ ] Scope:
  - `full`
  - `social`
  - `ads`
- [ ] Run object includes:
  - Scope.
  - Created time.
  - Item IDs included.
  - Progress.
  - Missing asset count.
  - Generated post IDs.

### Frontend

- [ ] Add Apply section with three CTAs:
  - Apply full plan.
  - Apply social media plan.
  - Apply ads plan.
- [ ] Create route:
  - `/suite/[id]/marketing-plan/apply/[runId]`
- [ ] Workspace:
  - Left/progress panel on desktop.
  - Center calendar/funnel based on scope.
  - Right selected-item detail panel.
  - Mobile bottom-sheet details.
- [ ] Item actions:
  - Generate.
  - Upload assets.
  - Edit.
  - Schedule.
  - Mark manual/ready.

### Verification

- [ ] Route opens for each scope.
- [ ] Owner controls hidden on public share page.
- [ ] Disabled generate state explains missing assets.

---

## Slice 5: One-Item Generation Bridge

**Purpose:** connect action items to existing Create & Generate.

### Backend

- [ ] Add endpoint:
  - `POST /api/v1/suites/{suite_id}/marketing-plan/actions/{item_id}/generate`
- [ ] Convert item fields into generation job payload:
  - Prompt.
  - Brand usage.
  - Output type.
  - Required size.
  - Reference assets.
  - Campaign/social metadata.
- [ ] Save generated post IDs back to the item.
- [ ] Reuse existing generation queue and media status.

### Frontend

- [ ] Generate button triggers item generation.
- [ ] Show queued/generating/generated status.
- [ ] Link generated output into Recent Content.
- [ ] Allow generated output approval/rejection through existing post lifecycle.

### Verification

- [ ] Unit test payload conversion.
- [ ] Manual QA with one social item and one ads item.

---

## Slice 6: Production QA

- [ ] Arabic RTL mobile.
- [ ] English LTR desktop.
- [ ] Public shared link.
- [ ] Empty source warnings.
- [ ] AI provider failure/queue state.
- [ ] Apply social-only flow.
- [ ] Apply ads-only flow.
- [ ] One-item generation.
- [ ] Print/download still works.

## Done Definition

This feature is production-ready when:

- The user can understand the market before seeing the plan.
- The user can edit plan items.
- The user can choose full/social/ads application.
- The Apply Workspace clearly shows what OneShare can generate and what needs client assets.
- A single action item can generate real content through the existing generation system.
- Public share remains polished and safe.
- Failures show useful reasons, not empty cards.
