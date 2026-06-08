# cosuite Owner Review Cycle Report

Generated: 2026-06-08 13:53:37
Source board: `docs/software-company/projects/cosuite/task-board.md`

## Summary

- Total active tasks: 21
- `done`: 3
- `in_progress`: 2
- `needs_review`: 5
- `not_started`: 4
- `ready_for_handoff`: 7

## Department Load

- Architecture: 2 task(s); not_started, ready_for_handoff
- Design: 1 task(s); ready_for_handoff
- DevOps / Infra: 1 task(s); ready_for_handoff
- Developers: 6 task(s); done, needs_review, not_started
- Developers Manager: 3 task(s); in_progress, ready_for_handoff
- Developers Manager / Developers: 1 task(s); not_started
- Product Manager: 2 task(s); done, ready_for_handoff
- Project Management: 2 task(s); done, in_progress
- QA: 3 task(s); needs_review, not_started, ready_for_handoff

## Needs Review

- `DEV-A-01` Backend Suite Memory, generation job status, media readiness (Developers) -> Architecture, QA
- `DEV-B-01` Frontend Create & Content Review states (Developers) -> QA, Design, DevOps
- `DEV-C-01` Mobile Suite nav, Brand/Profile, Connections/Analytics states (Developers) -> QA, Design
- `DEV-E-01` Publishing preflight and partial publish state (Developers) -> Architecture, QA
- `QA-03` Media preview and content action re-check (QA) -> Architecture

## Active Handoffs

- `PROD-01` MVP acceptance criteria (Product Manager) -> Architecture, Design, Developers Manager, QA
- `ARCH-01` Baseline architecture review (Architecture) -> Developers Manager, DevOps
- `DESIGN-01` UX baseline review (Design) -> Developers Manager, QA
- `DEVOPS-01` Runtime readiness review (DevOps / Infra) -> Architecture, Developers Manager
- `DEVMGR-01` Engineering task breakdown (Developers Manager) -> Developers
- `DEVMGR-02` Implementation Slice 02 after agent reviews (Developers Manager) -> Developers, Architecture, Design, QA
- `QA-01` Baseline smoke test (QA) -> Developers Manager, Architecture
- `PM-02` Autonomous phase control (Project Management) -> QA, Architecture
- `DEVMGR-03` Product Bulk stability slice (Developers Manager) -> Developers

## Blockers

- No blocked active tasks found.

## Next Queue

- `DEV-D-01` Limited account-level generation without Suite (Developers Manager / Developers) -> Architecture, Design, QA
- `DEV-F-01` Native-language/RTL and theme polish for new Suite screens (Developers) -> Design, QA
- `QA-02` Post-slice smoke test (QA) -> Developers Manager
- `ARCH-02` Post-stabilization architecture re-check (Architecture) -> Project Management

## Manager Decision Prompt

- Project Management: continue, fix, block, or request owner review?
- QA: are any open findings phase-blocking?
- Architecture: is any drift blocking the next phase?
- Developers Manager: is the next slice small enough to verify quickly?
