# OneShare Owner Review - Marketing Plan, Work Plan, and Quick Create

Date: 2026-06-20 20:05 London time

## What Changed

- Quick Post/Ad now respects the selected output type more correctly.
- When the user selects `Mix`, the backend requests a mixed generation set instead of silently producing only one image.
- The mixed plan is distributed into image, carousel, and video ideas.
- This behavior works both inside a suite and from account-level create paths.

## Marketing Plan Upgrade

- The marketing plan generator now asks Claude for a monthly social media work plan.
- The plan includes client focus questions before applying the month.
- The plan checks audience, country, religions, culture, holidays, and seasonal moments.
- The social plan follows the requested split:
  - 70% attraction and attention
  - 20% trust building
  - 10% sales
- Each work-plan item includes recommended output format and production mode, such as image, carousel, reel, story, AI video, UGC, store footage, talking-head video, or uploaded asset.
- The plan now includes a paid marketing funnel:
  - Awareness
  - Consideration
  - Conversion
  - Loyalty
  - Ambassador
- Each funnel idea also includes a generation request so it can be turned into content from the plan view.

## Plan UI

- The marketing plan page now accepts near-term focus, upcoming campaigns, and planning notes before generation.
- The plan view renders a monthly social work-plan section and a paid-funnel section.
- Individual plan items and funnel ideas can start generation directly from the plan page.
- Static plan labels now localize into Arabic, Hebrew, or English based on the plan language.
- PDF export remains available through print/export behavior, and share-page support remains in place.

## Suite Learning Logs

- Content generation prompts are now appended to suite brand learning logs.
- Post text edits are logged with before/after values.
- Rejection feedback and regeneration feedback are logged.
- These logs are stored in the suite brand profile so later logic can learn preferences such as word replacements, tone rules, and repeated client edits.

## Verification

- Backend tests passed:
  - `tests/test_suite_memory_media_contracts.py`
  - `tests/test_marketing_plan_generator.py`
  - `tests/test_quick_generation_options.py`
  - `tests/test_social_content_plan.py`
- Result: 30 passed.
- Web production build passed with `npm run build`.

## Production Readiness

Ready for next QA slice:

- Quick Post/Ad output selection logic is code-ready and covered by tests.
- Marketing plan data generation is code-ready and covered by tests.
- Marketing plan UI builds successfully.
- Learning logs are implemented at the suite profile data level.

Not fully production-complete yet:

- Bulk-select multiple plan items and generate them together is not implemented yet.
- Upload-ready-video/file from a plan item is not fully implemented yet.
- Applying an entire monthly plan into scheduling/publishing automation still needs a dedicated workflow.
- Browser QA against the live authenticated app still needs to be run after deployment.

## Recommended Next Step

Run a live suite QA path:

1. Generate a marketing plan in Arabic and Hebrew.
2. Confirm the monthly work plan appears.
3. Generate one plan item from the plan page.
4. Generate one funnel idea.
5. Confirm the created content appears in recent content.
6. Confirm logs appear in the suite brand profile payload.
7. Add bulk generation and apply-plan workflow after this smoke test is stable.
