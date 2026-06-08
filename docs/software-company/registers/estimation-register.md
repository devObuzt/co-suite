# Estimation Register

This register tracks client quote estimates, owner departments, assumptions, risk buffers, and approval status.

| ID | Date | Client / Project | Phase | Module | Owner Department | Low Hours | Expected Hours | High Hours | Rate | Price | Assumptions | Risks | Status |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| EST-001 | TBD | TBD | Discovery | Product scope | Product Manager | TBD | TBD | TBD | TBD | TBD | Scope is not finalized. | Requirements may expand after discovery. | Draft |
| EST-002 | 2026-06-07 | co-Suite Platform | Production MVP | Full MVP stabilization and launch | Project Management | 1,290 | 1,660 | 2,090 | $50/hr | $83,000 expected | Current codebase is starting point; excludes AI usage, ads budget, legal fees, and third-party subscriptions. | Provider limits, Meta/Google review, multilingual media quality, scope growth. | Draft |
| EST-003 | 2026-06-07 | co-Suite Platform | Platform V1 | Full web platform after MVP | Project Management | 2,940 | 3,820 | 4,840 | $50/hr | $191,000 expected | Includes MVP plus campaigns, calendar, billing, admin, advanced generation, agency foundations. | Campaign permissions, billing complexity, queue/provider load, QA scope. | Draft |
| EST-004 | 2026-06-07 | co-Suite Platform | Scale + Mobile | Web platform plus mobile and scale | Project Management | 4,620 | 6,020 | 7,620 | $50/hr | $301,000 expected | Includes Platform V1 plus iOS/Android, advanced automation, scale, deeper ad management. | Mobile duplication, app review, concurrency, security/compliance hardening. | Draft |

## Status Values

- `Draft`: Estimate is being prepared.
- `Needs Review`: Waiting for owner department review.
- `Approved Internally`: Ready to include in client proposal.
- `Sent`: Sent to client.
- `Accepted`: Accepted by client.
- `Rejected`: Rejected or replaced by another proposal.
