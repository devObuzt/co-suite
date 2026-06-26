# Marketing Plan Compact UI Design

## Goal

Improve the Suite marketing plan page so each stage card is compact by default, exposes a clear detail-page icon in the card header, and adds restrained color cues without making the page visually noisy.

## Scope

- Update the marketing plan stage cards on the main marketing plan page.
- Keep detail pages expanded.
- Preserve current API behavior and generated data.
- Keep mobile and RTL layouts stable.

## Design

- Stage cards remain full-width cards, but their default content becomes a preview.
- Services/products show the first 3 items on the main page, with a clear show-more control for the rest.
- Keywords show two compact rows on the main page, with existing expand/collapse behavior.
- Competitors show only the first populated source section on the main page, with an explicit show-more control for remaining sources.
- Demand/supply stays summary-first on the main page; detail pages keep the full table.
- The detail-page link is an icon button in the stage header, not a full-width button inside the card body.
- Each stage receives a subtle tone through icon background, soft border, and light inner accent. Colors are restrained and distinct.

## QA

- Run TypeScript/build checks.
- Verify the page compiles.
- Verify mobile viewport does not introduce horizontal page overflow.
- Verify detail pages still show full content.
