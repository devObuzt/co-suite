# Marketing Plan Execution Workspace Design

## Goal

Turn the OneShare marketing plan from a static presentation into a clear decision-and-execution workspace:

- First show market understanding: competitors, source links, demand, supply, channel opportunities.
- Then show an editable strategy and monthly action plan.
- Then let the user apply the full plan, only the social plan, or only the ads plan.
- Move execution into a focused workspace where every recommended content/campaign item can be generated, edited, scheduled, uploaded, or marked as requiring client assets.

This is the recommended Option 2: separate `Market Intelligence`, `Strategy`, and `Apply Workspace` instead of crowding the current plan page.

## Why This Matters

The current plan proves the system can generate a deck, but the user experience still feels like a report. A business owner needs to understand:

1. Why OneShare recommends this direction.
2. Who the competitors are and where they were found.
3. Where demand exists: Google search, social media, seasonal events, local market, or platform trends.
4. What exactly will be created.
5. What OneShare can generate alone and what requires client input.
6. How to approve and run the plan without reading a long PDF.

The product should earn trust before asking the user to click Generate.

## Product Structure

### 1. Market Intelligence

Purpose: show the research basis before showing recommendations.

Sections:

- Competitors
  - Tabs or filters: Google, Instagram, Facebook, TikTok, Website, Other.
  - Each competitor card includes:
    - Name.
    - Source platform.
    - Public URL.
    - Why it is relevant.
    - Detected category/offer.
    - Evidence snippet or source note.
    - Suggested threat/opportunity.
    - Confidence: high, medium, low.
  - Empty states explain which source failed or is unavailable.

- Demand and Supply
  - Google search intent signals.
  - Social demand signals: hashtags, pages, content themes, visible engagement where available.
  - Local demand: country/city/language signals from the Suite profile.
  - Seasonal/religious/local events relevant to the audience.
  - Supply density: where competitors are active and where they are weak.

- Opportunities
  - Concrete opportunity cards, for example:
    - High-search/low-content gap.
    - Weak competitor creative quality.
    - Underserved language.
    - Seasonal campaign window.
    - Product/service with strong intent but weak social proof.

### 2. Strategy Deck

Purpose: keep the polished client-facing plan.

The existing deck remains, but sections become editable and more tightly connected to the research:

- Executive summary.
- Current situation.
- Digital asset audit.
- Market demand and opportunity.
- Competitor landscape.
- Target audience.
- Positioning and message.
- Channel strategy.
- Content strategy.
- Campaign ideas.
- Action plan.
- KPIs.
- Budget direction.
- Next steps.

Each section should show source references where relevant. The user can edit section text; edits are saved as Suite learning logs.

### 3. Dynamic Action Plan

Purpose: convert strategy into executable items.

The action plan splits into two product surfaces:

- Social Plan
  - Monthly calendar view.
  - Content items grouped by date/week.
  - Each item includes:
    - Title.
    - Objective: attraction, trust, sales.
    - Channel: Instagram, Facebook, TikTok, LinkedIn, website, WhatsApp, etc.
    - Placement: post, reel, story, carousel, ad creative, blog, landing snippet.
    - Suggested output types: image, video, carousel, story, copy-only, mixed.
    - Required assets.
    - Generation prompt.
    - Editable caption/hook.
    - Status.

- Paid Funnel Plan
  - Funnel board:
    - Awareness.
    - Consideration.
    - Conversion.
    - Loyalty.
    - Ambassador.
  - Each funnel card includes:
    - Campaign idea.
    - Target audience.
    - Channel: Meta, Google, TikTok, etc.
    - Creative outputs needed.
    - Landing/WhatsApp/direct action.
    - Budget direction.
    - Required assets.
    - Generation status.

### 4. Apply Workspace

Purpose: after the user chooses what to apply, move them into an execution-first screen.

Entry CTAs:

- Apply full plan.
- Apply social media plan only.
- Apply ads plan only.

Workspace layout:

- Left rail: scope, progress, missing assets, warnings.
- Center:
  - Social scope: calendar.
  - Ads scope: funnel board.
  - Full scope: split social calendar + paid funnel board.
- Right detail panel:
  - Selected item details.
  - Editable prompt.
  - Output settings.
  - Asset requirements.
  - Upload area.
  - Generate button.
  - Schedule button.
  - Mark as ready/manual button.
  - Change log.

Mobile layout:

- Top segmented scope switcher.
- One active item list at a time.
- Detail panel opens as a bottom sheet.
- Primary action sticks to the bottom.
- Research details collapse into cards.

## Item States

Every content/campaign item needs a truthful lifecycle:

- `draft`: AI suggested the item, user has not reviewed.
- `edited`: user changed the item.
- `needs_assets`: OneShare cannot generate until the user uploads something.
- `ready_to_generate`: enough inputs exist.
- `queued`: generation requested.
- `generating`: worker is processing.
- `generated`: output exists.
- `needs_review`: output ready for approval.
- `approved`: user approved.
- `scheduled`: attached to a calendar/publish time.
- `published`: published or marked as used.
- `failed`: generation/application failed with reason.

## Required Asset Logic

Each action item must declare what it needs:

