# Department Managers

Last updated: 2026-06-07

Every department has a named manager. The manager owns department judgment, signs off department summaries, and writes or approves the department section in owner-review files.

These names are operating identities for the software-company workflow. They make accountability explicit and portable across projects.

| Department | Manager Name | Role |
|---|---|---|
| Project Management | Layla Haddad | Runs the delivery loop, task board, handoffs, owner-review cadence, release decisions, and cross-department coordination. |
| Product Management | Omar Nassar | Owns product outcome, scope, user value, product assumptions, acceptance criteria, pricing/packaging intent, and brand-intake questions when inputs are missing. |
| Architecture | Mira Cohen | Owns system boundaries, data flow, scalability, integration contracts, queue/provider risk, architecture reviews, and drift control. |
| Design / Design System | Noa Barak | Owns UX flow, visual direction, design system, brand translation into UI, language direction, mobile behavior, and UI quality gates. |
| DevOps / Infra | Kareem Mansour | Owns environments, deployment, secrets, storage, queues, monitoring, provider limits, backups, and runtime reliability. |
| Developers Manager | Daniel Farah | Converts approved product/design/architecture work into implementation slices and assigns engineering ownership. |
| Developers | Rami Saleh | Owns implementation quality, tests, code health, and local verification for assigned slices. |
| QA | Lina Saad | Owns smoke/regression testing, findings, re-check loops, release readiness evidence, and QA sign-off. |

## Owner-Review Rule

When a department changes something meaningful, that department manager must provide the relevant section in the owner-review summary.

Examples:

- Product scope change: Omar writes the Product section.
- New visual direction: Noa writes the Design section.
- Queue/provider risk: Mira and Kareem write Architecture/DevOps sections.
- Release smoke result: Lina writes the QA section.
- Implementation completed: Daniel and Rami write Developers Manager / Developers sections.

## Future Conversation Rule

When department-specific chat threads are added later, each thread should be owned by the named department manager and linked back to the project control room.
