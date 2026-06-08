# co-Suite M1 Implementation Slice 01

Date: 2026-06-07  
Owner: Developers Manager  
Status: ready_for_developer_handoff  
Milestone: M1 - Production Stabilization  

## 1. Implementation Slice 01 Goal

Make the core Suite path truthful and reachable before deeper feature work starts:

- Generation actions always expose a visible job state and failure reason.
- Generated content exposes media readiness instead of blank or misleading media cards.
- Suite-level navigation is reachable on mobile.
- Brand/Profile becomes minimally editable after onboarding for the M1 Suite Memory fields.
- Connections, Create & Generate, Brand/Profile, Content Review, and Analytics are reachable enough for the first QA smoke pass.

This slice should be small enough for immediate coding, but it crosses backend and frontend where the current product can otherwise appear broken even when services are partially working.

## 2. Why This Slice Comes First

Slice 01 comes before Product Bulk expansion, campaign builder work, publishing expansion, and mobile app work because it removes the highest cross-cutting release blockers:

- Product requires users to understand queued/running/failed/completed generation states and missing media states.
- Architecture flags generation jobs, media artifact state, and Suite Memory divergence as high M1 risks.
- DevOps flags AI keys, R2 readiness, and process-local background tasks as production risks that need clear user/admin visibility.
- Design flags mobile Suite navigation and Brand/Profile editability as must-fix user blockers.
- QA has open high/critical findings for AI runtime config, media storage, generation job visibility, connections/analytics truthfulness, and mobile/RTL usability.

The slice intentionally prioritizes truthfulness and recoverability over broad feature coverage.

## 3. Task List Ordered By Dependency

| Order | Task ID | Task | Primary Dependency |
| ---: | --- | --- | --- |
| 1 | DEV-M1-S01-T01 | Define and implement Suite Memory v0 read contract for M1 fields. | Existing `Suite.brand`, `Suite.strategy`, `Suite.connections` JSON |
| 2 | DEV-M1-S01-T02 | Add generation job status normalization and stale/failure visibility for content generation entry points. | T01 for brand-readiness and generation context |
| 3 | DEV-M1-S01-T03 | Add media readiness metadata to generated content responses. | T02 for generation failure/status semantics |
| 4 | DEV-M1-S01-T04 | Update Create & Generate and Content Review UI to show job/media states and reject-with-reason flow. | T02, T03 |
| 5 | DEV-M1-S01-T05 | Add mobile Suite navigation exposing required M1 Suite screens. | Existing Suite routes |
| 6 | DEV-M1-S01-T06 | Add minimum editable Brand/Profile sections backed by Suite Memory v0 merge rules. | T01 |
| 7 | DEV-M1-S01-T07 | Make Connections and Analytics states explicit enough for smoke testing without credentials. | T01, existing connection/status endpoints |

## 4. Proposed Developer Ownership Areas / File Areas

| Task ID | Proposed Owner Area | Likely File Areas |
| --- | --- | --- |
| DEV-M1-S01-T01 | Backend Platform / Suite Memory | `api/models/suite.py`, `api/routers/suites.py`, `api/routers/onboarding.py`, new or existing Suite context helper under `api/services/` |
| DEV-M1-S01-T02 | Backend Generation | `api/services/generation_jobs.py`, `api/routers/content.py`, `api/routers/product_bulk.py` only for shared status behavior if already touched safely |
| DEV-M1-S01-T03 | Backend Content / Media | `api/services/media_storage.py`, `api/routers/content.py`, content serialization helpers/models |
| DEV-M1-S01-T04 | Frontend Create / Review | `web/src/app/suite/[id]/create/*`, `web/src/app/suite/[id]/content/*`, shared content card/components where used |
| DEV-M1-S01-T05 | Frontend App Shell / Navigation | `web/src/app/suite/[id]/*`, shared dashboard/app-shell/navigation components |
| DEV-M1-S01-T06 | Frontend + Backend Brand/Profile | `web/src/app/suite/[id]/profile/*`, profile/brand components, `api/routers/suites.py` or profile update endpoints |
| DEV-M1-S01-T07 | Backend + Frontend Connections/Analytics | `api/routers/connections.py`, `api/routers/analytics.py`, `web/src/app/suite/[id]/connections/*`, `web/src/app/suite/[id]/analytics/*` |

Developers should keep changes scoped to these file areas unless code discovery proves the existing ownership is elsewhere.

## 5. Acceptance Criteria Per Task

