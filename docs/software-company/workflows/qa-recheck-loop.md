# QA Re-Check Loop

## Purpose

Make QA findings durable. A bug is not resolved because someone says it is fixed; it is resolved when QA re-checks and records the result.

## Finding Lifecycle

```txt
open
  -> fix_in_progress
  -> ready_for_recheck
  -> closed
```

Alternative outcomes:

```txt
deferred
accepted_risk
duplicate
not_reproducible
```

## Required Finding Fields

- ID.
- severity.
- area.
- finding.
- repro steps.
- expected.
- actual.
- owner.
- status.
- re-check date.
- resolution.

## Rules

- QA findings are never deleted.
- Every finding needs an owner.
- Every `ready_for_recheck` item must be tested again.
- Repeated failures are escalated to Developers Manager and Project Management.
- Critical/high findings block release unless formally accepted as risk.

## Register

Use `registers/qa-findings.md`.

