# OneShare Next Actions

Date: 2026-06-08  
Owner: Project Management  
Status: active  

## Current State

- The active product name is OneShare.
- We are in Milestone 1: Production Stabilization + UX Trust.
- The software-company workflow now has an autonomous delivery loop.
- Recent implementation slices improved:
  - account-level Quick Create;
  - onboarding mobile/RTL polish;
  - multi-logo upload and primary logo selection;
  - Brand/Profile consistency;
  - Create & Generate error feedback;
  - Recent Content action feedback.
- `npm run build` passed after the latest frontend slices.
- No owner action is required right now.

## What Happens Next

The next work happens autonomously in review-fix-smoke mode.

## Department Actions

### Project Management - PM-02

Start now.

Output required:

- Keep this phase active until media preview, product bulk, and QA smoke are stable.
- Decide phase movement only after QA and Architecture re-check.

### QA - QA-03

Start now.

Input:

- Latest slices in `status-log.md`.
- Recent Content action feedback.
- Product Bulk Studio flow.

Output required:

- Re-check media preview for image/video cards.
- Verify whether local-only/R2/missing media states are truthful.
- Create or update QA findings for any failures.

### Developers - DEV-H-01

Start after QA identifies exact media-preview gaps, or immediately if code inspection finds a clear fix.

Input:

- `web/src/components/suite/SuiteLegacyDashboard.tsx`
- `api/services/media_storage.py`
- `api/services/content_generator.py`
- R2/media readiness metadata.

Output required:

- Video/image preview states are accurate and actionable.
- User can open/download media when public media exists.
- User sees a clear reason when media is not previewable.

### Developers Manager - DEVMGR-03

Start in parallel.

Input:

- Latest owner direction.
- Current implementation state.

Output required:

- Create the next implementation slice for Product Bulk Studio stability.
- Include import, matching, first templates, approve template, generate all, and per-item regeneration.

### Architecture - ARCH-02

Start after DEV-H-01 and Product Bulk fixes.

Input:

- Final diff of stabilization slices.
- AI/provider job behavior.
- Media storage behavior.
- Product bulk job behavior.

Output required:

- Architecture drift re-check.
- Decision: okay for broader QA smoke, or return to Developers Manager.

## Current Owner Request

The owner should expect the next useful update to be:

> Media preview readiness result, then Product Bulk Studio stability result, then QA smoke recommendation.

No owner action is required right now unless we need Railway/env access, real provider keys, uploaded sample files, or permission to test external publishing/accounts.
