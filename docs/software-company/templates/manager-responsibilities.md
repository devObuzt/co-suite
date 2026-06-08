# Manager Responsibilities Template

Last updated: 2026-06-08

Copy this into a project README or project operating note when a project needs explicit ownership.

| Department | Manager | Owns | Must Produce |
| --- | --- | --- | --- |
| Project Management | Layla Haddad | Phase movement, task board, handoffs, owner-review cadence, release decision. | Current phase, blocker summary, next owner, owner-review report. |
| Product Management | Omar Nassar | User value, scope, assumptions, acceptance criteria, brand/product questions. | Product brief, must/should/later scope, acceptance criteria, accepted tradeoffs. |
| Architecture | Mira Cohen | System boundaries, data flow, integrations, security/scaling risk, drift control. | Architecture review, re-check notes, drift entries. |
| Design / Design System | Noa Barak | UX flow, visual direction, responsive behavior, content clarity, UI quality. | Design baseline, QA notes for UI, responsive/RTL/LTR checks when relevant. |
| DevOps / Infra | Kareem Mansour | Environments, deploys, secrets, queues, storage, monitoring, provider limits. | Runtime checklist, deploy notes, incident/dependency risks. |
| Developers Manager | Daniel Farah | Implementation sequencing, task slicing, developer handoffs, review readiness. | Slice plan, dependency map, verification commands. |
| Developers | Rami Saleh | Code implementation, tests, local verification, implementation notes. | Code change summary, test/build output, handoff notes. |
| QA | Lina Saad | Smoke/regression testing, defect records, re-check loops, release gates. | QA matrix, findings, release gate recommendation. |

## Manager Rules

- One task has one accountable department, even when several departments contribute.
- A task can move to `done` only when its acceptance criteria are verified or risk is explicitly accepted.
- `needs_review` means the owner department believes the task is complete enough for the next department to inspect.
- `ready_for_handoff` means the next department is named and has enough context to act.
- `accepted_risk` requires a dated note explaining who accepted it and why.
