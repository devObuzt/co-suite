# OneShare/Cosuite Agent Rules

## QA Is Required

Use the `cosuite-qa` skill for every user-facing or operational change before calling work complete. This includes UI, API, auth, admin, billing, generation, external providers, mobile layout, navigation, persistence, deploy, and bug fixes.

Passing tests is not enough by itself. Verify the relevant end-user or admin workflow, confirm persistence after refresh or re-fetch, and report exactly what was checked.

For production-only providers such as Google Ads, SerpAPI, OpenAI, Claude, or Meta, verify local fallback/diagnostic behavior and state the exact production/Railway check required when live credentials are unavailable locally.
