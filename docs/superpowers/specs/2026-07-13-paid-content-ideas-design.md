# Paid Content Ideas Design

## Goal

Make the paid-marketing work plan behave like the social-ideas gallery while preserving the paid funnel stages: Awareness, Consideration, Conversion, Loyalty, and Advocacy.

## User Experience

- Each funnel stage remains a separate section.
- Each section presents selectable idea cards.
- A card shows only the idea title, a concise description, the recommended format, the channel, and the provider.
- Recommended formats are video, image/banner, carousel, or AI video.
- Full ad copy, hooks, CTA text, production prompts, and asset requirements are not generated or displayed at this planning step.
- The user selects one idea per stage and saves the selection using the existing persistence flow.

## Data Contract

Each paid idea returns `title`, `description`, `recommended_format`, `channel`, `provider`, `stage`, and the existing stage metadata. Legacy `ad_format` remains accepted when reading older saved plans, but newly generated plans use the concise fields.

## Generation

OpenAI and Claude each return one concise idea per stage, producing two choices per stage. The prompt explicitly forbids full copy, scripts, hooks, CTAs, or detailed execution instructions. Fallback ideas follow the same concise contract and audience language.

## Compatibility And Persistence

Existing saved plans continue to render by deriving the description from `description`, `visual_idea`, or `rationale`, and the format from `recommended_format` or `ad_format`. The existing selection endpoint remains unchanged, so selected IDs continue to persist after reload.

## Verification

- Unit-test the concise prompt and normalization contract.
- Verify both AI batches produce two ideas per stage.
- Build and lint the work-plan page.
- In a browser, generate or load the paid plan, select one idea per stage, save, reload, and confirm the selections remain.
- Check the paid plan at a 390px mobile viewport for clipping or horizontal page drift.
