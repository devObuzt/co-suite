# co-Suite M1 Implementation Slice 02

Date: 2026-06-07  
Owner: Developers Manager  
Status: ready_for_developer_handoff  
Milestone: M1 - Production Stabilization  

## Goal

Close the highest post-review M1 gaps after Slice 01: review and validate the newly implemented publishing safety work, let logged-in users test limited generation before Suite onboarding, polish native-language/RTL/theme issues on the new Suite surfaces, then run the unblocked post-slice smoke pass.

## Task Order

| Order | Task ID | Owner | Task | Dependencies | Acceptance Tests |
| ---: | --- | --- | --- | --- | --- |
| 1 | DEV-E-01 | Architecture + QA, with Developers on fixes | Review publishing preflight and partial publish state now marked `needs_review`. Validate that media posts with missing, failed, local-only, or non-public media are blocked, explicit text-only publish is respected, and per-platform results prevent misleading global publish success. | Slice 01 media readiness contract; implemented `DEV-E-01`; Architecture `ARCH-REV-M1-002`; R2 status from DevOps where available. | Confirm targeted publishing/media tests remain green, then Architecture signs off or sends concrete fixes. QA: `M1-SMOKE-090`, `M1-SMOKE-091`, `M1-SMOKE-092`, `QA-M1-002`. |
| 2 | DEV-D-01 | Developers - Account/Create | Add limited account-level generation without Suite. A logged-in user can start prompt-driven Quick Post/Ad and existing safe media modes without Suite onboarding. `Use brand` is disabled/off, Suite-only promises are absent, job/error/media states match Suite generation, and the upgrade path to create a Suite is visible. | Slice 01 job/media state UI; Product `PROD-02`; current auth/session routing; no dependency on `DEV-E-01` except shared media/publish copy. | Manual and automated checks for authenticated no-Suite user path, disabled `Use brand`, prompt/language submission, visible queued/running/failed/completed states, account-level recent result or save behavior, and Suite upgrade CTA. QA should add or map smoke coverage from `M1-SMOKE-001`, `M1-SMOKE-002`, `M1-SMOKE-041`, `M1-SMOKE-042`, `M1-SMOKE-044`, `QA-M1-003`. |
| 3 | DEV-F-01 | Developers - Frontend/Design | Polish native-language, RTL, and theme behavior for the new Suite screens touched by Slice 01 and Slice 02: Suite nav, Brand/Profile, Connections, Analytics, Create, Content Review, and publishing/account-generation states. Replace hard-coded dark styling where practical or explicitly scope it as an approved studio surface. | Slice 01 navigation/profile/content changes; Slice 02 publishing/account-generation UI copy; Design baseline language/theme findings. | Desktop and mobile visual checks in English, Arabic, and Hebrew; light/dark checks for the touched screens; no mixed core navigation labels; `dir="auto"` or correct direction for user content, URLs, handles, and prompts. QA: `M1-SMOKE-005`, `M1-SMOKE-006`, `M1-SMOKE-011`, `M1-SMOKE-012`, `M1-SMOKE-024`, `M1-SMOKE-044`, `M1-SMOKE-100`, `M1-SMOKE-101`, `M1-SMOKE-102`, `QA-M1-005`. |
| 4 | QA-02 | QA | Run post-slice smoke against a clean production build or approved local/staging target. Clean web production build now passes outside sandbox; `QA-M1-006` is closed. | DEV-E-01, DEV-D-01, DEV-F-01 ready for review; build command evidence from DevOps; test accounts/fixtures where available. | QA gate recommendation recorded with pass/block/pass-with-accepted-risk, new findings logged from `QA-M1-007` onward, and credential-blocked checks explicitly marked blocked rather than silently skipped. |

## Dependencies And Gates

| Dependency | Required Before | Owner | Gate |
| --- | --- | --- | --- |
| Architecture review of publish semantics | Before DEV-E-01 can move from `needs_review` to accepted | Architecture | Confirm media preflight and per-platform result state satisfy `ARCH-REV-M1-002` without requiring a full `PublishJob` for M1. |
| Product review of no-Suite generation promise | DEV-D-01 complete | Product Manager | Confirm the account-level flow does not imply Suite Memory, publishing, scheduling, analytics, or campaign readiness. |
| Design review of RTL/theme pass | DEV-F-01 complete | Design | Confirm new/touched screens meet the M1 native-language and theme bar without demanding a full visual redesign. |
| Production-build smoke target | QA-02 start | DevOps / Developers | Provide the command, URL, build artifact, or deployment target QA should use. |

## Owner / Human Action Needed

| Action | Owner | Needed For | QA Handling Until Available |
| --- | --- | --- | --- |
| Confirm R2 bucket/public URL/access keys for durable media. | DevOps / Infra | Full media publish readiness and `M1-SMOKE-090`. | Test missing-storage limitation and block durable-media happy path. |
| Provide safe Meta/Facebook/Instagram publishing target or explicit approval for sandbox publishing. | Product + DevOps | End-to-end per-platform publish smoke. | Do not publish to real brand channels; test preflight and mocked/fixture partial states. |
| Confirm AI provider keys and provider limits for generation smoke. | DevOps / Architecture | Happy-path Suite and account-level generation. | Verify visible provider/config failure states. |
| Provide approved Arabic/Hebrew/English prompts and expected native-language examples. | Product + Design + QA | DEV-F-01 and `M1-SMOKE-044`, `M1-SMOKE-101`. | Use synthetic RTL prompts and log copy-quality findings separately. |
| Provide QA target and test accounts after coding. | Developers Manager + DevOps | QA-02. | QA remains `not_started` until target is named. |

## Not In This Slice

- Full durable queue/worker implementation unless Architecture/DevOps reject the accepted M1 posture.
- Full product bulk stabilization beyond shared job/media/language checks.
- Native mobile apps.
- Campaign creation/editing or automated publishing schedules.
- Billing, Morning webhook, or package checkout changes.

## Recommended First Coding Task

Start with `DEV-D-01`. `DEV-E-01` is already implemented and needs Architecture/QA review, so the first remaining coding task is the limited account-level generation path without Suite onboarding.
