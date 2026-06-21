# Marketing Plan Execution Workspace Feature Brief

## Owner Direction

The owner selected Option 2: separate the marketing plan into:

1. Market Intelligence.
2. Strategy Deck.
3. Apply Workspace.

The experience must be clear, simple, and practical for business owners. The product should not just generate content ideas; it should show competitor research, demand/supply signals, and then convert the plan into executable social and paid campaign actions.

## Department Handoff

### Product Manager

Define the user journey:

- User generates or opens a marketing plan.
- User first sees research: competitors, links, demand, supply, opportunities.
- User reviews/edit strategy.
- User reviews/edit social and paid action items.
- User chooses:
  - Apply full plan.
  - Apply only social plan.
  - Apply only ads plan.
- User lands in Apply Workspace to generate, upload, schedule, or mark items ready.

### Architecture

Review the data contract in:

- `docs/superpowers/specs/2026-06-21-marketing-plan-execution-workspace-design.md`

Main decision:

- First slice can remain in `Suite.strategy`.
- Watch object size and query needs.
- If versioning/history becomes necessary, move to dedicated tables later.

### Design

Design must keep the plan premium but execution-friendly:

- Research cards should be compact and evidence-led.
- Strategy remains polished.
- Action plan cards must be operational, not report-like.
- Mobile should show one active panel at a time with sticky actions.

### Developers Manager

Use the implementation plan:

- `docs/superpowers/plans/2026-06-21-marketing-plan-execution-workspace.md`

Recommended first development slice:

1. Data types.
2. UI shell tabs.
3. Safe fallback intelligence/action-plan rendering.
4. No external scraping changes yet.

### Developers

Do not replace the current plan page in one pass. Preserve:

- Existing deck.
- Share link.
- Password protection.
- PDF/print.
- Generation job status.

### QA

Build QA around:

- Arabic RTL mobile.
- Public share without execution controls.
- Empty/failing competitor sources.
- Disabled Generate state with missing asset explanation.
- Apply full/social/ads scope.

## Immediate Next Step

Start Slice 1 only:

- Extend API/frontend types.
- Add Market/Strategy/Social Plan/Ads Funnel/Apply shell.
- Render existing deck inside Strategy.
- Use fallback/sample structures only when data does not exist.

No AI prompt overhaul should happen before the UI/data contract is stable.
