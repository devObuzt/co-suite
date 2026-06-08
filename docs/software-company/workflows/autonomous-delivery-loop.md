# Autonomous Delivery Loop

Last updated: 2026-06-08

## Purpose

This workflow defines how the software-company agents keep working without waiting for the owner after every small step.

The owner should only be interrupted when:

- a business decision is required;
- external access, keys, or permissions are required;
- a risk must be accepted by a human;
- the first stable version is ready for owner review;
- the system is blocked after three meaningful attempts.

## Operating Principle

The company works in continuous loops:

1. Project Manager selects the active phase.
2. Department managers inspect their area.
3. Developers Manager slices the work.
4. Developers implement and verify.
5. QA checks the result and records findings.
6. Architecture re-checks for drift.
7. Project Manager decides:
   - continue same phase;
   - send back for fixes;
   - move to the next phase;
   - request owner input.

## Required Loop Artifacts

Each project must keep:

- `task-board.md`: active tasks and ownership.
- `next-actions.md`: current execution order.
- `status-log.md`: chronological work log.
- `handoff-log.md`: cross-department handoffs.
- `registers/qa-findings.md`: findings and re-check status.
- `registers/architecture-drift-register.md`: architecture drift and debt.
- owner-review PDF/HTML/MD files for meaningful checkpoints.

## Department Responsibilities

### Project Management - Layla Haddad

Layla owns phase movement.

Layla must answer after each loop:

- What phase are we in?
- What was completed?
- What is still open?
- Are there blockers?
- Which department works next?
- Can we move forward?

Layla does not ask the owner for routine execution approval.

### Product Management - Omar Nassar

Omar owns user value and scope.

Omar must check:

- Does this still match the product vision?
- Did the implementation create a confusing or weak user flow?
- Is the next slice still the highest-value slice?
- Is owner input required?

### Architecture - Mira Cohen

Mira owns technical direction.

Mira must re-check after implementation:

- Did the code create architecture drift?
- Are AI/provider limits handled?
- Are queues, media, billing, auth, and integrations still safe enough?
- What must be fixed now versus tracked as debt?

### Design - Noa Barak

Noa owns visual and UX quality.

Noa must check:

- Is the UI usable on mobile and desktop?
- Is language direction correct?
- Is the design calm enough for long work sessions?
- Are key actions clear?
- Are error and empty states humane?

### DevOps / Infra - Kareem Mansour

Kareem owns runtime stability.

Kareem must check:

- Are env vars and provider keys clear?
- Are queues and AI limits represented truthfully?
- Is storage/public media ready?
- Is deployment health observable?

### Developers Manager - Daniel Farah

Daniel owns execution slicing.

Daniel must convert findings into small slices with:

- files likely touched;
- dependencies;
- acceptance criteria;
- verification commands;
- handoff target.

### Developers - Rami Saleh

Rami owns code implementation.

Rami must:

- implement narrowly;
- avoid unrelated refactors;
- run verification;
- record what changed.

### QA - Lina Saad

Lina owns verification.

Lina must:

- test the latest implemented slice;
- record findings;
- re-check old findings;
- recommend continue, fix, or block.

## Phase Decision Rules

Project Management may move to the next phase only when:

- must-have tasks for the current phase are done or explicitly accepted as deferred;
- build/tests for touched surfaces pass;
- QA has no unresolved P0/P1 finding for that phase;
- Architecture has no unresolved blocking drift;
- DevOps has no unresolved deployment/runtime blocker for the phase.

Project Management must stay in the same phase when:

- user-visible core flows still fail silently;
- mobile usability blocks primary actions;
- generation jobs hide queued/failed/rate-limited state;
- media preview/publishing state is misleading;
- product bulk import/generation is not stable enough for a serious user test.

## OneShare Current Autonomous Loop

Current phase:

- Production Stabilization + UX Trust.

Current strategy:

- Keep closing stability and trust gaps before adding larger new products.

Next execution order:

1. Media preview readiness for image/video posts.
2. Product Bulk Studio import and template-generation stability.
3. QA smoke pass for signup, Suite onboarding, generation, content review, product bulk, and mobile navigation.
4. Architecture drift re-check.
5. Project Management phase decision.

Owner interruption is not required right now.
