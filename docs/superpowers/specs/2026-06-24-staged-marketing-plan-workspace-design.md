# Staged Marketing Plan Workspace Design

## Goal
Rebuild the marketing plan experience as independent stages instead of one long plan job, starting with services/products, keywords, competitors, and demand/supply.

## Stages
1. Services/products: always available and backed by the Suite brand profile. Add, edit, and delete operations update `suite.brand.services` immediately.
2. Keywords: locked until generated. `Generate` creates the first keyword set from Suite category, services/products, location, and audience language. `Generate More` appends new non-duplicate keywords.
3. Competitors: locked until generated. The first version uses final-shape mock competitor cards with source types such as Google organic, sponsored, Instagram, Maps, Facebook, and TikTok. `Generate More` appends additional non-duplicate mock cards. Later SerpAPI can replace the source without changing the UI contract.
4. Demand/supply: locked until generated. The first version uses current fallback demand, supply, and opportunity signals. Later Google Ads data can replace the source.

## Actions
`Regenerate` is intentionally out of scope for this slice. Each generated stage supports:
- `Generate`: first run for a locked stage.
- `Generate More`: append more results for the same topic without duplicating existing entries.

## UI Contract
The main marketing plan page shows each stage as a separate box. Each box has a details icon that opens a stage page:
- `/suite/[id]/marketing-plan/services`
- `/suite/[id]/marketing-plan/keywords`
- `/suite/[id]/marketing-plan/competitors`
- `/suite/[id]/marketing-plan/demand-supply`

The first version may reuse the same stage widget on both the main page and detail pages.

## Competitor Card Contract
Each competitor card includes source type, source icon, title/name, snippet/description, short URL, open-in-new-tab, copy, preview popover, and multi-select labels:
- not_competitor
- good_competitor
- local_competitor
- global_competitor

Classification changes are persisted inside `suite.strategy.marketing_intelligence.competitors`.

## Backend Contract
The backend stores staged outputs inside `suite.strategy.marketing_intelligence`:
- `keywords`: keyword objects with `id`, `text`, `intent`, `source`, and `confidence`.
- `competitors`: competitor objects with source metadata and classification tags.
- demand/supply/opportunities: existing normalized signal arrays.

Services/products remain in `suite.brand.services`.

## Constraints
- No token charging in this slice.
- No global marketing plan progress bar for stage actions.
- Stage actions must be immediate or stage-local; they must not reuse the full strategic plan job state.
- UI copy follows the active user language.
- SerpAPI is not implemented in this slice, but competitor data shape must be ready for it.
