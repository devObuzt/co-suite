# Marketing Plan Compact UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the marketing plan page more compact, easier to scan, and lightly color-coded.

**Architecture:** Implement the change inside `web/src/components/marketing-plan/MarketingPlanStages.tsx`. Keep API contracts unchanged and pass preview/detail state through existing `detail` props.

**Tech Stack:** Next.js, React, TypeScript, Tailwind, lucide-react.

## Global Constraints

- Main page cards must be compact by default.
- Detail pages must remain expanded.
- The stage detail navigation must be a small icon in the card header.
- Do not add noisy decoration or nested card structures.
- Preserve RTL/mobile behavior.

---

### Task 1: Compact stage previews

**Files:**
- Modify: `web/src/components/marketing-plan/MarketingPlanStages.tsx`

**Interfaces:**
- Consumes: existing `detail?: boolean` prop on stage components.
- Produces: compact preview behavior on non-detail pages.

- [ ] Limit services to 3 visible items when `detail` is false.
- [ ] Keep keywords collapsed to two rows by default.
- [ ] Limit competitors to the first populated source when `detail` is false.
- [ ] Add show-more controls where hidden content exists.

### Task 2: Header icon navigation and stage tones

**Files:**
- Modify: `web/src/components/marketing-plan/MarketingPlanStages.tsx`

**Interfaces:**
- Consumes: `StageSlug`.
- Produces: tone-aware `StageBox` styling and compact header detail link.

- [ ] Add a tone map by stage slug.
- [ ] Apply subtle stage tint to icon, border, and card background.
- [ ] Keep the detail link as a small accessible icon button in the header.

### Task 3: QA

**Files:**
- Verify: `web/src/components/marketing-plan/MarketingPlanStages.tsx`

- [ ] Run `npm run build` in `web`.
- [ ] Run a mobile-width browser check when local app/browser tooling is available.
- [ ] Confirm no API code changed.
