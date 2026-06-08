# QA Findings Register

QA must log findings here and re-check them until each item is closed, deferred, or accepted as risk.

## Status Values

- `open`: QA has logged the finding and it needs owner action.
- `fix_in_progress`: owner is actively working on the fix.
- `ready_for_recheck`: owner reports the fix/configuration is ready and QA must verify again.
- `closed`: QA re-checked and confirmed the issue is resolved.
- `deferred`: not fixed in this release; must have an owner and target milestone.
- `accepted_risk`: release owner accepted the risk explicitly.

## Severity Definitions

| Severity | Definition | Release Impact |
|---|---|---|
| Critical | Blocks signup/login, Suite access, data save, generation start/result visibility, or publishing/media truthfulness for the primary M1 journey. Includes security/privacy exposure or destructive data loss. | Blocks release unless formally accepted as risk. |
| High | Breaks a must-have flow for a meaningful user segment, causes misleading success/failure state, hides actionable integration errors, or blocks mobile review of core content. | Blocks release unless closed or formally accepted as risk. |
| Medium | Degrades a must-have flow but has a reasonable workaround, unclear copy, partial state sync issue, or non-blocking UX issue in desktop/mobile/RTL. | Can release only with owner, mitigation, and re-check date. |
| Low | Cosmetic, polish, minor copy, or low-risk consistency issue that does not change user understanding or task completion. | Does not block release. |

## M1 Initial Findings

| ID | Date | Severity | Area | Finding | Repro Steps | Expected | Actual | Owner | Status | Re-check Date | Resolution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QA-M1-001 | 2026-06-07 | Critical | AI / Runtime Config | `ANTHROPIC_API_KEY` is documented as missing in Railway env notes; brand extraction, strategy generation, and content generation will fail if still absent in the target environment. | Check target API service env against `docs/railway-env-vars.md`, then run onboarding extraction or content generation smoke. | Required AI provider config is present, or UI shows a clear provider/config unavailable state without raw 500/silent failure. | Documentation says key is missing and generation-related paths fail with 500 without it. | DevOps / Infra | open | TBD | Pending DevOps confirmation and QA re-check. |
| QA-M1-002 | 2026-06-07 | High | Media Storage / Publishing | R2/media storage readiness is not yet confirmed for publishable generated media, creating risk that media previews or publishing rely on local/non-durable URLs. | Check R2 env variables and run generated image/video preview plus publish-readiness smoke. | Publishable media has durable public URLs; if storage is absent, publishing explains the limitation and does not claim success. | Existing risk register flags media URL reliability; R2 variables are optional and require environment confirmation. | DevOps / Infra | open | TBD | Pending R2 readiness evidence and QA re-check. |
| QA-M1-003 | 2026-06-07 | High | Generation Jobs | M1 acceptance requires queued/running/failed/completed job states; any generation button that appears to do nothing is a release blocker. | Submit Quick Post/Ad generation, image generation, video generation, and product bulk generation where providers are configured. | Every generation path shows visible job/loading/failure/completed status and remains recoverable after refresh where applicable. | Baseline not executed yet; risk register flags silent AI/provider hangs as high risk. | Developers Manager / Architecture / DevOps | open | TBD | Convert to concrete repro rows during first smoke execution if a path fails. |
| QA-M1-004 | 2026-06-07 | High | Connections / Analytics | Missing Meta/Google permissions or config must not appear as successful connection or all-zero analytics. | Open Connections and Analytics with no provider credentials, then repeat with test credentials when available. | User sees `not connected` or `needs attention`; analytics distinguishes no data from no permissions/API failure. | Product acceptance lists misleading all-zero analytics and failed connection states as M1 risks requiring QA coverage. | Developers Manager / DevOps | open | TBD | Pending credential availability and QA execution. |
| QA-M1-005 | 2026-06-07 | High | Mobile / RTL | M1 requires mobile Suite navigation and content review to be usable, including RTL; current release cannot pass until this is smoke-tested. | On mobile viewport, log in, open Suite, navigate Suite screens, review content, approve/reject, switch Arabic/Hebrew where available. | Menu does not permanently cover content; cards fit width; buttons/tabs are tappable; RTL is readable. | Baseline not executed yet; risk register flags mobile UX as high release risk. | Design / QA | open | TBD | Pending mobile smoke execution. |
| QA-M1-006 | 2026-06-07 | High | Web Build / Smoke Environment | Local web production build hangs under `DEVOPS-02`, preventing production-build smoke execution for M1 Slice 01. | From `web`, move stale `.next` aside and run a clean `npm run build` under a watchdog. | Production build completes or fails with actionable diagnostics so QA can smoke the build artifact/runtime. | Clean build inside sandbox failed because Turbopack could not spawn/bind its helper process; clean build outside sandbox completed successfully. | DevOps / Developers | closed | 2026-06-07 | Resolved as local stale `.next` cache plus sandbox permission issue. Production-build smoke is unblocked. |

## M1 Finding Template

Use the next available ID in the form `QA-M1-007`, `QA-M1-008`, and so on.

| ID | Date | Severity | Area | Finding | Repro Steps | Expected | Actual | Owner | Status | Re-check Date | Resolution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QA-M1-XXX | YYYY-MM-DD | Critical/High/Medium/Low | Area | Concise user-facing problem. | 1. Step one 2. Step two 3. Step three | What should happen. | What happened. | Named owner/team | open | YYYY-MM-DD or TBD | Pending fix/re-check notes. |
