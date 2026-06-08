# co-Suite M1 Implementation Slice 03 - Review Fix Pass

Date: 2026-06-07  
Owner: Developers Manager - Daniel Farah  
Status: proposed_from_parallel_review  
Milestone: M1 - Production Stabilization  

## Goal

Convert the parallel Architecture, Design, QA, and Developers Manager review into the smallest next execution slice before full QA smoke.

This is not a feature expansion slice. It is a release-confidence slice.

## Ordered Tasks

| Order | Task ID | Owner | Task | Acceptance Criteria |
|---:|---|---|---|---|
| 1 | DEV-G-01 | Developers - Backend Content Lifecycle | Persist reject reason, preserve original post during regeneration, and persist failed publish attempt metadata. | Reject feedback survives refresh/API reload; regenerate never deletes the original before replacement succeeds; publish failures record user-safe metadata. |
| 2 | DEV-G-02 | Developers - Backend Suite Memory | Define and implement M1-safe Suite brand/profile merge semantics. | Profile/brand edits do not accidentally replace unrelated brand JSON; user edits remain protected unless explicitly replaced. |
| 3 | DEV-F-01A | Developers - Frontend Design Hardening | Tokenize dark-only M1 surfaces and reduce hard-coded dark styling where it breaks light theme. | Suite Legacy Dashboard and Product Bulk are readable in light and dark themes. |
| 4 | DEV-F-01B | Developers - Frontend i18n/RTL Hardening | Add suite shell/nav basics to i18n and verify RTL/LTR direction on touched screens. | Suite shell/nav/core labels do not stay English-only in Arabic/Hebrew; mobile 320/360 remains usable. |
| 5 | DEV-D-01 | Developers - Account/Create | Add limited account-level generation without Suite. | Logged-in no-Suite user can generate Quick Post/Ad with `Use brand` off/unavailable and visible job/media/error states. |
| 6 | QA-02A | QA | Run P0 smoke on unblocked flows. | Findings are logged from `QA-M1-007`; blocked provider/storage/credential cases are explicitly marked blocked. |

## Required Reviews

- Architecture reviews DEV-G-01 and DEV-G-02.
- Design reviews DEV-F-01A and DEV-F-01B.
- QA runs P0 smoke after a named local/staging target is available.
- Project Management updates release readiness after QA result.

## Not In This Slice

- Durable queue/worker implementation.
- Full Product Bulk stabilization.
- Campaign builder.
- Native iOS/Android apps.
- Billing/Morning webhook.
- Full SEO/web platform.
- Full localization rewrite beyond M1 touched shell/navigation basics.

