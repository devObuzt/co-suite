# DevOps Readiness Review - Milestone 1

Date: 2026-06-07  
Owner: DevOps / Infra  
Status: ready_for_review  
Milestone: M1 - Production Stabilization  

## Scope

This review covers the runtime readiness needed before co-Suite Milestone 1 is treated as production-stable for real customer testing.

Sources reviewed:

- `docs/software-company/projects/cosuite/product-acceptance-m1.md`
- `docs/software-company/projects/cosuite/milestone-01-production-stabilization.md`
- `docs/architecture/co-suite-architecture-brief.md`
- `docs/railway-env-vars.md`
- `api/core/config.py`
- `api/engine/config.py`
- `api/main.py`
- `api/requirements.txt`
- `nixpacks.toml`
- `api/services/media_storage.py`
- `api/services/generation_jobs.py`
- `api/routers/content.py`
- `api/routers/product_bulk.py`
- `api/routers/connections.py`
- `api/routers/suites.py`
- `api/routers/billing.py`

## Executive Readiness

M1 is not production-ready until owner-supplied secrets and Railway service changes are completed.

Current runtime shape:

- FastAPI API service runs on Railway through `uvicorn api.main:app --host 0.0.0.0 --port $PORT`.
- PostgreSQL is required through `DATABASE_URL`.
- `/health` exists and returns a simple API liveness response.
- R2 media storage has code-level configuration checks and an authenticated suite-level public storage test.
- Generation jobs have durable DB status rows, but execution currently uses FastAPI `BackgroundTasks`, not a separate durable worker/queue.
- Celery and Redis are installed dependencies, but no worker service, broker URL, or Celery app wiring was found in the reviewed runtime path.
- Billing endpoints exist, but the Morning webhook currently does not verify `MORNING_WEBHOOK_SECRET`.

## Required Environment Variables And Secrets

### Auth And App Runtime

Required for production:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `DATABASE_URL` | Yes | Railway PostgreSQL connection. `api/core/config.py` rewrites `postgresql://` to `postgresql+asyncpg://`. | Must be set by Railway PostgreSQL. |
| `SECRET_KEY` | Yes | JWT signing secret. | Must be strong 32+ character secret; default is unsafe. |
| `FRONTEND_URL` | Yes | CORS origins and OAuth callback base URL. | Must be public HTTPS web domain in production. |
| `DEBUG` | No | Enables FastAPI docs when true. | Keep false in production. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Session lifetime if overridden. | Default is 7 days. |

Web service variable:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Browser API base URL baked into Next.js build. | Must point to `https://<api-domain>/api/v1`; redeploy web after changes. |
| `NIXPACKS_NODE_VERSION` | Recommended | Web build Node version. | Existing env doc recommends `20`. |

Owner action:

- Confirm API `FRONTEND_URL` exactly matches the production web origin.
- Confirm web `NEXT_PUBLIC_API_URL` matches the production API `/api/v1` base.

### Database

Required:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `DATABASE_URL` | Yes | Async SQLAlchemy DB connection. | Required before API starts successfully. |

Runtime notes:

- `api/main.py` creates metadata on startup and performs lightweight `ALTER TABLE` / enum migrations.
- Alembic is installed, but M1 runtime should not rely on ad hoc startup migrations as the long-term migration strategy.
- Railway PostgreSQL backup/restore policy was not found in repo docs.

Owner/Railway action:

- Confirm Railway PostgreSQL plugin is attached to API service.
- Confirm backups/snapshots are enabled or manually documented before customer testing.

### AI Providers

Required for core M1 generation/onboarding:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `ANTHROPIC_API_KEY` | Yes | Brand extraction, strategy, content ideas, and text generation. | Existing Railway doc marks this missing and critical. |
| `AI_TEXT_PROVIDER` | Recommended | Selects `anthropic` or `openai` where supported. | Default is `anthropic`. |
| `ANTHROPIC_TEXT_MODEL` | Recommended | Main Anthropic model. | Default currently `claude-sonnet-4-6`. |
| `ANTHROPIC_FAST_MODEL` | Recommended | Fast Anthropic model. | Default currently `claude-haiku-4-5-20251001`. |

