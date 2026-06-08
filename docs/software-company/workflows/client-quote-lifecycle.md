# Client Quote Lifecycle

## Purpose

Produce a detailed client proposal with scope, hours, pricing, assumptions, risks, payment milestones, and ongoing costs.

## Owner

Project Management owns the quote from intake to client delivery.

## Contributors

| Department | Responsibility |
| --- | --- |
| Product Manager | Defines scope, user flows, phases, inclusions, exclusions, and product assumptions. |
| Architecture | Reviews technical complexity, integrations, data model, AI/provider risks, queue needs, security, and scalability assumptions. |
| Design | Estimates UX flows, screen design, responsive behavior, design system work, and prototype/review cycles. |
| DevOps / Infra | Estimates deployment, environments, database, storage, queues, monitoring, CI/CD, secrets, and expected runtime costs. |
| Developers Manager | Breaks scope into engineering modules and consolidates development hours. |
| Developers | Sanity-check implementation estimates and identify unknowns inside assigned modules. |
| QA | Estimates QA matrix, regression cycles, acceptance testing, release verification, and recheck time. |

## Workflow

1. Project Management opens a quote request and records the client goal, deadline, budget signals, and known constraints.
2. Product Manager turns the request into scoped phases and marks what is included and excluded.
3. Architecture reviews the scope for technical complexity, external dependencies, data flows, provider limits, security, and scale risks.
4. Design estimates the UX/UI work by flow, screen, state, responsive surface, and review cycle.
5. DevOps / Infra estimates setup, deployment, runtime services, monitoring, storage, queueing, and ongoing provider costs.
6. Developers Manager breaks the work into modules and collects implementation estimates from Developers where needed.
7. QA estimates test coverage, regression passes, device/browser coverage, and release verification.
8. Project Management consolidates low, expected, and high hour ranges into the estimation register.
9. Project Management adds visible risk buffer, pricing model, timeline, payment milestones, and assumptions.
10. Architecture and Developers Manager review the quote for hidden technical gaps.
11. Product Manager reviews the quote for product scope accuracy.
12. Project Management prepares the client-facing proposal and stores it under `docs/software-company/quotes/`.

## Required Outputs

- A client proposal in `docs/software-company/quotes/YYYY-MM-DD-client-project-quote.md`.
- Updated `docs/software-company/registers/estimation-register.md`.
- Clear inclusions, exclusions, assumptions, and risks.
- Separate lines for build cost, ongoing operating cost, AI/provider usage, hosting/storage, and advertising budgets.

## Pricing Rules

- Separate subscription/product build work from ad spend.
- Separate AI/provider token costs from engineering labor.
- Include a visible buffer for uncertain AI APIs, third-party reviews, platform permissions, app store review, and integration delays.
- Do not promise fixed scope without fixed assumptions.
- Any estimate with high uncertainty must show a low, expected, and high range.

## Quality Gates

- Every estimate has an owner department.
- Every module has hours, assumptions, and risks.
- DevOps has checked hosting, storage, queues, monitoring, and secrets.
- QA has checked regression and release verification needs.
- Architecture has checked scalability, provider limits, and queue/fallback requirements.
- Product has confirmed scope and exclusions.
- Project Management has confirmed price, timeline, milestones, and client-facing wording.
