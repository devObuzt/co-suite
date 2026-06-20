# Marketing Plan Studio Design

## Goal
Build a trust-building, client-facing marketing plan experience inside OneShare: a polished web plan that can be generated from a Suite, shared by link with an optional password, and downloaded as PDF.

## Product Shape
The feature is not a static PDF generator. It is a live strategy presentation page that resembles the attached marketing-plan references: strong cover, business imagery, brand color, bilingual/RTL-ready text, structured sections, and a premium agency feel.

The first production MVP includes:
- Generate or refresh a plan from an existing Suite.
- Save the generated plan in the Suite strategy JSON.
- Render an interactive internal page under the Suite.
- Create a public share link with an optional password.
- Export/download through browser print-to-PDF in the first version.
- Use Claude for strategic analysis and writing.
- Use existing source links, brand profile, strategy, competitors, ads/analytics data, and scraped source summaries where available.

## Plan Content
Each generated plan contains these sections:
1. Cover: business name, category, location, year, cover image, services/market chips.
2. Executive summary: what the business needs, what OneShare found, recommended direction.
3. Current situation: status of brand, website/social links, content, ads, and business assets.
4. Market and demand: audience demand, offer strength, gaps, seasonal or local opportunities.
5. Competitor landscape: competitors, channels, positioning, content patterns, possible gaps.
6. Audience and personas: segments, languages, pain points, purchase triggers.
7. Positioning: USP, ESP, marketing message, proof points.
8. Channel strategy: organic social, Meta Ads, Google Ads, website/SEO, WhatsApp or direct leads when relevant.
9. Content strategy: pillars, formats, hooks, examples, cadence.
10. Campaign ideas: 3-5 concrete campaign concepts with goal, audience, channels, creative angle.
11. 30/60/90 day action plan.
12. KPI dashboard: what to measure and why.
13. Budget recommendation: starter, growth, aggressive ranges where enough information exists.
14. Next steps: what the client should approve or prepare.

## Data Inputs
The generator reads:
- `Suite.brand`: name, category, services/products, locations, audience, links, logos, colors, personas, content rules.
- `Suite.strategy`: current marketing plan and message if already generated.
- `Suite.connections`: Meta, Google, and storage readiness when available.
- Existing analytics/campaign endpoints for current performance snapshots.
- Existing scraper/search services for source links and competitor/market research.

## AI Policy
Claude is the primary model for marketing-plan analysis and narrative writing. The plan generator should use the existing provider-neutral `call_text_ai` client with `provider="anthropic"`. If Claude fails because of transient provider limits, return a queued/failed state with actionable details instead of a blank plan. OpenAI can remain a fallback for JSON repair if needed, but the strategic voice comes from Claude.

## Storage Model
For MVP, store the output under `suite.strategy["marketing_plan_deck"]`. The object contains:
- `version`: `marketing_plan_deck_v1`
- `language`
- `status`: `ready`, `failed`, or `draft`
- `generated_at`
- `cover`
- `sections[]`
- `research_summary`
- `share`: `{ enabled, token, password_hash, created_at }`

This avoids a migration for the first version while keeping a clear upgrade path to a `marketing_plans` table when version history, multiple plans, or analytics become necessary.

## Routes
Authenticated app routes:
- `GET /suites/{suite_id}/marketing-plan`
- `POST /suites/{suite_id}/marketing-plan/generate`
- `POST /suites/{suite_id}/marketing-plan/share`

Public route:
- `GET /marketing-plans/share/{token}`
- `POST /marketing-plans/share/{token}/unlock`

Web routes:
- `/suite/[id]/marketing-plan`
- `/marketing-plans/share/[token]`

## UI
Internal Suite page:
- Hero cover with business title, generated date, plan language, and actions.
- Action bar: Generate/Refresh, Share, Set password, Copy link, Download PDF.
- Section navigation on desktop; compact jump menu on mobile.
- Plan sections rendered as cards/sections with large headings and short, scannable paragraphs.
- RTL support for Arabic/Hebrew.

Public share page:
- Password gate if password exists.
- Same plan renderer after unlock.
- No owner controls.
- OneShare branding in footer.

## PDF Export
MVP uses browser print CSS and `window.print()` from the web plan page. Print styles hide controls and preserve section breaks. Backend PDF rendering is deferred until the plan page stabilizes.

## Error Handling
- If generation fails: show provider message, source stage, and retry action.
- If plan has no enough data: generate a lighter plan and flag missing inputs.
- If shared link token is invalid: show a branded not-found page.
- If password is wrong: show retry without leaking whether token exists.

## Testing
- API tests for generating, saving, sharing, password unlock, and invalid token behavior.
- Unit tests for normalizing plan JSON.
- Next build verification.
- Manual QA on Arabic RTL and English LTR plan pages.

## Non-MVP
- Multiple saved plan versions.
- Backend-rendered PDF with pixel-perfect pagination.
- Collaborative comments on plan sections.
- Plan view analytics.
- AI-generated custom cover images for every plan.
