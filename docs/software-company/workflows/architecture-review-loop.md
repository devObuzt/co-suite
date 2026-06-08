# Architecture Review Loop

## Purpose

Ensure implementation stays aligned with intended architecture and remains scalable as the product grows.

## When Required

Run this loop for changes touching:

- Suite Memory.
- onboarding intelligence.
- AI generation.
- queue/jobs/workers.
- billing/credits/marketing budget.
- platform integrations.
- analytics.
- publishing/scheduling.
- product bulk.
- storage/media.
- security-sensitive data.

## Review Pass 1: Before Implementation

Architecture defines:

- expected boundaries.
- data contracts.
- provider contracts.
- queue/job requirements.
- scaling assumptions.
- security concerns.
- migration/deployment risks.

## Review Pass 2: After Implementation

Architecture compares:

- planned architecture.
- actual implementation.
- skipped requirements.
- new coupling.
- missing observability.
- sync work that should be async.
- data model drift.
- provider/billing/security risks.

## Outputs

- update `registers/architecture-review-log.md`.
- update `registers/architecture-drift-register.md`.
- mark each drift item as:
  - `fix_now`
  - `track_debt`
  - `accepted_risk`
  - `not_an_issue`