- `none`: OneShare can generate directly.
- `logo`: use Suite default logo or ask for upload.
- `brand_assets`: colors/fonts/logos are needed.
- `product_photos`: user should upload product images.
- `human_video`: user should upload talking-head or store video.
- `store_photos`: user should upload place/team photos.
- `offer_details`: user must confirm price, promotion, deadline, terms.
- `landing_url`: user must provide destination URL.
- `approval_only`: content already exists; user just approves/schedules.

The UI should never hide why a Generate button is disabled.

## AI Generation Architecture

Avoid one giant JSON prompt. Generate and validate independently:

1. `market_intelligence`
   - Competitors.
   - Source links.
   - Demand/supply signals.
   - Opportunities.

2. `strategy_deck`
   - Narrative client-facing plan.
   - Uses market intelligence as input.

3. `social_action_plan`
   - Calendar-ready social content items.
   - 70/20/10: attraction, trust, sales.

4. `paid_funnel_plan`
   - Funnel-ready campaign items.
   - Awareness to Ambassador.

5. `action_item_generation`
   - Generates assets for selected plan items.
   - Uses existing Create & Generate capabilities.

Claude remains the primary reasoning model for market/strategy/action planning. Image/video generation remains routed through the current media generation providers and model policy.

## Data Contract

For the next production slice, store under `suite.strategy` to avoid a migration unless the object becomes too large:

```json
{
  "marketing_plan_deck": {
    "version": "marketing_plan_deck_v1",
    "status": "ready",
    "sections": []
  },
  "marketing_intelligence": {
    "version": "marketing_intelligence_v1",
    "generated_at": "...",
    "competitors": [],
    "demand_signals": [],
    "supply_signals": [],
    "opportunities": [],
    "source_links": [],
    "warnings": []
  },
  "marketing_action_plan": {
    "version": "marketing_action_plan_v1",
    "generated_at": "...",
    "social_items": [],
    "ad_funnel_items": [],
    "planning_questions": [],
    "warnings": []
  },
  "marketing_application_runs": []
}
```

Recommended item shape:

```json
{
  "id": "item_...",
  "plan_type": "social",
  "title": "...",
  "objective": "attraction",
  "channel": "instagram",
  "placement": "reel",
  "output_types": ["video", "story"],
  "schedule_window": "2026-07-03",
  "funnel_stage": null,
  "required_assets": ["product_photos"],
  "generation_prompt": "...",
  "caption": "...",
  "hook": "...",
  "source_references": [],
  "status": "needs_assets",
  "user_edits": [],
  "generated_post_ids": []
}
```

## API Shape

Authenticated:

- `GET /api/v1/suites/{suite_id}/marketing-plan`
  - Returns deck, intelligence, action plan, latest jobs.

- `POST /api/v1/suites/{suite_id}/marketing-plan/generate-intelligence`
  - Creates/queues market intelligence.

- `POST /api/v1/suites/{suite_id}/marketing-plan/generate-action-plan`
  - Creates/queues social + ads executable plan.

- `PATCH /api/v1/suites/{suite_id}/marketing-plan/actions/{item_id}`
  - Saves user edits.

- `POST /api/v1/suites/{suite_id}/marketing-plan/apply`
  - Body: `{ "scope": "full" | "social" | "ads" }`.
  - Creates application run.

- `POST /api/v1/suites/{suite_id}/marketing-plan/actions/{item_id}/generate`
  - Converts one action item into content generation jobs.

- `POST /api/v1/suites/{suite_id}/marketing-plan/actions/{item_id}/assets`
  - Uploads required assets for that item.

Public share:

- Keep current shared deck route, but shared pages should initially show read-only research and strategy. Execution controls remain owner-only.

## UI Principles

- Show research before recommendations.
- Show only the next useful action.
- Keep the plan editable but avoid turning the page into a spreadsheet.
- Put the heavy execution UI in a dedicated Apply Workspace.
- On mobile, avoid side-by-side panes; use tabs, sheets, and sticky actions.
- Always explain missing data, failed sources, and disabled buttons.
- Keep Arabic/Hebrew RTL clean with `dir="auto"` for mixed platform names and URLs.

## Acceptance Criteria

The first implementation slice is accepted when:

- The marketing plan page has clear tabs/sections for Market, Strategy, Social Plan, Ads Funnel, and Apply.
- Competitors can be shown as separate cards with source links and platform labels.
- Demand/supply appears as a separate readable section.
- Social and ads plans are represented as editable action items, not static paragraphs.
- The user can choose Apply full, Apply social only, or Apply ads only.
- The Apply Workspace opens with the correct scope.
- Every action item shows whether it can be generated now or needs user assets.
- Disabled generation states explain exactly what is missing.
- The public share page does not expose owner execution controls.

## Non-Goals For First Slice

- Fully automated publishing of the entire plan.
- Budget spend controls for live Meta/Google campaigns.
- Perfect external competitor scraping from every platform.
- Multiple plan versions.
- Collaborative comments.

## Implementation Recommendation

Build in four slices:

1. Data contract + UI skeleton.
2. Competitor/demand intelligence generation and rendering.
3. Dynamic social/ad action plan rendering and editing.
4. Apply Workspace and one-item generation flow.

This keeps the product moving while protecting the current working marketing plan page.
