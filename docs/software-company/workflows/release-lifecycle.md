# Release Lifecycle Workflow

## Purpose

Prevent unstable releases by requiring evidence from every department.

## Release Inputs

- Feature scope.
- Product acceptance criteria.
- Architecture re-check.
- DevOps readiness.
- Developer verification.
- QA findings and re-check status.
- Known risks.

## Release Gate

Release can proceed only when:

- Product: scope is correct.
- Architecture: no blocking drift.
- Design: affected UX is acceptable.
- DevOps: deploy/runtime/storage/queue/env readiness is clear.
- Developers Manager: implementation scope is complete.
- Developers: verification commands are documented.
- QA: release recommendation is pass or pass-with-accepted-risk.
- Project Management: blockers and owners are clear.

## Release Decision Values

- `release`
- `release_with_accepted_risk`
- `hold`
- `rollback`

## Required Register

Update `registers/release-readiness.md` for every release candidate.

