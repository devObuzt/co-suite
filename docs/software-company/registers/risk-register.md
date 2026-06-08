# Risk Register

| ID | Risk | Area | Severity | Owner | Mitigation | Status |
|---|---|---|---|---|---|---|
| R-001 | Agents become documentation-only and do not enforce review loops | Process | High | Project Management | Use required handoffs and registers for every feature/release | open |
| R-002 | Architecture drift accumulates because implementation skips planned boundaries | Architecture | High | Architecture | Run architecture re-check after implementation and log drift | open |
| R-003 | QA findings are found once but not re-checked | QA | High | QA | Use QA findings register with re-check date and closure status | open |
| R-004 | co-Suite team starts too many feature areas before stabilizing the production base | Project Delivery | High | Project Management | Start with Milestone 1 Production Stabilization and block new platform scope until gates pass | open |
| R-005 | AI generation failures or provider limits create silent user-facing hangs | AI / Runtime | High | Architecture + DevOps | Require visible job states, queue/retry behavior, provider status, and admin alerting | open |
| R-006 | Media generated locally cannot be previewed or published reliably in production | Media Storage | High | DevOps / Infra | Verify R2/public media flow and make media URL handling part of M1 QA | open |
| R-007 | Mobile UX blocks real customer usage even if desktop works | UX | High | Design + QA | Include mobile dashboard/content/onboarding checks in M1 baseline | open |
| R-008 | Long AI/video/product bulk jobs run inside API background tasks instead of a durable worker | Queue / Runtime | High | DevOps + Developers Manager | Add Railway worker or DB-backed worker, timeout recovery, and concurrency limits before broad customer testing | open |
| R-009 | Billing webhook can accept payment events without verifying the configured webhook secret | Billing / Security | High | Developers Manager + DevOps | Verify `MORNING_WEBHOOK_SECRET` before enabling real Morning payment callbacks | open |
| R-010 | Mobile Suite navigation may still fail discoverability or RTL/theme polish even though required Suite screens are now exposed in the mobile drawer | UX / Navigation | High | Design + Developers Manager | Smoke test the mobile Suite drawer across Home, Connections, Brand/Profile, Create, Content, Analytics, and Product Bulk in LTR/RTL and light/dark themes | ready_for_smoke |
| R-011 | Arabic/Hebrew users see mixed-language or incorrectly directed UI in core Suite flows | UX / Localization | High | Design + Developers Manager + QA | Localize M1 shell labels, verify RTL/LTR mixed-content behavior, and add Arabic/Hebrew smoke tests | open |
| R-012 | Brand/Profile remains read-only after onboarding, preventing users from correcting Suite Memory | Product UX | High | Product Manager + Design + Developers Manager | Implement editable M1 profile sections and ensure manual edits override AI suggestions | open |
| R-013 | Hard-coded dark legacy panels break light theme consistency and reduce readability | UX / Theming | Medium | Design + Developers Manager | Convert M1 surfaces to theme tokens or explicitly QA approved dark studio surfaces in both themes | open |
