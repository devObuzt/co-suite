# Milestone 1: Production Stabilization

## Goal

Make the current co-Suite web/API product stable enough for predictable feature delivery.

This milestone does not try to finish every product dream. It creates the base where the team can work without drowning in broken flows, invisible failures, or unclear ownership.

## Success Definition

Milestone 1 is successful when:

- signup/login and dashboard navigation are stable.
- users can run limited prompt-driven generation without completing a Suite, with no false brand/publishing/analytics promises.
- Suite onboarding can gather and save business profile data consistently.
- generation requests use clear status states: queued, running, failed, completed.
- generated media has durable public URLs when needed.
- content lifecycle actions work: approve, reject, regenerate, edit/copy/download where in scope.
- Meta/Google connection states are understandable.
- basic analytics and campaigns fail gracefully when permissions are missing.
- mobile layout is usable for the main dashboard and content review flows.
- QA has a baseline regression list.
- Architecture has completed a re-check after implementation.

## Scope In

| Workstream | Outcome |
| --- | --- |
| Product baseline | Define exact MVP flows and acceptance criteria. |
| Architecture baseline | Confirm Suite Memory, generation jobs, provider limits, media/storage, publishing, and analytics boundaries. |
| UX baseline | Stabilize key screens: signup, account-level quick generation, Suite dashboard, create/generate, onboarding, content review, connections. |
| DevOps baseline | Confirm env vars, Railway services, DB, R2, workers/queues, health checks, monitoring needs. |
| Engineering baseline | Convert known unstable flows into implementation tasks. |
| QA baseline | Smoke tests for auth, onboarding, generation, media preview, approve/reject, connections, analytics. |

## Scope Out

- Full mobile apps.
- Full campaign creation/editing in ad platforms.
- Fully automated social calendar loops.
- Full agency/team permissions.
- Advanced billing packages beyond MVP credits/subscription structure.
- Full subscription/token-pack checkout and marketing-budget ledger.
- Advanced SEO website builder or native mobile apps.
- Legal review by external lawyer.

## Workstreams

### PM-01: Project Control

- Owner: Project Management
- Status: in_progress
- Acceptance criteria:
  - kickoff docs exist.
  - milestone scope exists.
  - task board exists.
  - handoff log exists.
  - status log is updated after every meaningful step.

### PROD-01: MVP Acceptance Criteria

- Owner: Product Manager
- Status: not_started
- Acceptance criteria:
  - list the exact user flows that must pass in Milestone 1.
  - mark each flow as must-have, should-have, later.
  - define what “stable enough” means for each flow.
  - confirm user-facing language expectations.

### ARCH-01: Baseline Architecture Review

- Owner: Architecture
- Status: not_started
- Acceptance criteria:
  - map current generation flow.
  - map media storage/public URL flow.
  - map Suite Memory reads/writes.
  - map provider limits and queue behavior.
  - identify architecture drift and must-fix items.

### DESIGN-01: UX Baseline Review

- Owner: Design
- Status: not_started
- Acceptance criteria:
  - review mobile and desktop for signup, dashboard, onboarding, create/generate, content cards, connections.
  - list visual/usability blockers.
  - identify quick design fixes versus later redesigns.

### DEVOPS-01: Runtime Readiness Review

- Owner: DevOps / Infra
- Status: not_started
- Acceptance criteria:
  - document required env vars.
  - confirm Railway services and health checks.
  - confirm DB and R2/media storage readiness.
  - confirm worker/queue status.
  - document provider/admin alert needs.

### DEVMGR-01: Implementation Task Breakdown

- Owner: Developers Manager
- Status: not_started
- Acceptance criteria:
  - break Milestone 1 into reviewable engineering tasks.
  - assign dependencies and order.
  - mark which tasks require Architecture re-check.
  - mark which tasks require QA re-check.

### QA-01: Baseline Smoke Test

- Owner: QA
- Status: not_started
- Acceptance criteria:
  - test auth/signup/login.
  - test Suite onboarding with real examples.
  - test generation types currently available.
  - test media previews.
  - test approve/reject/regenerate.
  - test Meta/Google connection status.
  - test mobile layout.
  - log findings in QA register.

## Gates

| Gate | Required Before | Owner |
| --- | --- | --- |
| Product Gate | Engineering implementation starts | Product Manager |
| Architecture Gate | Risky backend/generation/media changes start | Architecture |
| DevOps Gate | Production-impacting changes deploy | DevOps / Infra |
| QA Gate | Release candidate accepted | QA |
| Architecture Re-check Gate | Milestone is marked done | Architecture |
| PM Gate | Work moves to Milestone 2 | Project Management |

## Done Criteria

Milestone 1 cannot be closed until:

- all must-have acceptance criteria are done or explicitly accepted as risk.
- high/critical QA findings are closed or accepted as risk.
- architecture re-check is documented.
- release readiness register is updated.
- open blockers have owners.
