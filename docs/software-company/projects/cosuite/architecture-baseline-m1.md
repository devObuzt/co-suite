# co-Suite M1 Architecture Baseline Review

Date: 2026-06-07  
Owner: Architecture Agent  
Status: baseline_complete  
Milestone: M1 - Production Stabilization  

## Review Scope

This baseline covers the current backend architecture shape for Milestone 1 stabilization, using:

- `docs/software-company/projects/cosuite/product-acceptance-m1.md`
- `docs/software-company/projects/cosuite/milestone-01-production-stabilization.md`
- `docs/architecture/co-suite-architecture-brief.md`
- Targeted code review of Suite, onboarding, generation, content, media, publishing, analytics, and product bulk paths.

M1 should not become a broad architecture rewrite. The required architectural outcome is narrower: stabilize the contracts that make onboarding, Suite Memory, generation jobs, media artifacts, publishing, connections, and analytics understandable and reliable enough for customer testing.

## Current Architecture Shape

### 1. Suite Memory

Current implementation:

- `Suite` is the aggregate root for a customer workspace.
- `Suite.brand`, `Suite.strategy`, and `Suite.connections` are JSON fields on `api/models/suite.py`.
- Onboarding writes directly into `Suite.brand` through full save and step patch endpoints.
- Content generation reads `suite.brand` and `suite.strategy` directly in `api/services/content_generator.py`.
- Product bulk reads `suite.brand` directly in `api/services/product_bulk_generator.py`.
- Regeneration feedback is appended to `suite.brand["content_rules"]` from `api/routers/content.py`.

Architecture assessment:

- This is acceptable for M1 only if treated as a versioned Suite Memory contract, not as an open-ended JSON bag.
- The code already assumes many specific keys: `name`, `industry`, `tone`, `services`, `target_audience`, `colors`, `audience_languages`, `brand_logos`, `brand_personas`, `content_rules`, `usp_points`, `esp_points`, and others.
- The planned architecture calls for a `SuiteContextBuilder`; the current code does not have one. Each service builds its own interpretation of Suite Memory.

M1 baseline contract:

```txt
Suite Memory v0 lives in:
  Suite.brand
  Suite.strategy
  Suite.connections

M1 must document and normalize these sections:
  business_profile
  audience_profile
  brand_profile
  language_profile
  content_rules
  visual_assets
  personas
  products_services
  platform_connections_summary
```

For M1, this can remain physically stored in JSON, but read/write behavior must stop diverging by feature.

### 2. Onboarding And Source Gathering

Current implementation:

- `api/routers/onboarding.py` owns extraction, save, strategy generation, step save, asset upload, asset suggestion, and translation endpoints.
- `extract-brand` gathers URL input and calls `extract_brand_from_sources` or `suggest_brand_identity`.
- `save-brand-step` shallow-merges arbitrary step data into `Suite.brand`.
- `generate-strategy` derives missing audience/value fields and writes `Suite.strategy`.
- Uploaded logos, fonts, and personas are stored through `store_brand_asset`; R2 is required for these uploads.
- Logo/persona images get best-effort width, height, shape, and background metadata.

Architecture assessment:

- Manual continuation is architecturally possible because source gathering and save are separate.
- User edits are not explicitly marked as user-confirmed versus AI-suggested; they simply overwrite keys.
- There is no durable source-gathering record, confidence field, or step revision history.
- The current shallow merge means two UI steps can overwrite adjacent fields without a schema-level guard.

M1 baseline contract:

- Onboarding must treat AI output as suggestions, never as authoritative memory.
- Every save endpoint must preserve user-edited values unless the user explicitly regenerates/replaces a section.
- The frontend/backend handoff must define the exact M1 `Suite.brand` keys and their ownership.
- `research_debug` and `missing_info` are useful and should be surfaced enough to explain weak extraction.

### 3. Generation Jobs

Current implementation:

- `GenerationJob` exists with statuses: `queued`, `waiting_capacity`, `waiting_provider_limit`, `running`, `retrying`, `completed`, `failed`, `cancelled`, `timeout`.
- `api/services/generation_jobs.py` creates, serializes, and updates jobs.
- `api/routers/content.py` creates a job and runs generation through FastAPI `BackgroundTasks`.
- Product bulk generation also uses generation job types in its router path.
- Active jobs are limited per Suite by `get_active_job`.
- Provider limit errors are classified by string matching and marked as `waiting_provider_limit`.

Architecture assessment:

- The UI can show visible queued/running/failed/completed states now.
- The execution boundary is not a durable production queue. FastAPI background tasks can be lost on process restart/deploy and do not provide worker concurrency control.
- There is no real retry scheduler for `waiting_provider_limit`; expired provider-limit jobs are eventually marked failed when active job lookup runs.
- Generation progress is best effort; progress writes are asynchronous and can be skipped if no loop is available.

M1 baseline contract:

- For M1, generation may stay on `BackgroundTasks` only if this limitation is explicitly accepted and user-facing failure states are clear.
- Any long-running provider operation must write a job before starting and must finish in exactly one terminal state.
- M1 should add operational visibility for stuck jobs: active duration, last update, error, provider, model, and retry state.
- Developers Manager should plan a queue/worker slice early if production deploys or video/product bulk jobs are expected during customer testing.

### 4. Media Artifacts

Current implementation:

- `api/services/media_storage.py` supports R2-backed public URLs and local `/static/posts/*` fallback.
- `storage_status()` and `test_public_storage()` can report missing R2 config and public fetch health.
- Generated content stores media as `ContentPost.media_urls` plus optional `ai_metadata.platform_media`.
- Product bulk stores generated media on `ProductBulkAsset.media_url`.
- Content generation catches media generation failures and still creates a pending content post with empty `media_urls`.

Architecture assessment:

- R2 is the right production default and the service already exposes enough diagnostic primitives.
- `ContentPost` does not record artifact status, storage backend, content type, dimensions, or why media is missing.
- The UI cannot reliably distinguish "text-only content", "media generation failed", "storage fell back to local", and "public media ready".
- Product bulk has stronger per-asset status than regular content generation.

M1 baseline contract:

- Any generated media intended for publishing must have a durable public HTTPS URL.
- If media is missing, local-only, or failed, the content card must receive an explicit reason from backend state.
- Publishing must not silently downgrade an image/video post into text-only unless the user explicitly chooses a text-only publish path.

### 5. Publishing

Current implementation:

- `api/routers/content.py` publishes approved/scheduled posts through `api/services/publisher.py`.
- Publisher resolves existing HTTPS media URLs as-is.
- Publisher attempts to upload local `/static` media to R2 if R2 appears configured.
- Facebook can fall back to text-only publishing when media cannot be made public.
- Instagram fails when media is unavailable because Instagram requires media.
- Publish results are returned as mixed success/error keys. A post is marked `published` if either Facebook or Instagram succeeds.

Architecture assessment:

- Publishing is separated from generation at service level, which is good.
- There is no `PublishJob`; publish attempts happen in request lifecycle.
- Partial success is possible, but content status is single-value and cannot represent per-platform success/failure cleanly.
- The product acceptance criterion says the app must not claim publishing succeeded if media was not public or the platform rejected it. Current behavior needs sharper state semantics.

M1 baseline contract:

- Publishing response must distinguish per-platform success, per-platform failure, and warnings.
- A content item should not be globally marked `published` without preserving failed platform states.
- Media readiness must be checked before publish, especially for Instagram and video.
- For M1, a full `PublishJob` can be deferred if synchronous publish remains bounded and visible, but failed/partial publish state must be durable.

### 6. Analytics And Campaign Read

Current implementation:

- Analytics reads `Suite.connections` and returns `error: no_connections` when neither Facebook nor Instagram is connected.
- Meta and Google campaign reads are exposed through connection router endpoints.
- Meta/Google services return campaign arrays plus warning strings on missing connection/API errors.
- Connection data is stored in `Suite.connections` JSON and sanitized before being returned.

Architecture assessment:

- The code has the beginnings of graceful state, but it is not yet a typed connection capability model.
- "Connected" is not separated from "analytics ready", "ads read ready", "publishing ready", or "needs attention".
- Analytics must avoid all-zero misleading dashboards when the actual condition is no permission, no connection, provider error, or unsupported metric.

M1 baseline contract:

- Connections API must expose capability states, not just stored token presence.
- Analytics response must represent data quality explicitly:
  - `ok`
  - `no_connection`
  - `missing_permission`
  - `provider_error`
  - `unsupported`
  - `no_data`
- Campaign read is M1-safe as read-only. Campaign/ad/adset mutation remains outside M1.

### 7. Provider Limits And Queues

Current implementation:

- Provider limit detection is string-based in `classify_provider_limit`.
- Jobs can be marked `waiting_provider_limit` with estimated wait and reset timestamps.
- There is no durable queue worker, provider-level concurrency limiter, or automatic retry runner.
- Product bulk loops over products sequentially and can run many image generations under one request-triggered background process.

Architecture assessment:

