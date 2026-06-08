# Agent Cycle Runbook

Last updated: 2026-06-08

This runbook is the default operating loop for any project using the software-company system.

## Cycle Inputs

- `docs/software-company/projects/<project>/task-board.md`
- `docs/software-company/projects/<project>/next-actions.md`
- `docs/software-company/projects/<project>/status-log.md`
- `docs/software-company/projects/<project>/handoff-log.md`
- relevant register entries under `docs/software-company/registers/`

## Standard Cycle

1. Project Management selects the active phase and reads the task board.
2. Product checks that the next work still matches user value and acceptance criteria.
3. Architecture checks boundaries, data flow, integrations, risk, and likely drift.
4. Design checks UX flow, responsive behavior, content states, and visual quality when UI is involved.
5. DevOps checks runtime needs, secrets, deploy path, storage, queues, monitoring, and provider limits.
6. Developers Manager turns approved work into the smallest useful slice.
7. Developers implement only the assigned slice and record verification.
8. QA tests the slice, logs findings, and re-checks old findings.
9. Architecture re-checks the implementation against the plan.
10. Project Management updates the board and decides continue, fix, block, or owner review.

## Handoff Format

Each handoff should include:

- `From` and `To`
- task ID
- files or artifacts changed
- verification run
- open risks
- requested decision

## Owner Interruption Rules

Interrupt the owner only when:

- a business decision changes scope, pricing, legal exposure, or brand direction;
- external access, credentials, billing approval, or production permissions are required;
- a P0/P1 risk must be accepted;
- the current phase is ready for owner review;
- the same blocker remains after three meaningful attempts.

## Cycle Close Checklist

- Task board statuses are current.
- New blockers are listed in `Blocked Tasks`.
- QA findings are logged or marked clear.
- Architecture drift is logged or marked clear.
- Release gate state is explicit.
- Next handoff owner is named.
