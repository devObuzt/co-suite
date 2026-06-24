# Admin Console Design

## Goal

Build a protected admin console for co-Suite operators to inspect and manage users, suites, logs, provider usage, tokens, and operational costs.

## Scope

The first release adds a super-admin gate, a dashboard at `/admin`, user/suite management, audit logs, and provider usage reporting. It keeps customer billing events separate from internal provider cost tracking.

## Access Model

- Add `ADMIN_EMAIL` to environment config.
- Add `is_super_admin` to `users`.
- On startup and on login, the user whose email matches `ADMIN_EMAIL` is promoted to super admin.
- All admin endpoints require an authenticated active user with `is_super_admin = true`.

## Data Model

Add `audit_logs`:
- actor user id and email
- action, resource type, resource id
- optional suite id and target user id
- metadata JSON
- IP address and user agent
- created timestamp

Add `provider_usage_events`:
- provider, model, endpoint, operation
- status
- input/output/total tokens
- actual cost USD
- suite id, user id, generation job id
- latency, request id, metadata
- created timestamp

Use existing `users`, `suites`, `generation_jobs`, and `usage_events` for summaries.

## Admin API

- `GET /api/v1/admin/summary`
- `GET /api/v1/admin/users`
- `GET /api/v1/admin/users/{user_id}`
- `PATCH /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/password`
- `DELETE /api/v1/admin/users/{user_id}`
- `GET /api/v1/admin/audit-logs`
- `GET /api/v1/admin/provider-usage`
- `GET /api/v1/admin/provider-usage/summary`

Admin responses must never expose password hashes or provider API keys.

## UI

Add `/admin` inside the existing dashboard shell:
- overview cards for users, suites, jobs, provider cost, billed amount
- users table with suite counts and actions
- selected user drawer/section with owned suites
- audit log table
- provider usage summary and request table with date filters: today, yesterday, week, month, all, custom

The UI is operational, dense, and scan-friendly. It does not use marketing-style landing sections.

## Testing

- Unit/API tests verify admin access control.
- Tests verify user edit, password reset, audit log creation, and provider usage filtering.
- Web build must pass.
