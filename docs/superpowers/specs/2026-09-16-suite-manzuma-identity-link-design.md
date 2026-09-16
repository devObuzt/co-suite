# Suite ↔ Manzuma Identity Link Design

## Goal

Make a co-Suite **suite** and a Manzuma **business** the same entity, so every
product in the family can read the strategy of the business it is working for.
The immediate consumer is the Campaigns section being built in OneShare, which
must target the audience described in the suite's marketing plan instead of
asking the customer to re-enter it.

## Why now

OneShare is about to gain campaign creation. Targeting, message and creative
all come from work co-Suite already did for the same customer — but no product
can reach it, because co-Suite is an island: its own users, its own suites with
their own members and roles, and its own Meta connections.

The two systems already model the same thing twice:

| Concept | co-Suite | Manzuma accounts |
|---|---|---|
| Container | `suites` (owner, name, slug) | `organizations` |
| People | `suite_members` (owner/admin/member) | `memberships` (owner/admin/member) |
| Identity | `users` + password + own JWT | Auth.js session, phone/email/OAuth |
| Platform connections | `suites.connections` JSON, **plaintext tokens** | encrypted vault, per-module service keys |

Leaving both in place means every new product pays the same integration tax
twice, and the plaintext tokens stay where they are.

## Decisions

Taken with Wisam on 2026-09-16:

1. **Suite = business**, one-to-one with a Manzuma organization. Accounts is the
   source of truth for identity, membership and subscriptions.
2. **Strategy stays in co-Suite** and is read by other products through one
   internal, read-only endpoint. co-Suite remains the brain; products execute.
3. **Tokens move to the accounts vault.** Suites connected to Meta today
   reconnect once through accounts. No plaintext token is copied between
   databases.
4. **Out of scope on purpose:** the Campaigns section itself, the AI layer that
   proposes campaigns from the marketing plan, unifying co-Suite's generation
   credits with Manzuma billing, and migrating the Google/YouTube connections —
   the last one follows this same pattern later.

## Current state (verified in code, 2026-09-16)

**co-Suite API** (`devObuzt/co-suite`, FastAPI + SQLAlchemy):

- `api/models/user.py` — `users(id, email unique, hashed_password, full_name,
  phone, approval_status, is_super_admin, …)`.
- `api/models/suite.py` — `suites(id, owner_id, name, slug unique, status,
  brand JSON, strategy JSON, connections JSON, …)` and `suite_members(suite_id,
  user_id, role)`.
- `api/core/security.py` — `create_access_token(user_id)` and
  `get_current_user`, a bearer JWT issued by co-Suite itself.
- `api/routers/connections.py` — writes `connections["meta_user_token"]` and
  `connections["facebook"]["page_access_token"]` **in clear text**. The
  repository contains no encryption of any kind.
- `api/services/meta_oauth.py` — uses `settings.meta_app_id`, the same Meta app
  the rest of Manzuma uses (`689045671558325`).
- `api/services/meta_ads_manager.py` — `fetch_campaigns(ad_account_id, token)`
  reads campaigns with their ad sets, ads and insights. Read only; nothing
  creates campaigns today.

**Manzuma accounts** (`devObuzt/manzuma-accounts`, Next.js):

- `GET /api/session` — the one endpoint modules use to learn who is signed in.
  Accepts the shared cookie on `.manzuma.app` or an OIDC bearer, and answers
  with the user, their organizations (with role) and their subscriptions.
- `POST /api/internal/integrations/token` — serves a decrypted provider token
  for an organization (and optionally one asset) to a module authenticated by
  its own service key. `ModuleName` already includes `cosuite`.
- Tokens are stored AES-256-GCM encrypted; the vault logs the caller, the asset
  and the organization, never the token.

**OneShare** (`devObuzt/manzuma-oneshare`, Next.js): reads assets and tokens
through `src/lib/manzuma-client.ts`, and uses a ports interface
(`src/inbox/ports.ts`) wherever a dependency must be swappable in tests.

## Design

### 1. Identity

co-Suite stops being an identity provider.

**Schema** (one Alembic migration):

