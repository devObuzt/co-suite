# OneShare Task Board

Last updated: 2026-06-08

## Status Values

- `not_started`
- `in_progress`
- `blocked`
- `needs_review`
- `ready_for_handoff`
- `done`
- `accepted_risk`

## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| PM-01 | M1 | Project control room | Project Management | done | Kickoff docs, milestone scope, task board, status log, handoff log exist. | Product Manager, Architecture, DevOps, Design, QA |
| PROD-01 | M1 | MVP acceptance criteria | Product Manager | ready_for_handoff | Must/should/later flows and stable-enough criteria are defined in `product-acceptance-m1.md`. | Architecture, Design, Developers Manager, QA |
| ARCH-01 | M1 | Baseline architecture review | Architecture | ready_for_handoff | Generation, media, Suite Memory, provider limits, queues, drift risks mapped in `architecture-baseline-m1.md`. | Developers Manager, DevOps |
| DESIGN-01 | M1 | UX baseline review | Design | ready_for_handoff | Mobile/desktop blockers and quick fixes listed in `design-baseline-m1.md`. | Developers Manager, QA |
| DEVOPS-01 | M1 | Runtime readiness review | DevOps / Infra | ready_for_handoff | Env, Railway, DB, R2, worker/queue, health, monitoring checklist done in `devops-readiness-m1.md`. | Architecture, Developers Manager |
| DEVMGR-01 | M1 | Engineering task breakdown | Developers Manager | ready_for_handoff | Implementation tasks ordered with dependencies, review gates, QA needs in `implementation-slice-01-m1.md`. | Developers |
| DEV-A-01 | M1 | Backend Suite Memory, generation job status, media readiness | Developers | needs_review | Backend exposes normalized Suite context, truthful job state, and media readiness metadata without breaking existing data. Backend tests pass. | Architecture, QA |
| DEV-B-01 | M1 | Frontend Create & Content Review states | Developers | needs_review | Create/content UI shows job/media states, status All filter, reject reason flow, and non-misleading Use Brand state. TypeScript passes; production build hang needs DevOps follow-up. | QA, Design, DevOps |
| DEV-C-01 | M1 | Mobile Suite nav, Brand/Profile, Connections/Analytics states | Developers | needs_review | Mobile Suite screens are reachable; profile is minimally editable; connections/analytics show truthful states. TypeScript passes. | QA, Design |
| DEV-D-01 | M1 | Limited account-level generation without Suite | Developers Manager / Developers | not_started | Logged-in user can reach limited prompt-driven generation without Suite onboarding; `Use brand` is unavailable/off; job/error/media states are visible; upgrade path to Suite is clear. | Architecture, Design, QA |
| DEV-E-01 | M1 | Publishing preflight and partial publish state | Developers | needs_review | Media posts cannot publish unless media is ready, or user explicitly chooses text-only. Partial platform success must not mark the whole post globally published without per-platform state. Backend tests pass. | Architecture, QA |
| DEV-F-01 | M1 | Native-language/RTL and theme polish for new Suite screens | Developers | not_started | New Suite nav/profile/connections/analytics copy uses app language, RTL is verified, and hard-coded dark panels are reduced or clearly scoped. | Design, QA |
| DEVMGR-02 | M1 | Implementation Slice 02 after agent reviews | Developers Manager | ready_for_handoff | `implementation-slice-02-m1.md` routes publishing safety review, limited account-level generation, native-language/RTL/theme polish, and post-slice smoke with owners, dependencies, acceptance tests, and human actions. | Developers, Architecture, Design, QA |
| PROD-02 | M1 | Product direction re-check | Product Manager | done | M1 is checked against owner direction: autonomous workflow foundation, stable onboarding, limited generation without Suite, scalable AI/job model, and web/SEO/mobile-app future. Scope corrections are documented in `product-acceptance-m1.md`. | Developers Manager, QA, Design |
| QA-01 | M1 | Baseline smoke test | QA | ready_for_handoff | Smoke matrix and initial M1 findings created in `qa-smoke-matrix-m1.md` and `qa-findings.md`. | Developers Manager, Architecture |
| QA-02 | M1 | Post-slice smoke test | QA | not_started | Run M1 smoke matrix against local or deployed app after clean web build is available. Clean web build now passes outside sandbox. | Developers Manager |
| PM-02 | M1 | Autonomous phase control | Project Management | in_progress | Project Manager keeps Production Stabilization + UX Trust active, routes department work, and decides phase movement after QA/Architecture re-check. | QA, Architecture |
| QA-03 | M1 | Media preview and content action re-check | QA | needs_review | Recent Content actions show feedback; media preview states are checked for image/video/local-only/R2 cases. Findings recorded or marked clear. | Architecture |
| DEV-H-01 | M1 | Media preview readiness fix pass | Developers | done | Image/video cards show truthful preview/open/download states and actionable reasons when media cannot render. Build passes. | QA |
| DEVMGR-03 | M1 | Product Bulk stability slice | Developers Manager | in_progress | Next Product Bulk slice is defined around import, matching, first templates, approve template, generate all, and per-item regeneration. | Developers |
| ARCH-02 | M1 | Post-stabilization architecture re-check | Architecture | not_started | Architecture reviews latest generation/media/product-bulk flow and decides whether phase can move forward. | Project Management |

## Blocked Tasks

None currently blocking local verification. `DEVOPS-02` was resolved as a local cache/sandbox issue.

## Recently Done

| ID | Milestone | Task | Owner | Done Date |
| --- | --- | --- | --- | --- |
| PM-01 | M1 | Project control room | Project Management | 2026-06-07 |
| PROD-01 | M1 | MVP acceptance criteria | Product Manager | 2026-06-07 |
| ARCH-01 | M1 | Baseline architecture review | Architecture | 2026-06-07 |
| DEVOPS-01 | M1 | Runtime readiness review | DevOps / Infra | 2026-06-07 |
| DESIGN-01 | M1 | UX baseline review | Design | 2026-06-07 |
| QA-01 | M1 | Baseline smoke test | QA | 2026-06-07 |
| DEVMGR-01 | M1 | Engineering task breakdown | Developers Manager | 2026-06-07 |
| PROD-02 | M1 | Product direction re-check | Product Manager | 2026-06-07 |
| DEVOPS-02 | M1 | Local Next production build hang investigation | DevOps / Developers | 2026-06-07 |
| DEVMGR-02 | M1 | Implementation Slice 02 after agent reviews | Developers Manager | 2026-06-07 |
| DEV-D-01 | M1 | Limited account-level generation without Suite | Developers Manager / Developers | 2026-06-08 |
| DEV-F-01 | M1 | Native-language/RTL and theme polish for new Suite screens | Developers | 2026-06-08 |
| DEV-H-01 | M1 | Media preview readiness fix pass | Developers | 2026-06-08 |
