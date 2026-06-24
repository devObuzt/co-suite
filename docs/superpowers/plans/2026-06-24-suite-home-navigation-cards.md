# Suite Home Navigation Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Suite home page as four designed navigation boxes for strategy, generation/creation, data repository, and settings/connections.

**Architecture:** Keep the work in the existing `web/src/app/(dashboard)/suite/[id]/page.tsx` route. Use local data arrays for localized section copy and links, and keep current API calls for Suite, connections, and storage readiness.

**Tech Stack:** Next.js App Router, React client component, existing API helper, lucide-react icons, Tailwind utility styling.

## Global Constraints

- Change the Suite home page only.
- Keep the sidebar and mobile top navigation unchanged.
- Keep visible copy localized for Arabic, Hebrew, and English.
- Reuse existing routes and API calls.

---

### Task 1: Replace Suite Home Action Grid

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`

**Interfaces:**
- Consumes: existing `api.suites.get`, `api.connections.get`, and `api.suites.storageStatus`.
- Produces: four visual navigation boxes with child links to existing routes.

- [x] Define localized labels for the four boxes.
- [x] Replace `HealthCard` and `HomeAction` layout with section cards.
- [x] Preserve readiness signals for brand, Meta, Google Ads, and storage where relevant.
- [x] Include future placeholders for logs, leads, and customers without creating broken routes.

### Task 2: Verification

**Files:**
- Verify: `web/src/app/(dashboard)/suite/[id]/page.tsx`

- [ ] Run `cd web && npm run build`.
- [ ] Commit the web change.
- [ ] Push web and root if the gitlink changes.