### DEV-M1-S01-T01 - Suite Memory v0 Read Contract

- A single backend helper or equivalent contract builds normalized M1 Suite context from `Suite.brand`, `Suite.strategy`, and `Suite.connections`.
- The contract covers business profile, audience profile, brand profile, language profile, content rules, visual assets, personas, products/services, and platform connection summary.
- Existing JSON keys remain backward compatible.
- User-edited fields are preserved over AI-suggested fields unless the user explicitly replaces a section.
- Create & Generate can determine whether `Use brand` should default on from the normalized context.

### DEV-M1-S01-T02 - Generation Job Status Visibility

- Every M1 generation entry point creates or returns a job state before long provider work starts.
- Jobs finish in one terminal state: `completed`, `failed`, `cancelled`, or `timeout`.
- Active jobs expose status, stage/progress where available, age, last update, provider/model where known, retry/wait information where known, and a user-safe error message.
- Stale `queued`, `running`, `retrying`, or provider-limit jobs have a timeout/stuck policy visible to UI/admin.
- A generation button never appears to do nothing.

### DEV-M1-S01-T03 - Media Readiness Metadata

- Content responses include media readiness for each generated item: ready, missing, failed, local-only, unsupported, or not-required.
- Responses distinguish public HTTPS media from local `/static` fallback.
- Missing media includes a user-safe reason when known.
- Publishable image/video content is not represented as publish-ready unless it has durable public media.
- Existing content without metadata gets a safe fallback state.

### DEV-M1-S01-T04 - Create & Review UI State Updates

- Create & Generate shows queued/running/waiting/failed/completed states after submit and after refresh where backend state allows.
- `Use brand` defaults on only when Suite Memory v0 reports usable brand data; otherwise it is off or visibly limited.
- Content Review status filters include All, Pending, Approved, Rejected, and Published.
- Reject opens a reason/free-text step before submitting.
- Media cards show preview/download when ready and explanatory disabled/missing states when not ready.

### DEV-M1-S01-T05 - Mobile Suite Navigation

- Mobile users inside a Suite can reach Dashboard/Home, Connections, Brand/Profile, Create & Generate, Content, Analytics, and Product Bulk.
- The mobile menu can be opened and closed without permanently covering content.
- Account-level and Suite-level navigation remain distinguishable.
- Labels are localized through existing i18n where available, or consistently English for this slice if translation keys are not ready. Avoid mixed Arabic/English default labels.

### DEV-M1-S01-T06 - Minimum Editable Brand/Profile

- Brand/Profile supports editing and saving M1 minimum fields: business name, category, audience languages, products/services, audience note/interests/behaviors/segments, USP/ESP, logos/assets, personas/reference images, and content rules where already supported.
- Edits persist after refresh.
- Manual edits are not silently overwritten by AI regeneration.
- The old "Edit in wizard" path does not create a new Suite when the user intends to edit the current Suite.
- Inputs support RTL/LTR mixed content using existing direction patterns.

### DEV-M1-S01-T07 - Connections / Analytics Truthful States

- Connections shows Meta, Google Ads, and storage as connected, not connected, needs attention, or unavailable.
- Missing config names can be shown without exposing secret values.
- Partial Meta state can distinguish Facebook page, Instagram account, and Meta Ads readiness where data exists.
- Analytics does not show misleading all-zero dashboards when the true state is no connection, missing permission, provider error, unsupported metric, or no data.
- Dedicated Connections page opens or foregrounds the connection status instead of hiding the main state by default.

## 6. Architecture Gates Per Task

| Task ID | Gate |
| --- | --- |
| DEV-M1-S01-T01 | Architecture must confirm Suite Memory v0 keys, merge rules, and backward compatibility before dependent generation/profile changes are considered complete. |
| DEV-M1-S01-T02 | Architecture + DevOps must confirm whether M1 accepts process-local `BackgroundTasks` with stuck-job handling, or whether this slice reveals a worker/queue blocker. |
| DEV-M1-S01-T03 | Architecture must confirm media readiness semantics are explicit enough for review and publish guards. |
| DEV-M1-S01-T04 | Product + Architecture must confirm visible job/media states match backend semantics and do not create false success states. |
| DEV-M1-S01-T05 | Design must confirm mobile navigation separates account and Suite scope and does not block core paths. |
| DEV-M1-S01-T06 | Architecture must confirm profile saves use Suite Memory v0 merge rules and protect user edits. |
| DEV-M1-S01-T07 | Architecture + DevOps must confirm connection/analytics states reflect capability/data quality, not token presence alone. |

