# Handoff Protocol

## Purpose

Every agent handoff must be explicit. No department should guess what the previous department decided.

## Standard Handoff Format

```txt
From:
To:
Date:
Scope:
Context:
Decisions made:
Artifacts produced:
Open questions:
Risks:
Required next action:
Definition of done:
```

## Required Handoffs

### Product -> Architecture

Must include:

- user outcome.
- scope.
- acceptance criteria.
- constraints.
- pricing/billing implications if any.

### Product -> Design

Must include:

- user persona.
- primary flow.
- language requirements.
- required states.
- success criteria.

### Architecture -> Developers Manager

Must include:

- boundaries.
- data contracts.
- job/queue requirements.
- provider/integration constraints.
- migration risks.
- observability requirements.

### Design -> Developers Manager

Must include:

- screen behavior.
- responsive requirements.
- component states.
- copy requirements.
- accessibility concerns.

### Developers -> QA

Must include:

- changed files/areas.
- verification commands.
- known gaps.
- test accounts/data needed.
- expected behavior.

### QA -> Developers

Must include:

- finding IDs.
- repro steps.
- severity.
- expected/actual.
- screenshots/logs if available.
- re-check criteria.

### Developers/QA -> Architecture

Must include:

- final implementation notes.
- deviations from plan.
- data/model/provider changes.
- open technical debt.

## Handoff Storage

For large work, create a dated file:

```txt
docs/software-company/handoffs/YYYY-MM-DD-<feature>-handoff.md
```

Small handoffs can be recorded in the relevant register.

