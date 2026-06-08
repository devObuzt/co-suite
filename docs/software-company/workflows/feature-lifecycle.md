# Feature Lifecycle Workflow

## Purpose

Move a feature from idea to verified implementation without losing product intent, architecture control, design quality, or QA accountability.

## Steps

1. Product Manager writes or updates product scope.
2. Architecture reviews scope and defines technical constraints.
3. Design defines UX/screen/state requirements.
4. DevOps/Infra reviews runtime needs.
5. Developers Manager creates implementation plan.
6. Developers implement and verify locally.
7. QA tests and logs findings.
8. Developers fix assigned findings.
9. QA re-checks findings.
10. Architecture re-checks final implementation for drift.
11. Project Management updates release readiness.

## Required Handoffs

```txt
Product -> Architecture
Product -> Design
Architecture + Design + DevOps -> Developers Manager
Developers Manager -> Developers
Developers -> QA
QA -> Developers
Developers -> QA re-check
Developers/QA -> Architecture re-check
All -> Project Management release status
```

## Exit Criteria

- Acceptance criteria satisfied.
- QA high/critical findings closed or accepted as risk.
- Architecture re-check completed.
- DevOps runtime requirements met or explicitly deferred.
- Release readiness updated.