Optional or feature-dependent:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `OPENAI_API_KEY` | Feature-dependent | OpenAI text/image paths. | Required if `AI_TEXT_PROVIDER=openai` or OpenAI image features are used. |
| `OPENAI_TEXT_MODEL` | Recommended when OpenAI enabled | Main OpenAI text model. | Default currently `gpt-5.1`. |
| `OPENAI_FAST_MODEL` | Recommended when OpenAI enabled | Fast OpenAI model. | Default currently `gpt-4.1`. |
| `OPENAI_IMAGE_MODEL` | Feature-dependent | OpenAI image model. | Default currently `gpt-image-1.5`. |
| `GOOGLE_API_KEY` | Feature-dependent, likely M1 required for image/video | Google image/video generation. | Required by legacy engine config and image/video paths. |
| `GOOGLE_IMAGE_MODEL` | Recommended when Google images enabled | Image model. | Default currently `gemini-3.1-flash-preview-image-generation`. |
| `GOOGLE_VIDEO_MODEL` | Recommended when video enabled | Video model. | Default currently `veo-3.1-fast-generate-preview`. |

Important mismatch:

- `api/core/config.py` treats AI keys as optional empty strings.
- `api/engine/config.py` treats `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY` as required at import time.
- M1 should standardize which config module owns production settings to avoid surprises where one feature fails only when a legacy engine module imports.

### Meta

Required for Facebook/Instagram OAuth and publishing:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `META_APP_ID` | Yes for Meta connections | Meta OAuth app ID. | Owner credential required. |
| `META_APP_SECRET` | Yes for Meta connections | Meta OAuth app secret and token debug. | Owner credential required. |

Legacy/manual-publishing variables present in `api/engine/config.py`:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `META_USER_TOKEN_SHORT_LIVED` | No | Legacy/manual token flow. | Not required for suite OAuth flow. |
| `META_USER_TOKEN_LONG_LIVED` | No | Legacy/manual token flow. | Not required for suite OAuth flow. |
| `META_PAGE_ID` | No | Legacy/manual publisher config. | Suite OAuth stores page data per suite. |
| `META_PAGE_NAME` | No | Legacy/manual publisher config. | Suite OAuth stores page data per suite. |
| `META_PAGE_ACCESS_TOKEN` | No | Legacy/manual publisher config. | Suite OAuth stores page token per suite. |
| `META_IG_USER_ID` | No | Legacy/manual publisher config. | Suite OAuth stores IG user ID per suite. |

Readiness notes:

- Meta OAuth scopes include posting, insights, ads read/management, and business management.
- `get_oauth_url` currently builds a URL even if `META_APP_ID` is empty; Developers should add explicit missing-config handling.
- Meta tokens are stored inside `suite.connections`; API responses strip token fields before sending to frontend, but storage encryption/rotation was not verified.

Owner action:

- Create/confirm Meta app.
- Configure valid OAuth redirect URL matching `FRONTEND_URL + /connections/callback`.
- Confirm requested permissions are approved for the app mode used in production.

### Google Ads

Required for Google Ads OAuth/read-only campaign and analytics features:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `GOOGLE_ADS_CLIENT_ID` | Yes for Google Ads | OAuth client ID. | Owner credential required. |
| `GOOGLE_ADS_CLIENT_SECRET` | Yes for Google Ads | OAuth client secret. | Owner credential required. |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Yes for Google Ads API | Google Ads API developer token. | Owner credential required. |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | Conditional | Manager account header when needed. | Required if using MCC/manager hierarchy. |

Readiness notes:

- Google Ads service already rejects missing config and requires HTTPS `FRONTEND_URL`.
- OAuth callback expects `FRONTEND_URL + /connections/google/callback`.
- Refresh tokens are stored per suite in `suite.connections`; response serialization strips token fields.

Owner action:

- Create/confirm Google Cloud OAuth client.
- Add production callback URL.
- Confirm Google Ads developer token status and accessible customer accounts.

### R2 / Media Storage

Required for durable generated media, publishing, product bulk image storage, and public previews:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `R2_ACCOUNT_ID` | Yes | Cloudflare account endpoint. | Owner credential required. |
| `R2_ACCESS_KEY_ID` | Yes | R2 S3 access key. | Owner credential required. |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 S3 secret. | Owner credential required. |
| `R2_BUCKET_NAME` | Yes | Bucket used by API media storage. | Owner credential required. |
| `R2_PUBLIC_URL` | Yes | Public HTTPS base URL for stored media. | Must be HTTPS and externally fetchable. |

