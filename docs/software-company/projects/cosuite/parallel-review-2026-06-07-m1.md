# M1 Parallel Review - Architecture, Design, QA, Developers Manager

Date: 2026-06-07  
Owner: Project Management - Layla Haddad  
Status: completed  

## Purpose

Run the next recommended M1 steps in parallel:

- Architecture re-check by Mira Cohen.
- UX/mobile/RTL/theme review by Noa Barak.
- QA smoke planning by Lina Saad.
- Developers Manager sequencing by Daniel Farah.

No code was changed during this review.

## Executive Decision

M1 should continue in stabilization mode.

Do not start broad new feature work yet. The next work should be three focused passes:

1. Backend lifecycle durability fix pass.
2. M1 design hardening pass.
3. P0 smoke preparation and execution against a named target.

`DEV-D-01` limited account-level generation without Suite remains the first new feature-coding task, but it should not distract from the lifecycle/design fixes required before full QA confidence.

## Architecture - Mira Cohen

### Accepted For M1

- Suite Memory v0 read contract is acceptable for M1.
- Generation job status serialization is acceptable for M1 visibility.
- Media readiness contract is acceptable.
- Publishing preflight direction is acceptable.

### Required Before Release Candidate

- Persist reject reason/free-text in backend metadata or lifecycle field.
- Do not delete original content before regeneration succeeds.
- Persist publish attempt metadata for full failure, not only success/partial success.
- Define merge semantics for `/suites/{suite_id}/brand`; avoid accidental full JSON replacement.
- Either route generation through Suite Memory v0 or document that v0 is UI/read-only for M1.

### Accepted Risk Candidate

FastAPI `BackgroundTasks` is not production-grade. M1 may continue only if Product/DevOps explicitly accept stale/lost-job risk until durable queue work.

## Design - Noa Barak

### Acceptable For M1

- Core suite reachability mostly exists on desktop and mobile.
- Brand/Profile editability, `Use brand` gating, Content `All`, reject reason UI, readiness cards, and analytics notices are materially improved.
- `dir="auto"` usage is good enough for mixed Arabic/Hebrew/English content in M1.

### Top UX Blockers

- Theme consistency is not smoke-ready on dark-only surfaces.
- Native-language coverage is incomplete across Suite shell, Create, Content, Profile, Connections, Analytics, and Product Bulk.
- Product Bulk rejection is inconsistent because it does not require feedback.
- Create and Content share the same `ContentTab`; acceptable for M1 only if QA treats this as intentional.

### Recommended Design Pass

- Tokenize remaining dark-only surfaces.
- Add i18n keys for suite navigation and shell basics.
- Require Product Bulk reject feedback or relabel rejection.
- Add compact output-language summary/control near Create prompt.
- Run mobile 320/360, desktop, light/dark, Arabic/Hebrew/English smoke.

## QA - Lina Saad

### P0 Smoke Order

1. Build/runtime entry smoke.
2. Auth and Suite access.
3. Onboarding and profile persistence.
4. Create & Generate visibility.
5. Content review lifecycle.
6. Truthful readiness states.
7. Mobile core journey.
8. Publishing/media preflight after Architecture review.

### Blocked Or Conditional

- Meta/Google connected-provider checks require credentials.
- Full AI happy path requires provider keys and limit posture.
- Durable media/publishable URL checks require R2 readiness.
- External publishing requires sandbox accounts or explicit approval.
- `DEV-D-01` and `DEV-F-01` are currently not started; smoke records them as blocked if absent.

### QA Gate

Block M1 if signup/login, Suite access, data save, generation visibility, content review, mobile navigation, or media truthfulness fails. Block if missing config appears as success, raw error, or misleading all-zero analytics.

## Developers Manager - Daniel Farah

### Review First

Review `DEV-E-01` publishing preflight and partial publish state first.

### First New Coding Task

Start `DEV-D-01` limited account-level generation without Suite.

Acceptance:

- Logged-in no-Suite user can create prompt-driven Quick Post/Ad.
- `Use brand` is unavailable/off.
- Suite-only promises are absent.
- queued/running/failed/completed states are visible.
- media/error states match Suite behavior.
- clear upgrade path to create a Suite exists.

### Do Not Start Yet

- Durable queue/worker implementation unless Architecture/DevOps reject M1 accepted-risk posture.
- Product Bulk stabilization.
- Campaign builder.
- Native apps.
- Billing/Morning webhook.
- SEO/mobile-app future work.
- Full localization redesign.

## Consolidated Next Actions

1. Developers: implement lifecycle durability fixes:
   - reject reason persistence.
   - safe regeneration preservation.
   - failed publish metadata.
   - Suite brand merge semantics.
2. Design/Developers: run M1 design hardening:
   - theme token pass.
   - suite shell/nav i18n.
   - Product Bulk reject feedback consistency.
3. Developers: start `DEV-D-01` after or alongside the fix pass if file ownership stays separate.
4. QA: prepare P0 smoke data and run unblocked smoke against a named local/staging target.
5. DevOps/Product: provide or explicitly mark blocked:
   - AI provider key/limit readiness.
   - R2 public media readiness.
   - Meta/Google test credentials.
   - safe publishing target.