- M1 can expose provider wait states, but cannot claim production-grade queueing yet.
- Product bulk and video generation are the highest risk because they are long-running, expensive, provider-limited, and harder to retry safely.

M1 baseline contract:

- At minimum, M1 needs one active generation job per Suite, clear provider-limit state, admin visibility, and a timeout/stuck-job policy.
- Before broader customer testing, queue/worker readiness should be decided by Architecture + DevOps. If no queue is shipped in M1, this must be accepted as release risk.

## Must-Fix Architecture Risks For M1

| ID | Risk | Severity | Why It Matters | Required M1 Fix |
|---|---|---:|---|---|
| ARCH-M1-R01 | Suite Memory is an unversioned JSON contract read differently by onboarding, content generation, product bulk, and regeneration. | High | User edits can be overwritten or ignored; generation quality becomes inconsistent across modes. | Define Suite Memory v0 keys, ownership, and merge rules. Add a small backend normalizer/context builder or equivalent contract before generation changes expand. |
| ARCH-M1-R02 | Generation jobs are persisted, but execution runs through process-local background tasks rather than a durable queue. | High | Deploys/restarts/provider delays can leave jobs stuck or silently lost during customer testing. | Add stuck-job handling, timeout policy, admin/status visibility, and decide whether a real queue/worker is required before M1 release. |
| ARCH-M1-R03 | Media artifact state is not explicit on normal content posts. | High | Review cards can show blank media or allow publishing attempts with local/missing media. | Return explicit media readiness/error/backend state for every generated post. Block or explain publish when public media is unavailable. |
| ARCH-M1-R04 | Publishing uses a single content status for multi-platform partial results. | High | A Facebook success plus Instagram failure can still mark the post as published, hiding failure. | Persist per-platform publish result and keep failed platform state visible. Do not treat partial publish as full success. |
| ARCH-M1-R05 | Analytics and connections do not yet expose typed capability/data-quality states. | Medium | Users may see all-zero or ambiguous dashboards when permissions/config are missing. | Return explicit connection capabilities and analytics state reasons. |
| ARCH-M1-R06 | Regeneration deletes the original post before replacement is generated. | Medium | A failed regeneration can remove reviewable content and lose lifecycle continuity. | Preserve original post until replacement succeeds, or store regenerated-from/replacement relationship with recoverable state. |
| ARCH-M1-R07 | Product bulk generation can be long-running without durable per-item retry orchestration. | Medium | Catalog generation may fail halfway and require clear recovery. | Keep per-item/asset status visible and add retry/resume expectations for failed assets. |

## Architecture Drift Items

| Drift ID | Area | Planned Direction | Current State | M1 Required Correction |
|---|---|---|---|---|
| ADRIFT-M1-001 | Suite Memory | Suite Memory is a structured system of record accessed through a shared context builder. | Direct reads/writes to `Suite.brand` and `Suite.strategy` from multiple services. | Define Suite Memory v0 and normalize generation inputs through one backend function/service. |
| ADRIFT-M1-002 | Generation Workflow | Generation is job/worker based with retry and provider capacity handling. | Jobs exist, but execution is FastAPI background task based. | Add timeout/stuck handling now; queue/worker decision before release. |
| ADRIFT-M1-003 | Media Artifacts | Stored assets have public URL, backend, content type, dimensions, source, and suite linkage. | `ContentPost.media_urls` is a URL list; product bulk has better asset status. | Add M1 media readiness metadata to content responses. |
| ADRIFT-M1-004 | Publishing | Publishing is separate workflow with per-platform result state. | Request lifecycle publish marks global post status on partial success. | Persist per-platform result/error and show partial success. |
| ADRIFT-M1-005 | Connections/Analytics | Connection status separates auth, selected account, publishing, analytics, ads read/write readiness. | `Suite.connections` stores provider JSON; readiness is inferred ad hoc. | Add typed capability state in connection/analytics responses. |

## Recommended First Implementation Slices

### Slice 1: Suite Memory v0 Contract

Owner: Developers Manager + Architecture re-check  
Goal: Stop further divergence before feature fixes.

Deliverables:

- Document exact `Suite.brand` and `Suite.strategy` M1 keys.
- Add a backend `build_suite_context(suite)` or equivalent normalizer used by content generation and product bulk.
- Define merge rules: user-confirmed fields override AI-suggested fields.
- Keep backward compatibility with existing JSON keys.

### Slice 2: Generation Job Reliability Baseline

Owner: Developers Manager + DevOps + Architecture re-check  
Goal: Make job state truthful even if generation fails.

Deliverables:

- Add stuck/timeout detection for active jobs.
- Ensure every generation path writes terminal state on failure.
- Expose latest job details needed by UI/admin: provider, model, stage, error, retry count, age, next retry.
- Decide and document whether M1 ships with process-local background tasks or a real worker queue.

### Slice 3: Media Readiness And Artifact State

Owner: Developers Manager + DevOps  
Goal: Make review and publishing decisions safe.

Deliverables:

- Add media readiness metadata to content response.
- Distinguish public R2 URLs from local fallback URLs.
- Preserve media generation failure reason on `ContentPost.ai_metadata` or a small artifact structure.
- Surface R2 storage health in admin/diagnostic connection state.

### Slice 4: Content Lifecycle And Regeneration Safety

Owner: Developers Manager + QA  
Goal: Prevent user-visible content loss and ambiguous states.

Deliverables:

- Reject flow stores reason and free text.
- Regenerate preserves the original content until replacement succeeds.
- Regeneration feedback is used for the next generation and recorded as a future content rule only after appropriate user action or explicit M1 acceptance.
- Content listing returns newest-first and includes lifecycle timestamps needed by cards.

### Slice 5: Publishing Result Semantics

Owner: Developers Manager + DevOps + QA  
Goal: No false publish success.

Deliverables:

- Preflight media readiness before publish.
- Persist per-platform result and error.
- Represent partial publish separately from full publish.
- Keep text-only external-use path separate from platform publishing.

### Slice 6: Connections And Analytics State

Owner: Developers Manager + DevOps + QA  
Goal: No misleading all-zero dashboards.

Deliverables:

- Add connection capability response fields: auth, selected account, publishing, analytics, ads read, needs attention.
- Analytics returns data-quality states instead of implicit zeroes.
- Campaign reads remain read-only for M1.

### Slice 7: Product Bulk Recovery

Owner: Developers Manager + QA  
Goal: Make large catalog generation recoverable enough for testing.

Deliverables:

- Keep matched/missing image explanation visible after import.
- Ensure failed assets can be regenerated individually.
- Ensure generate-all can resume or skip already generated assets without duplicating good outputs.

## Explicit Gates

### Gate A: Before Risky Backend Implementation Starts

Architecture expects these to be true before developers start changing generation/media/publishing internals:

- Product acceptance criteria are frozen for M1 must-have flows.
- Suite Memory v0 key list and ownership rules are agreed.
- DevOps confirms target production storage posture: R2 configured, local fallback allowed only for development.
- Developers Manager chooses the M1 execution posture for generation:
  - process-local background tasks with accepted risk, or
  - real worker/queue implementation.
- QA has smoke scenarios for onboarding, generation status, media preview, approve/reject/regenerate, publish failure, connections, and analytics permission failure.

### Gate B: Before M1 Release Candidate

These must be true before M1 can be considered release-candidate ready:

- Every user-triggered generation creates a visible job or returns a clear active-job state.
- Jobs do not remain indefinitely active without timeout/stuck handling.
- Generated content cards can explain missing media, failed media generation, and local/non-public media.
- R2/public storage readiness is visible to admin/devops and publishing logic.
- Publishing cannot report full success when any requested platform failed.
- Analytics distinguishes no data from no connection, missing permission, provider error, and unsupported metrics.
- User-edited Suite Memory fields are not silently overwritten by AI regeneration.
- Product bulk import errors identify Excel, ZIP, column, size, and image matching problems.

### Gate C: Before M1 Can Close

Architecture will not sign off M1 closure until:

- Architecture re-check confirms generation/media/Suite Memory changes match this baseline or accepted risk is documented.
- High architecture risks in this document are closed or explicitly accepted in the release readiness process.
- Architecture drift register is updated for any remaining drift that moves to M2.
- QA has passed the smoke tests for the must-have flows or logged accepted release risks.
- DevOps confirms production env, storage, provider, health check, and queue/worker posture.

## Architecture Decision For M1

M1 should stabilize the existing architecture rather than introduce a full new domain model. The most important decision is to formalize contracts around the current JSON and job models:

- Keep `Suite.brand` / `Suite.strategy` for now, but treat them as Suite Memory v0.
- Keep `GenerationJob`, but make lifecycle truthfulness non-negotiable.
- Keep R2 media storage service, but prevent local fallback from masquerading as publish-ready media.
- Keep synchronous publishing for M1 only if per-platform results and errors are durable and visible.
- Keep campaign read-only for M1.

This gives Developers Manager a pragmatic path: stabilize contracts first, then fix user-facing flows without creating hidden architecture debt that blocks M2.
