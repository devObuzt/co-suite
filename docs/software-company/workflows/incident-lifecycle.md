# Incident Lifecycle Workflow

## Purpose

Handle production or provider incidents with ownership, evidence, user impact, and follow-up.

## Incident Types

- deploy failure.
- API outage.
- database issue.
- AI provider rate limit/quota/outage.
- media storage failure.
- publishing failure.
- billing/payment failure.
- analytics/campaign sync failure.

## Steps

1. DevOps/Infra identifies incident and impact.
2. Project Management opens incident status.
3. Architecture reviews systemic cause and future prevention.
4. Developers fix application issue if needed.
5. QA verifies fix and regression.
6. Product Manager decides user-facing messaging if needed.
7. Project Management records resolution and follow-up actions.

## Required Incident Data

- start time.
- affected users/suites/jobs.
- impacted workflow.
- severity.
- root cause.
- mitigation.
- permanent fix.
- owner.
- follow-up date.

## Output

Use `registers/risk-register.md` for systemic risk and `registers/release-readiness.md` if release is affected.