- `users.manzuma_user_id` — string, unique, nullable.
- `suites.organization_id` — string, unique, nullable.

Both nullable, because the link happens per user as people sign in, not in one
migration night.

**Configuration** (co-Suite):

- `MANZUMA_ACCOUNTS_URL` — `https://accounts.manzuma.app`
- `MANZUMA_SERVICE_KEY` — this module's key; accounts adds `cosuite:<key>` to
  `INTERNAL_SERVICE_KEYS`
- `MANZUMA_SSO` — feature flag, off until the path is proven in production
- `INTERNAL_SERVICE_KEYS` — co-Suite's own map of the products that may call
  its internal endpoint, e.g. `oneshare:<key>,heartbeat:<key>`. Same shape and
  same constant-time comparison accounts uses, so neither side invents a second
  auth scheme.

**Request path.** `get_current_user` gains a second branch, tried first when
`MANZUMA_SSO` is on: if the request carries a Manzuma session — the shared
cookie forwarded by the web app, or an OIDC bearer — co-Suite verifies it with
one server-to-server `GET {MANZUMA_ACCOUNTS_URL}/api/session` call and resolves
the local user from the answer. The legacy password branch stays underneath
during the transition, so an unmigrated user is never locked out.

The verification result is cached in-process for 30 seconds, keyed by a hash of
the credential, never by the credential itself. Nothing about the session is
written to logs beyond the resolved user id.

**Resolving the user**, in order:

1. `users.manzuma_user_id` matches the session's user id → that user.
2. `users.email` matches case-insensitively **and accounts says the email is
   verified** → adopt: write `manzuma_user_id`.
3. `users.phone` matches in E.164 **and accounts says the phone is verified** →
   adopt.
4. Otherwise create a user from the session (email, name, phone) with no
   usable password hash.

The two verification conditions are not decoration. Adoption hands over an
existing suite — its brand, its strategy, its connected accounts — so it may
only follow an identifier this platform itself proved. Accounts publishes
`emailVerified` and `phoneVerified` on the session for exactly this, and a
missing flag reads as *not verified*: the impostor gets their own empty account
instead of somebody else's business.

`approval_status` is **not** forced to `approved`. An adopted user keeps the
status it already had, and a newly created one is approved only when the
session says the organization has an active co-Suite subscription — the
funnel's freeze rule stays exactly as it is, with the subscription as its input
instead of a manual step.

**Resolving the suite.** The session carries the caller's organizations with
their roles. For the active organization:

- an existing suite with that `organization_id` → use it;
- no linked suite, and the caller owns exactly one suite that is not linked to
  any organization → offer to link that suite (explicit confirmation, never
  automatic);
- otherwise → the suite creation flow.

**Roles** come from the Manzuma membership (`owner`, `admin`, `member` map
one-to-one). `suite_members` is no longer written; existing rows stay readable
until the table is dropped in a later change.

**The marketing funnel** (`/startbyconnec`) keeps working anonymously. It is a
lead funnel, not a product surface, and it must not require a Manzuma session.

### 2. The strategy contract

One endpoint, in co-Suite, for every product:

```
GET /internal/v1/suite?organization_id=<manzuma organization id>
Authorization: Bearer <module service key>
```

Authenticated exactly like the accounts vault: one key per module, compared in
constant time, never accepted from a browser.

```json
{
  "suite":  { "id": "...", "name": "...", "status": "active", "updated_at": "2026-09-16T10:00:00Z" },
  "brand":  { "description": "...", "tagline": "...", "services": ["..."] },
  "audience": {
    "language": "ar",
    "demographics": { "age": "25-45", "gender": "all", "social_status": "..." },
    "problem": "...",
    "personas": [
      { "name": "...", "age": 34, "profession": "...", "needs": "...", "challenges": "..." }
    ],
    "keywords": ["..."]
  },
  "marketing_message": "...",
  "content_themes": ["..."]
}
```

- A **summary**, not the raw `strategy` blob: the blob is co-Suite's internal
  shape and changes with its generators. This shape is the published contract.
- `404` when the organization has no linked suite. Consumers read that as "no
  suite yet" and invite the customer to create one — not as an error.
