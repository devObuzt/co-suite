# Operating Model

Last updated: 2026-06-07

## Mission

Build software like a small, disciplined company: product decisions are explicit, architecture is reviewed continuously, implementation has owners, QA tracks findings until closure, and release decisions are evidence-based.

## Standard Lifecycle

1. Product Manager defines the product outcome.
2. Product Manager runs brand/design intake when UI, website, app, or client-facing screens are involved.
3. Product Manager runs UX style intake when product comfort, animation, dashboard density, or long-session work is involved.
4. Architect reviews feasibility, boundaries, data flow, scalability, and risks.
5. Design defines UX, UI behavior, responsive requirements, content clarity, and visual direction.
6. DevOps/Infra checks environments, secrets, queues, storage, observability, and deploy risks.
7. Developers Manager converts the spec into sequenced engineering tasks.
8. Developers implement with tests and local verification.
9. QA verifies against acceptance criteria and records findings.
10. Architect runs an architecture re-check against the implementation.
11. Project Management prepares release status and blocker summary.
12. Release proceeds only when open findings and risks are explicitly resolved, deferred, or accepted.

## Department Managers

Every department has a named manager. The current manager roster lives in:

- `department-managers.md`

Owner-review summaries must attribute meaningful department changes to the relevant manager.

## Brand And Design Intake

The brand/design intake workflow applies to every project:

- `workflows/brand-and-design-intake.md`

For any UI, website, app, or visual product work, Product Management must confirm whether brand materials exist. If the client/owner has not provided brand assets, Product Management must ask for them or record that the project has no brand assets yet.

Design must not produce final UI direction from guesswork when brand assets are expected but missing.

## UX Style Intake

UX style is a product decision, not only a design preference:

- `workflows/ux-style-intake.md`

For every project, Product Management must ask how the experience should feel or propose a style when the owner/client is unsure.

For OneShare, the default UX direction is calm, clear, modern, lightly animated, and comfortable for long work sessions.

## Control Loops

### Autonomous Delivery Loop

The default working mode is autonomous execution:

- department managers continue their responsibilities without asking the owner after every small step;
- Project Management decides whether the team continues, returns for fixes, or moves phase;
- the owner is interrupted only for business decisions, permissions, access, accepted risk, or final version review.

Workflow:

- `workflows/autonomous-delivery-loop.md`

### Architecture Control Loop

The architect does not only design upfront. The architect returns after implementation and asks:

- What was planned?
- What was implemented?
- What was skipped?
- What was changed?
- Did the implementation create architecture drift?
- Are scalability, security, billing, queue, data, or integration assumptions still true?
- What must be fixed now versus tracked as debt?

Outputs:

- `registers/architecture-review-log.md`
- `registers/architecture-drift-register.md`
- architecture handoff notes to Developers Manager and Project Management.

### QA Control Loop

QA does not only test once. QA records every finding and re-checks it later.

Each finding must have:

- ID.
- title.
- severity.
- affected area.
- reproduction steps.
- expected result.
- actual result.
- owner.
- status.
- re-check date.
- final resolution.

Outputs:

- `registers/qa-findings.md`
- release gate recommendation.

### Pricing And Quote Control Loop

Project Management owns client quotes, but does not invent technical hours alone. A client-facing quote requires department estimates first.

Required estimate inputs:

- Product Manager confirms scope, phases, inclusions, exclusions, and product assumptions.
- Architecture confirms complexity, integration risk, scalability, AI/provider limits, queue needs, and security assumptions.
- Design confirms UX/UI screens, states, responsive scope, design-system work, and review cycles.
- DevOps/Infra confirms deployment, hosting, storage, database, queue, monitoring, secrets, and runtime provider costs.
- Developers Manager confirms module breakdown, engineering sequencing, and development hour ranges.
- Developers sanity-check module estimates and implementation unknowns when assigned.
- QA confirms test matrix, regression, release verification, and re-check hours.

Outputs:

- `workflows/client-quote-lifecycle.md`
- `registers/estimation-register.md`
- `quotes/YYYY-MM-DD-client-project-quote.md`

No quote should be sent to a client unless scope, build hours, operating costs, AI/provider usage, advertising budget handling, assumptions, exclusions, and risk buffer are visible.

## Decision Rules

- If a decision affects product scope, Product Manager owns it.
- If a decision affects technical direction, Architecture owns it.
- If a decision affects visual/UX quality, Design owns it.
- If a decision affects deployment, runtime, secrets, monitoring, or scale, DevOps/Infra owns it.
- If a decision affects release readiness, QA and Project Management must both be heard.

## Status Language

Use consistent status terms:

- `proposed`: suggested but not accepted.
- `approved`: accepted and ready for execution.
- `in_progress`: actively being worked.
- `blocked`: cannot progress without a specific dependency.
- `needs_review`: ready for another agent to review.
- `changes_requested`: review found required changes.
- `accepted_risk`: known risk accepted by owner.
- `done`: implemented and verified.

## Required Registers

- `decision-log.md`: durable decisions and rationale.
- `risk-register.md`: product, technical, operational, legal, and delivery risks.
- `architecture-review-log.md`: architecture reviews and re-checks.
- `architecture-drift-register.md`: deviations between intended and actual architecture.
- `qa-findings.md`: defects and re-check history.
- `release-readiness.md`: current release status.
- `estimation-register.md`: client quote estimates, owner departments, hours, assumptions, and risks.

## Reusable Project Layer

Every future project should start with the templates in `templates/` instead of inventing a new control format.

- `templates/project-task-board.md`: project-local board with active tasks, blockers, recently done work, and cycle notes.
- `templates/agent-cycle-runbook.md`: one delivery loop from phase selection through QA, architecture re-check, and Project Management decision.
- `templates/manager-responsibilities.md`: portable department ownership table.
- `templates/qa-architecture-gates.md`: phase gates for QA and Architecture.

Project Management can create a timestamped markdown owner-review from a project task board with:

```sh
python3 scripts/software_company/generate_owner_review.py <project>
```

The script reads `docs/software-company/projects/<project>/task-board.md` and writes to `docs/software-company/owner review/`. It is intentionally local, dependency-free, and safe to run before or after a cycle.