Legacy engine R2 variables also exist:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `R2_BUCKET` | Legacy | Legacy engine bucket name. | Different name from `R2_BUCKET_NAME`; standardize before relying on legacy engine paths. |
| `R2_PUBLIC_URL_PREFIX` | Legacy | Legacy public URL prefix. | Different name from `R2_PUBLIC_URL`; standardize before relying on legacy engine paths. |
| `R2_API_TOKEN` | Legacy/optional | Not used by main media storage path. | Do not require unless legacy tooling needs it. |

Readiness notes:

- `api/services/media_storage.py` requires all five main R2 variables.
- If R2 is missing, post media can fall back to local `/static/posts`, but this is not public enough for publishing and may disappear after redeploys.
- Product Bulk image uploads call `store_brand_asset`, which raises if R2 is not configured. Product Bulk Studio therefore requires R2 for M1.
- `/api/v1/suites/{suite_id}/storage-status` reports missing R2 config without exposing secret values.
- `/api/v1/suites/{suite_id}/storage-test` uploads a test object and checks public fetchability.

Owner/Railway action:

- Create R2 bucket and API token with least privileges for that bucket.
- Configure public HTTPS URL, preferably a stable custom domain rather than temporary/dev-only URL.
- Run storage test after deploy using an authenticated suite owner account.

### Workers / Queues

Required for production-stable long AI/video/product bulk jobs:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `REDIS_URL` or broker URL | Needed for real worker queue | Broker for Celery/RQ/Arq if implemented. | Not documented or wired in current runtime. |
| Worker concurrency limits | Needed for provider/cost control | Cap simultaneous text/image/video/product jobs. | Not present in env docs. |
| Queue visibility/alert settings | Needed for ops | Alert on failed/stuck jobs and queue age. | Not present in env docs. |

Current implementation:

- `GenerationJob` rows provide visible statuses: `queued`, `running`, `waiting_provider_limit`, `retrying`, `failed`, `completed`, and others.
- Content generation and Product Bulk generation are launched through FastAPI `BackgroundTasks`.
- Only one active generation job per suite is allowed by `get_active_job`.
- Provider limit classification maps 429/quota/resource exhaustion to `waiting_provider_limit` with a default 120 second wait.

Readiness gap:

- `BackgroundTasks` are not a durable queue. Jobs can be interrupted by deploys/restarts, API timeouts, or process crashes.
- No separate Railway worker service was found.
- No Redis/broker variable or queue worker command was found.
- No sweeper was found to recover old `queued`/`running` jobs after process failure.

M1 decision:

- For controlled internal testing, DB-backed job status plus `BackgroundTasks` may be accepted as a short-term risk.
- For real customer testing with video and Product Bulk enabled, a Railway worker service or DB-backed job runner is a blocker.

### Billing

Billing is present in API routes and models, but M1 scope excludes advanced billing packages.

Variables:

| Variable | Required | Purpose | Readiness |
|---|---:|---|---|
| `MORNING_API_KEY` | Future/feature-dependent | Morning payment integration. | Documented but not used in reviewed webhook path. |
| `MORNING_WEBHOOK_SECRET` | Required before accepting real payments | Verify Morning webhook authenticity. | Config exists, but webhook currently does not verify it. |
| `MORNING_SUBSCRIBE_URL` | Required for production billing links | Subscription payment page. | Falls back to `https://morning.co.il` if empty. |
| `MORNING_PAY_URL` | Required for production pay-balance links | Balance payment page. | Falls back to `https://morning.co.il` if empty. |

Readiness gap:

- `api/routers/billing.py` accepts Morning webhook JSON without verifying `MORNING_WEBHOOK_SECRET`.
- Do not enable real payment webhooks until signature/secret verification is implemented and tested.

## Railway / Runtime Readiness

### API Service

Ready:

- `nixpacks.toml` sets Python `3.12`.
- Start command uses Railway `$PORT`.
- FastAPI `/health` endpoint exists.
- `api/requirements.txt` and root `requirements.txt` include the same backend dependencies.

Needs confirmation:

- Railway health check should target `/health`.
- API service variables must include `DATABASE_URL`, `SECRET_KEY`, `FRONTEND_URL`, AI keys, R2 keys, and integration keys for enabled features.
- Production should run with `DEBUG=false`.
- Logs should be retained long enough to diagnose failed generation/provider incidents.

Potential build/runtime dependency notes:

- `uvicorn[standard]`, `asyncpg`, `boto3`, `Pillow`, `openpyxl`, Anthropic, Google GenAI, Celery, and Redis Python dependencies are present.
- No Dockerfile was found; Nixpacks is the active runtime configuration.
- Image/video generation may need additional system packages depending on provider outputs and post-processing paths. Current reviewed paths use Python libraries and remote providers.

### Web Service

Needs confirmation:

- `NEXT_PUBLIC_API_URL` must be set before building and deploying the web service.
- Any change to this variable requires a web redeploy because it is baked into the frontend bundle.
- Web and API domains must be mutually consistent for CORS and OAuth callbacks.

### Database

Needs confirmation:

- Railway PostgreSQL service exists and is attached.
- Backups/snapshots are enabled before real customer testing.
- M1 should move toward explicit migrations; startup schema mutation is acceptable only as short-term stabilization debt.

### Health Checks

Current:

- `/health` returns only process/app liveness.
- Storage diagnostics exist behind authenticated suite endpoints.

M1 recommendation:

- Keep `/health` lightweight for Railway liveness.
- Add or expose an admin-only readiness endpoint that checks DB connection, R2 configured status, AI key presence, and worker/queue status without exposing secret values.
- Do not make provider network calls in the Railway liveness check; use separate diagnostics to avoid killing healthy API instances during provider outages.

## Media Storage And Public URL Readiness

R2 is mandatory for M1 features that publish or review generated media reliably.

Readiness criteria:

- All five main R2 variables are set.
- `R2_PUBLIC_URL` starts with `https://`.
- Storage test can upload an object and fetch it publicly.
- Generated media URLs stored on content/product assets are absolute public URLs when needed for publish/download/preview.
- Local `/static/posts` fallback is disabled or treated as diagnostic-only in production.

Blockers:

- Product Bulk image ingestion cannot work without R2 because `store_brand_asset` raises when storage is not configured.
- Meta/Instagram publishing cannot reliably fetch local media URLs.
- Generated local media may be lost on redeploy.

Recommended M1 implementation:

- Add a startup/admin diagnostic that reports `storage_status()`.
- In production, fail media generation/publishing clearly when R2 is missing instead of silently falling back to local storage for publishable media.
- Standardize R2 env names across `api/core/config.py` and `api/engine/config.py`.

## Queue / Worker Readiness For Long Jobs

M1 must treat long AI/video/Product Bulk work as an operational risk until a durable worker path exists.

Current job types and runtime behavior:

| Flow | Current runtime path | Risk |
|---|---|---|
| Content generation | API creates `GenerationJob`, then runs FastAPI background task. | Lost/stuck jobs on API restart or deploy. |
| Regeneration | Same background task path. | Same risk. |
| Product Bulk generate first | API background task. | Slow/heavy provider work in API process. |
| Product Bulk generate all | API background task. | High risk for 500 rows / many assets. |
| Product Bulk asset regenerate | API background task. | Same risk. |
| Video generation | Routed through generation services/providers. | Expensive/slow; needs concurrency and cost controls. |

Minimum M1 requirement before broad testing:

- Add a separate Railway worker service or DB-backed polling worker.
- Add worker command, queue/broker env vars, and concurrency limits.
- Add recovery for jobs stuck in `queued`/`running` beyond a timeout.
- Add retry policy that distinguishes provider limit from permanent failures.
- Add admin-visible job list with status, age, provider, model, error, retry time, and suite/user impact.

Short-term acceptable internal-only path:

- Keep `BackgroundTasks`.
- Limit customer test group and disable heavy Product Bulk all/video workflows by policy or feature flag.
- Monitor logs manually during tests.
- Clear stuck jobs manually in DB if needed.

## Provider Limit / Outage Handling And Admin Alerts

Current readiness:

- Provider limit classifier detects common rate-limit terms: `rate limit`, `429`, `quota`, and `resource exhausted`.
- Jobs can move to `waiting_provider_limit`.
- The UI can poll generation status endpoints for visible states.

Gaps:

- No admin alert route/service was found for provider outage or repeated job failures.
- No queue depth, job age, provider failure rate, or cost dashboard was found.
- Provider wait is generic 120 seconds; provider-specific retry-after headers are not used in the reviewed helper.
- No fallback provider policy is documented for Anthropic/OpenAI/Google image/video failures.
- Meta and Google Ads errors are returned as warnings/errors, but admin alerting is not present.