- **Read only.** No product writes strategy. One brain, one writer.
- Versioned in the path, so a future shape lands as `/internal/v2/` instead of
  silently breaking a consumer.

### 3. Tokens

- co-Suite asks the accounts vault for a token at the moment it needs one,
  using `MANZUMA_SERVICE_KEY`, exactly as OneShare does. It stores none.
- `suites.connections` keeps identifiers only — page id, Instagram account id,
  ad account id — and every token key is removed. Those identifiers already
  exist as vault assets, so the column becomes a cache at most.
- No token is ever returned to the browser or written to a log. Every existing
  path in `api/routers/connections.py` that returns a token to the web app is
  closed as part of this work.
- **Migration is a reconnect, not a copy.** When a linked suite has no Meta
  connection in the vault, co-Suite shows "connect Meta from your Manzuma
  account" and links to `accounts.manzuma.app/integrations`. One click, once,
  and the tokens that were sitting in clear text stop being used.

### 4. The OneShare side

- `src/lib/suite.ts` — a typed client for the contract above, shaped like
  `manzuma-client.ts`, with its service key in `COSUITE_SERVICE_KEY`.
- A `strategy` port with two implementations: the real client, and a fake used
  by tests so the Campaigns work can be built and tested without co-Suite
  running.
- An empty state for a business with no suite: what a suite is, and a link into
  the suite creation flow — the `startbyconnec` path **without** the pricing
  proposal.
- **Execution settings stay in OneShare**, per organization: locations, default
  daily budget, currency, the ad account and the page to run from. The suite
  says who to talk to and what to say; OneShare says from where and for how
  much. The strategy has no geography in it, and this is where that gap is
  filled.

## Rollout

Each step ships on its own and can be reverted on its own.

1. **accounts** — add `cosuite:<key>` to `INTERNAL_SERVICE_KEYS`. Environment
   only; the code already knows the module.
2. **co-Suite API** — the migration (two columns), then the session branch
   behind `MANZUMA_SSO=off`, then the accounts client and
   `/internal/v1/suite`. Nothing changes for users while the flag is off.
3. **co-Suite web** — sign in with the Manzuma session when the flag is on, the
   "link this suite to your business" confirmation, and the "connect Meta from
   accounts" empty state.
4. **OneShare** — the suite client, the port, and the no-suite empty state. No
   Campaigns yet; that is the next project.
5. **After it settles** — turn off password sign-in, then strip tokens from
   `suites.connections`. This is the only destructive step, and it runs after
   every linked suite has a vault connection.

## Testing

**co-Suite (pytest):**

- a valid Manzuma session resolves an existing user by `manzuma_user_id`;
- a session whose email matches a legacy user adopts that row exactly once;
- a session for an unknown person creates an approved user with no password;
- an expired or forged session is rejected and never falls through to a
  password branch;
- a suite already linked to another organization is never re-linked;
- `/internal/v1/suite` returns the contract for a linked organization, `404`
  for an unlinked one, and `401` without a valid module key;
- the response contains no token and no raw `strategy` blob.

**OneShare (vitest):**

- the suite client maps the contract to the internal type, including an absent
  `personas` array;
- `404` becomes "no suite" rather than an error;
- a timeout or a 5xx degrades to the saved execution settings and surfaces a
  notice, and never blocks the page.

**Manual QA** follows `AGENTS.md` in this repository: run the `cosuite-qa`
skill over the sign-in, suite-linking and connection flows before calling the
work complete, and state exactly what was checked on production.

## Risks

- **Latency** — a session check on every request. Mitigated by the 30-second
  cache; if accounts is unreachable, an already-cached session keeps working
  for its window and the user sees a clear error after that, not a blank page.
- **Two membership models during the transition** — mitigated by writing only
  Manzuma roles once the flag is on, and treating `suite_members` as read-only
  history.
- **A suite linked to the wrong business** — the unique constraint makes it
  impossible to link two suites to one organization, the link needs an explicit
  confirmation, and every link writes one audit line (`suite_id`,
  `organization_id`, `user_id`).
- **Reconnect friction** — the empty state links straight to the integrations
  page, and the number of suites affected is small enough to handle in a day.
