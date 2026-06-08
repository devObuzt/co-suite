# QA And Architecture Gates

Last updated: 2026-06-08

Use these lightweight gates before a project moves phase or receives owner review.

## QA Gate

QA recommends `continue` only when:

- all must-have acceptance criteria for the current slice are tested;
- no open P0/P1 defect blocks the current phase;
- P2 defects have owners, dates, and fix/defer decisions;
- regression checks touched the changed surface and its nearest dependencies;
- failed, empty, loading, permission, and retry states are checked when relevant;
- evidence is recorded in the project QA artifact or `registers/qa-findings.md`.

QA recommends `fix` when:

- user-visible state is misleading;
- primary workflow completion is blocked;
- mobile or accessibility behavior blocks core use;
- verification could not run for a reason the team can control.

QA recommends `block` when:

- production data, payment, security, legal, or external account risk is unresolved;
- required credentials, seed data, provider access, or deploy visibility is missing;
- a release would require owner risk acceptance.

## Architecture Gate

Architecture recommends `continue` only when:

- implementation still matches the intended system boundary;
- data contracts and provider assumptions are true or explicitly updated;
- queue, retry, timeout, rate-limit, storage, auth, and billing implications are checked when relevant;
- no blocking architecture drift is open;
- known drift is recorded with owner, impact, and fix/defer decision.

Architecture recommends `fix` when:

- implementation bypasses an agreed boundary;
- state is duplicated without an owner of truth;
- error handling hides provider, queue, storage, or auth failure;
- a temporary shortcut would become expensive to undo.

Architecture recommends `block` when:

- the design creates serious data loss, security, billing, or scalability risk;
- the current implementation cannot be operated or debugged safely;
- a required architecture decision is missing.

## Phase Decision

Project Management may move the phase forward only when both QA and Architecture are `continue`, or when every exception is marked `accepted_risk` with owner approval.