M1 admin alert needs:

- Alert when job failure rate crosses a threshold in a rolling window.
- Alert when any job remains `running` longer than the configured timeout.
- Alert when provider-limit waits affect multiple suites.
- Alert when R2 storage test fails in production.
- Alert when OAuth callbacks fail repeatedly for Meta or Google Ads.
- Alert when billing webhook verification fails once billing is enabled.

Recommended channels:

- Start with Railway logs plus a simple admin dashboard.
- Add email/Slack/Telegram only after owner chooses the operational channel and supplies credentials.

## Concrete Blockers Requiring Owner Credentials Or Railway Changes

Owner credentials required:

- `ANTHROPIC_API_KEY` for core M1 AI text/brand/generation flows.
- `GOOGLE_API_KEY` for image/video paths if those M1 modes remain enabled.
- `OPENAI_API_KEY` if OpenAI text/image provider paths are enabled.
- Cloudflare R2 account, bucket, access key, secret key, and public HTTPS URL.
- Meta app ID/secret and approved OAuth redirect URLs/permissions.
- Google OAuth client ID/secret and Google Ads developer token.
- Morning URLs/secrets before real billing is enabled.

Railway/service changes required:

- Confirm API service health check path `/health`.
- Confirm API `FRONTEND_URL` and web `NEXT_PUBLIC_API_URL` are production domains and redeploy web after changes.
- Attach Railway PostgreSQL and enable backups/snapshots.
- Add separate worker service or DB-backed worker process before broad customer testing with video/Product Bulk.
- Add Redis or a selected broker if the team chooses Celery/RQ/Arq rather than DB-backed polling.
- Set production log retention/observability expectations.

Do not launch broad customer tests until these are resolved:

- R2 public storage passes upload plus public fetch test.
- Core AI key is set and smoke-tested.
- OAuth credentials are set for any platform shown as connectable in production.
- Long job strategy is accepted explicitly: durable worker implemented, or internal-only limited test risk accepted.
- Billing webhook verification is implemented before real payments.

## Recommended First Implementation Slices For Developers Manager

1. Runtime diagnostics slice

- Add admin/readiness endpoint that checks DB connectivity, config presence by feature, R2 status, and worker/queue mode.
- Reuse `storage_status()` and avoid returning secret values.
- Surface missing config cleanly in Connections and internal diagnostics.

2. R2 production media slice

- Standardize R2 env variable names across current and legacy config modules.
- Make publishable media require R2 in production.
- Add QA script or endpoint flow for upload plus public fetch.
- Ensure content and Product Bulk assets store durable absolute URLs.

3. Worker/queue slice

- Choose DB-backed worker for fastest M1 path or Redis/Celery if Railway Redis is approved.
- Move content, regeneration, product bulk first/all, and asset regeneration out of FastAPI `BackgroundTasks`.
- Add job timeout recovery and stuck-job handling.
- Add worker concurrency limits by job type.

4. Provider resilience slice

- Normalize provider errors into user/admin-safe codes.
- Use provider retry-after data where available.
- Add provider incident/admin alert records.
- Add fallback/disable switches for image/video/product bulk when provider capacity is exhausted.

5. Integration config hardening slice

- Add explicit Meta missing-config checks before returning OAuth URLs.
- Keep Google Ads current missing-config behavior.
- Add per-platform `configured`, `connected`, and `needs_attention` states.
- Add token age/permission validation checks where provider APIs allow it.

6. Billing safety slice

- Verify `MORNING_WEBHOOK_SECRET` before accepting payment webhooks.
- Do not enable production payment callbacks until verification is tested.
- Replace fallback Morning URLs with explicit missing-config state in production.

7. Railway operations slice

- Document API/web service names, domains, health check, env ownership, and redeploy steps.
- Add backup/restore notes for Railway PostgreSQL.
- Add manual incident runbook for failed deploy, provider outage, R2 failure, and stuck jobs.

## M1 DevOps Gate Decision

Status: conditional fail for production-stable launch; acceptable for continued internal stabilization.

Pass conditions:

- Required secrets are set for enabled features.
- R2 public storage test passes.
- Railway API/web env values are confirmed and web is redeployed after env changes.
- Long-job worker/queue plan is implemented or formally accepted as limited internal-test risk.
- Provider/admin alert path is at least minimally operational.
- Billing webhooks are not enabled until secret verification exists.