## 7. QA Re-checks Per Task

| Task ID | QA Smoke Re-checks |
| --- | --- |
| DEV-M1-S01-T01 | M1-SMOKE-021, M1-SMOKE-022, M1-SMOKE-030, M1-SMOKE-032, M1-SMOKE-043 |
| DEV-M1-S01-T02 | M1-SMOKE-041, M1-SMOKE-042, QA-M1-001, QA-M1-003 |
| DEV-M1-S01-T03 | M1-SMOKE-054, M1-SMOKE-090, M1-SMOKE-091, QA-M1-002 |
| DEV-M1-S01-T04 | M1-SMOKE-040, M1-SMOKE-041, M1-SMOKE-043, M1-SMOKE-050, M1-SMOKE-051, M1-SMOKE-052, M1-SMOKE-053, M1-SMOKE-054 |
| DEV-M1-S01-T05 | M1-SMOKE-011, M1-SMOKE-012, M1-SMOKE-100, M1-SMOKE-101, M1-SMOKE-102, QA-M1-005 |
| DEV-M1-S01-T06 | M1-SMOKE-030, M1-SMOKE-031, M1-SMOKE-032 |
| DEV-M1-S01-T07 | M1-SMOKE-070, M1-SMOKE-071, M1-SMOKE-080, QA-M1-004 |

QA should keep blocked credential-dependent checks blocked until DevOps/Product provide real or fixture credentials. Slice 01 should still pass the no-credential clarity states.

## 8. DevOps / Human / Owner Blockers

| Blocker | Owner | Impact On Slice 01 |
| --- | --- | --- |
| Confirm target environment has `ANTHROPIC_API_KEY` or approved provider fallback. | DevOps / Infra | Full generation happy path cannot be re-checked without it; UI failure state can still be tested. |
| Confirm R2 bucket, public URL, and access keys. | DevOps / Infra | Durable public media and publish-readiness checks remain blocked; missing-storage state can still be implemented and tested. |
| Decide whether M1 customer testing accepts FastAPI `BackgroundTasks` with stuck-job handling. | Architecture + DevOps + Product | If not accepted, queue/worker setup becomes an immediate follow-up or release blocker. |
| Provide Meta and Google Ads test credentials/accounts. | Product + DevOps | Connected-state and analytics happy paths remain blocked; no-credential states can still be implemented and tested. |
| Provide approved product bulk sample Excel/ZIP fixtures. | Product + QA | Product Bulk is mostly outside Slice 01, but later slices need fixtures before QA can close import findings. |

## 9. What Is Explicitly Not Included In Slice 01

- Full campaign builder, campaign/ad/adset mutation, or automated campaign launch.
- Mobile native apps.
- Full Product Bulk Studio stabilization beyond shared job/media state safety.
- Full durable worker/queue implementation unless Architecture/DevOps reject the short-term `BackgroundTasks` risk during the gate.
- Full publishing workflow redesign or `PublishJob` implementation.
- Billing package work, Morning webhook enablement, or payment flow changes.
- Complete localization rewrite for every legacy panel.
- Visual redesign of the app shell beyond mobile reachability and state clarity.
- Advanced analytics dashboards beyond truthful empty/error/permission states.

## 10. Recommended Next Slices After Slice 01

1. Slice 02 - Durable Queue / Worker Decision And Implementation  
   Add a Railway worker or DB-backed runner, provider concurrency limits, retry scheduling, and stuck-job alerts if M1 cannot accept process-local background tasks.

2. Slice 03 - Publish Safety And Per-Platform Results  
   Persist per-platform publish success/failure/warning state and block unsafe media publishing, especially Instagram/image/video paths.

3. Slice 04 - Product Bulk M1 Stabilization  
   Finalize localized column guidance, Excel/ZIP validation, matched/missing image explanations, first-template approval, and per-asset retry/review.

4. Slice 05 - Onboarding Completion And RTL/Language Pass  
   Tighten manual fallback, logo classification visibility, custom audience fields, USP/ESP bulk add, and Arabic/Hebrew smoke findings.

5. Slice 06 - Connections And Analytics Happy Path  
   After credentials are available, close Meta/Google connected-state, permission, campaign-read, and date-filter checks.

6. Slice 07 - Release Gate Hardening  
   Close remaining QA findings, update accepted risks, perform architecture re-check, and prepare final M1 release recommendation.
