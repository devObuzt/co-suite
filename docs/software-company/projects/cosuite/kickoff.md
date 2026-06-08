# co-Suite Project Kickoff

Date: 2026-06-07  
Project: co-Suite AI Marketing Operating System  
Current phase: Production MVP  
Current milestone: Milestone 1 - Production Stabilization  
Project owner: Project Management Agent  

## Start Decision

The project starts only after these kickoff conditions are true:

| Gate | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Owner approval received | Project Management | approved | User approved Milestone 1 Production Stabilization on 2026-06-07. |
| Initial scope selected | Product Manager + Project Management | approved | Start with Milestone 1, not full platform. |
| Work tracking location exists | Project Management | done | `docs/software-company/projects/cosuite/`. |
| First milestone documented | Project Management | in_progress | `milestone-01-production-stabilization.md`. |
| Department owners identified | Project Management | done | See ownership map below. |
| Git policy clarified | Project Management | done | User said not to add current docs to git now. |

## First Milestone

We start with **Milestone 1: Production Stabilization**.

Reason:

- The app already has many valuable features, but reliability is uneven.
- Generation, media, queues, publishing, analytics, and onboarding need stable contracts before the team expands work.
- A self-running team needs a stable baseline and clear review loops.

## Ownership Map

| Area | Primary Owner | Supporting Owners |
| --- | --- | --- |
| Scope and acceptance criteria | Product Manager | Project Management |
| Architecture baseline | Architecture | Developers Manager, DevOps |
| UX stability and mobile usability | Design | Product Manager, QA |
| Runtime, env, media, queues | DevOps / Infra | Architecture, Developers |
| Engineering breakdown | Developers Manager | Architecture, Developers |
| Implementation | Developers | Developers Manager |
| Verification and re-check | QA | Developers, Design |
| Status, blockers, handoffs | Project Management | All departments |

## Kickoff Rules

1. Project Management decides what starts, based on approved milestone scope.
2. Product Manager defines the user-facing outcome before Developers start.
3. Architecture defines boundaries and risks before implementation.
4. Developers Manager breaks work into tasks before Developers implement.
5. QA records findings and re-checks them; screenshots or reproduction notes are preferred.
6. Architecture returns after implementation to check drift.
7. Project Management keeps status visible in `status-log.md`.
8. Nothing is silently considered done.

## Communication Rhythm

| Rhythm | Owner | Output |
| --- | --- | --- |
| Daily status | Project Management | Update `status-log.md`. |
| Task handoff | Sending department | Update `handoff-log.md`. |
| QA re-check | QA | Update `registers/qa-findings.md`. |
| Architecture re-check | Architecture | Update architecture review/drift registers. |
| Release gate | Project Management | Update `registers/release-readiness.md`. |

## First 72 Hours Plan

| Timebox | Owner | Output |
| --- | --- | --- |
| Hour 0-4 | Project Management | Kickoff docs, task board, milestone scope. |
| Day 1 | Product Manager | Milestone 1 acceptance criteria and current top broken flows. |
| Day 1 | Architecture | Baseline review of generation jobs, media storage, Suite Memory, provider limits. |
| Day 1-2 | DevOps / Infra | Env, Railway, DB, R2, worker/queue, health check checklist. |
| Day 2 | Design | Mobile/dashboard/create/onboarding UX baseline findings. |
| Day 2 | Developers Manager | Task breakdown for first implementation slice. |
| Day 2-3 | QA | Baseline smoke test matrix and first findings. |

## Start Approval

Project Management approves starting Milestone 1 documentation and planning now.

Company owner approved starting with Milestone 1: Production Stabilization on 2026-06-07.

Implementation starts only after:

- Milestone 1 task board has owner/status/acceptance criteria.
- Architecture baseline task is open.
- QA baseline task is open.
- Developers Manager has first task breakdown.
