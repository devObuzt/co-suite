# Project Task Board Template

Last updated: YYYY-MM-DD

Use this file as `docs/software-company/projects/<project>/task-board.md`.

## Project

- Project: `<project-name>`
- Phase: `<current-phase>`
- Project Manager: `<manager-name>`
- Current decision: `continue | fix | block | ready_for_owner_review`

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
| PM-01 | M1 | Create project control room | Project Management | not_started | Project README, task board, status log, and handoff log exist. | Product Manager |
| PROD-01 | M1 | Define product outcome | Product Manager | not_started | Must/should/later scope and acceptance criteria are explicit. | Architecture, Design |
| ARCH-01 | M1 | Baseline architecture review | Architecture | not_started | System boundaries, data flow, integration risks, and drift risks are documented. | Developers Manager |
| DESIGN-01 | M1 | Baseline UX/design review | Design | not_started | Core journeys, responsive needs, content states, and visual direction are documented. | Developers Manager, QA |
| DEVOPS-01 | M1 | Runtime readiness review | DevOps / Infra | not_started | Env vars, deploy path, storage, queues, monitoring, and provider limits are checked. | Architecture |
| DEVMGR-01 | M1 | Engineering slice plan | Developers Manager | not_started | Work is broken into small implementation slices with dependencies and verification. | Developers |
| DEV-01 | M1 | Implement first slice | Developers | not_started | Code change is narrow, locally verified, and handed off with notes. | QA, Architecture |
| QA-01 | M1 | Smoke and regression pass | QA | not_started | QA checks acceptance criteria, logs findings, and recommends continue/fix/block. | Project Management |

## Blocked Tasks

| ID | Blocker | Needed From | Owner | Decision Needed |
| --- | --- | --- | --- | --- |
| - | None | - | - | - |

## Recently Done

| ID | Milestone | Task | Owner | Done Date |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Cycle Notes

- What changed this cycle:
- Evidence checked:
- Risks accepted:
- Next owner-review trigger:
