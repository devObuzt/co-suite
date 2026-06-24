# Admin Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a protected admin console for users, suites, logs, and provider usage.

**Architecture:** Add admin-only backend models and routes, then expose them through the existing Next dashboard shell. Keep provider cost tracking separate from customer billing events.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, Next.js App Router, TypeScript, Tailwind, lucide-react.

## Global Constraints

- `ADMIN_EMAIL` promotes the first admin.
- Admin APIs require authenticated `is_super_admin` users.
- Never expose password hashes or provider API keys.
- Keep billing events and provider usage events separate.

---

### Task 1: Backend Admin Foundation

**Files:**
- Modify: `api/core/config.py`
- Modify: `api/models/user.py`
- Create: `api/models/admin.py`
- Modify: `api/models/__init__.py`
- Modify: `api/main.py`
- Create: `api/services/admin_audit.py`
- Create: `api/routers/admin.py`
- Modify: `api/routers/__init__.py`
- Test: `tests/test_admin_routes.py`

**Interfaces:**
- Produces: `require_super_admin`, `record_audit_log`, `record_provider_usage`, `/api/v1/admin/*`.

- [ ] Add model fields, startup migrations, and admin route.
- [ ] Add access-control tests and summary/list endpoints.
- [ ] Commit backend foundation.

### Task 2: User Management and Logs

**Files:**
- Modify: `api/routers/admin.py`
- Modify: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `record_audit_log`, `require_super_admin`.
- Produces: user edit/password/delete endpoints and audit listing.

- [ ] Add update, password reset, deactivate/delete endpoints.
- [ ] Record audit logs for admin actions.
- [ ] Commit user management.

### Task 3: Provider Usage Reporting

**Files:**
- Modify: `api/routers/admin.py`
- Modify: `api/routers/marketing_plans.py`
- Modify: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `record_provider_usage`.
- Produces: provider usage summary and request tables.

- [ ] Add period filtering and summaries.
- [ ] Start recording SerpAPI calls from competitor generation.
- [ ] Commit provider usage reporting.

### Task 4: Admin Frontend

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/store/auth.ts`
- Modify: `web/src/app/(dashboard)/layout.tsx`
- Create: `web/src/app/(dashboard)/admin/page.tsx`

**Interfaces:**
- Consumes: `/api/v1/admin/*`.
- Produces: `/admin` console.

- [ ] Add admin API types and client calls.
- [ ] Add admin nav link for super admins.
- [ ] Build dashboard tables and filters.
- [ ] Commit frontend.

### Task 5: Verification

**Files:**
- No new files.

- [ ] Run `pytest -p no:cacheprovider tests/test_admin_routes.py tests/test_marketing_plan_routes.py -q`.
- [ ] Run `npm run build` in `web`.
- [ ] Push.
