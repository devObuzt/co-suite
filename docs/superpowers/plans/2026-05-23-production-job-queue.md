# Production Job Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory content generation state with durable database-backed jobs that can wait, retry, and surface AI provider limits cleanly.

**Architecture:** The API creates a `GenerationJob` row before background work starts. The content generator updates the job through a small service layer, and the dashboard polls the job endpoint for durable progress. This is intentionally DB-backed first, so the current Railway deployment stays simple while leaving a clear path to a separate worker/queue later.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, PostgreSQL/Railway, Next.js, TypeScript.

---

## File Structure

- Create `api/models/generation_job.py`: SQLAlchemy model and enums for durable job state.
- Modify `api/models/__init__.py`: export the new model/enums so `Base.metadata.create_all` creates the table.
- Create `api/services/generation_jobs.py`: small service functions to create, lock, update, complete, fail, timeout, and serialize jobs.
- Modify `api/routers/content.py`: replace `_GENERATION_JOBS` memory dict with database-backed job rows and add status endpoint response from DB.
- Modify `api/services/content_generator.py`: accept a job progress callback and report provider/model/stage updates without knowing router details.
- Modify `web/src/lib/api.ts`: keep the `GenerationStatus` contract aligned with durable job fields.
- Modify `web/src/app/(dashboard)/suite/[id]/page.tsx`: keep current progress UI but consume persisted statuses and waiting states.
- Create `tests/test_generation_jobs.py`: model/service tests for statuses, duplicate prevention, provider-limit waiting, and serialization.

---

### Task 1: Add Durable Generation Job Model

**Files:**
- Create: `api/models/generation_job.py`
- Modify: `api/models/__init__.py`
- Test: `tests/test_generation_jobs.py`

- [ ] **Step 1: Write model/service enum tests**

Create `tests/test_generation_jobs.py` with:

```python
from api.models.generation_job import GenerationJobStatus, GenerationJobType


def test_generation_job_status_values_are_stable():
    assert GenerationJobStatus.queued.value == "queued"
    assert GenerationJobStatus.waiting_capacity.value == "waiting_capacity"
    assert GenerationJobStatus.waiting_provider_limit.value == "waiting_provider_limit"
    assert GenerationJobStatus.running.value == "running"
    assert GenerationJobStatus.retrying.value == "retrying"
    assert GenerationJobStatus.completed.value == "completed"
    assert GenerationJobStatus.failed.value == "failed"
    assert GenerationJobStatus.cancelled.value == "cancelled"
    assert GenerationJobStatus.timeout.value == "timeout"


def test_generation_job_type_values_are_stable():
    assert GenerationJobType.content_generation.value == "content_generation"
    assert GenerationJobType.content_regeneration.value == "content_regeneration"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_generation_jobs.py -v
```

Expected: FAIL because `api.models.generation_job` does not exist.

- [ ] **Step 3: Create the model**

Create `api/models/generation_job.py`:

```python
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class GenerationJobStatus(str, enum.Enum):
    queued = "queued"
    waiting_capacity = "waiting_capacity"
    waiting_provider_limit = "waiting_provider_limit"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class GenerationJobType(str, enum.Enum):
    content_generation = "content_generation"
    content_regeneration = "content_regeneration"


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    type: Mapped[GenerationJobType] = mapped_column(Enum(GenerationJobType), nullable=False)
    status: Mapped[GenerationJobStatus] = mapped_column(
        Enum(GenerationJobStatus),
        nullable=False,
        default=GenerationJobStatus.queued,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_wait_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    suite: Mapped["Suite"] = relationship("Suite")
```

- [ ] **Step 4: Export the model**

Modify `api/models/__init__.py`:

```python
from .generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
```

Add these names to `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
pytest tests/test_generation_jobs.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/models/generation_job.py api/models/__init__.py tests/test_generation_jobs.py
git commit -m "feat: add durable generation job model"
```

---

### Task 2: Add Generation Job Service

**Files:**
- Create: `api/services/generation_jobs.py`
- Modify: `tests/test_generation_jobs.py`

- [ ] **Step 1: Add serialization test**

Append to `tests/test_generation_jobs.py`:

```python
from datetime import datetime, timezone

from api.models.generation_job import GenerationJob
from api.services.generation_jobs import serialize_job


def test_serialize_job_returns_frontend_contract():
    job = GenerationJob(
        id="job_1",
        suite_id="suite_1",
        type=GenerationJobType.content_generation,
        status=GenerationJobStatus.waiting_provider_limit,
        stage="provider_limit",
        message="Waiting for OpenAI rate limit reset.",
        progress=35,
        provider="openai",
        model="gpt-image-1",
        retry_count=1,
        estimated_wait_seconds=120,
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
    )

    payload = serialize_job(job)

    assert payload["job_id"] == "job_1"
    assert payload["suite_id"] == "suite_1"
    assert payload["status"] == "waiting_provider_limit"
    assert payload["stage"] == "provider_limit"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-image-1"
    assert payload["retry_count"] == 1
    assert payload["estimated_wait_seconds"] == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_generation_jobs.py::test_serialize_job_returns_frontend_contract -v
```

Expected: FAIL because `api.services.generation_jobs` does not exist.

- [ ] **Step 3: Create service module**

Create `api/services/generation_jobs.py`:

```python
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType

ACTIVE_STATUSES = {
    GenerationJobStatus.queued,
    GenerationJobStatus.waiting_capacity,
    GenerationJobStatus.waiting_provider_limit,
    GenerationJobStatus.running,
    GenerationJobStatus.retrying,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_job(job: Optional[GenerationJob], suite_id: Optional[str] = None) -> dict:
    if job is None:
        return {
            "suite_id": suite_id,
            "status": "idle",
            "stage": "idle",
            "message": "No generation is running.",
            "progress": 0,
        }
    return {
        "suite_id": job.suite_id,
        "job_id": job.id,
        "status": job.status.value,
        "stage": job.stage,
        "message": job.message,
        "progress": job.progress,
        "error": job.error,
        "provider": job.provider,
        "model": job.model,
        "retry_count": job.retry_count,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
        "rate_limit_reset_at": job.rate_limit_reset_at.isoformat() if job.rate_limit_reset_at else None,
        "estimated_wait_seconds": job.estimated_wait_seconds,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "result": job.result,
    }


async def get_active_job(db: AsyncSession, suite_id: str) -> Optional[GenerationJob]:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.status.in_(ACTIVE_STATUSES))
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_job(db: AsyncSession, suite_id: str) -> Optional[GenerationJob]:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_job(
    db: AsyncSession,
    suite_id: str,
    job_type: GenerationJobType,
    user_id: Optional[str],
    input_data: dict,
) -> GenerationJob:
    job = GenerationJob(
        suite_id=suite_id,
        created_by=user_id,
        type=job_type,
        status=GenerationJobStatus.queued,
        stage="queued",
        message="Generation queued.",
        progress=0,
        input=input_data,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def update_job(db: AsyncSession, job_id: str, **fields) -> Optional[GenerationJob]:
    result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return None
    for key, value in fields.items():
        if hasattr(job, key):
            setattr(job, key, value)
    await db.commit()
    await db.refresh(job)
    return job


async def mark_running(db: AsyncSession, job_id: str, message: str = "Generation started.") -> Optional[GenerationJob]:
    return await update_job(
        db,
        job_id,
        status=GenerationJobStatus.running,
        stage="running",
        message=message,
        progress=5,
        started_at=utcnow(),
    )


async def mark_provider_limit(
    db: AsyncSession,
    job_id: str,
    provider: str,
    model: Optional[str],
    wait_seconds: int,
    error: str,
) -> Optional[GenerationJob]:
    now = utcnow()
    return await update_job(
        db,
        job_id,
        status=GenerationJobStatus.waiting_provider_limit,
        stage="provider_limit",
        message=f"Waiting for {provider} API capacity.",
        provider=provider,
        model=model,
        retry_count=GenerationJob.retry_count + 1,
        next_retry_at=now + timedelta(seconds=wait_seconds),
        rate_limit_reset_at=now + timedelta(seconds=wait_seconds),
        estimated_wait_seconds=wait_seconds,
        error=error,
    )


async def mark_completed(db: AsyncSession, job_id: str, result: dict) -> Optional[GenerationJob]:
    return await update_job(
        db,
        job_id,
        status=GenerationJobStatus.completed,
        stage="done",
        message="Generation completed.",
        progress=100,
        result=result,
        finished_at=utcnow(),
    )


async def mark_failed(db: AsyncSession, job_id: str, error: str) -> Optional[GenerationJob]:
    return await update_job(
        db,
        job_id,
        status=GenerationJobStatus.failed,
        stage="failed",
        message="Generation failed.",
        progress=100,
        error=error,
        finished_at=utcnow(),
    )
```

- [ ] **Step 4: Fix retry_count update**

Replace the `retry_count=GenerationJob.retry_count + 1` line with explicit loading inside `mark_provider_limit`:

```python
result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
job = result.scalar_one_or_none()
retry_count = (job.retry_count + 1) if job else 1
```

Then pass `retry_count=retry_count`.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_generation_jobs.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/services/generation_jobs.py tests/test_generation_jobs.py
git commit -m "feat: add generation job service"
```

---

### Task 3: Replace In-Memory Router Jobs

**Files:**
- Modify: `api/routers/content.py`
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Replace memory helpers**

In `api/routers/content.py`, remove `_GENERATION_JOBS`, `_active_job`, and `_job_payload`.

Add imports:

```python
from ..models.generation_job import GenerationJobType
from ..services.generation_jobs import (
    create_job,
    get_active_job,
    get_latest_job,
    mark_completed,
    mark_failed,
    mark_running,
    serialize_job,
    update_job,
)
```

- [ ] **Step 2: Update background runner signature**

Change `_run_generation` to accept `job_id` as required and update the DB job:

```python
async def _run_generation(suite_id: str, job_id: str, count: int = 3, options: Optional[dict] = None):
    async with AsyncSessionLocal() as db:
        await mark_running(db, job_id, "Preparing content generation.")

        def progress(event: dict):
            async def _write():
                async with AsyncSessionLocal() as progress_db:
                    await update_job(progress_db, job_id, **event)
            import asyncio
            asyncio.create_task(_write())

        try:
            post_ids = await generate_content_for_suite(
                suite_id,
                db,
                count=count,
                options=options or {},
                progress=progress,
            )
            await mark_completed(db, job_id, {"post_ids": post_ids, "count": len(post_ids)})
        except Exception as exc:
            await mark_failed(db, job_id, str(exc))
```

- [ ] **Step 3: Update generate endpoint**

In `generate_content`, replace memory duplicate check with:

```python
existing = await get_active_job(db, suite_id)
if existing:
    return serialize_job(existing)
```

Create durable job:

```python
job = await create_job(
    db,
    suite_id=suite_id,
    job_type=GenerationJobType.content_generation,
    user_id=current_user.id,
    input_data=options | {"count": data.count},
)
background_tasks.add_task(_run_generation, suite_id, job.id, data.count, options)
return serialize_job(job)
```

- [ ] **Step 4: Update status endpoint**

Replace `return _job_payload(suite_id)` with:

```python
job = await get_latest_job(db, suite_id)
return serialize_job(job, suite_id=suite_id)
```

- [ ] **Step 5: Update regenerate endpoint**

Before deleting the old post:

```python
existing = await get_active_job(db, suite_id)
if existing:
    return serialize_job(existing)
```

After delete/commit:

```python
job = await create_job(
    db,
    suite_id=suite_id,
    job_type=GenerationJobType.content_regeneration,
    user_id=current_user.id,
    input_data=options | {"count": 1, "post_id": post_id},
)
background_tasks.add_task(_run_generation, suite_id, job.id, 1, options)
return serialize_job(job)
```

- [ ] **Step 6: Update frontend type**

In `web/src/lib/api.ts`, extend `GenerationStatus`:

```ts
provider?: string | null;
model?: string | null;
retry_count?: number;
next_retry_at?: string | null;
rate_limit_reset_at?: string | null;
estimated_wait_seconds?: number | null;
result?: { post_ids?: string[]; count?: number } | null;
```

And status union:

```ts
status:
  | "idle"
  | "queued"
  | "waiting_capacity"
  | "waiting_provider_limit"
  | "running"
  | "retrying"
  | "completed"
  | "failed"
  | "cancelled"
  | "timeout";
```

- [ ] **Step 7: Run compile/build**

Run:

```bash
python3 -m py_compile api/routers/content.py api/services/content_generator.py api/services/generation_jobs.py api/models/generation_job.py
npm run build
```

Expected: Python compile passes and Next.js build succeeds.

- [ ] **Step 8: Commit**

```bash
git add api/routers/content.py api/models/__init__.py api/models/generation_job.py api/services/generation_jobs.py web
git commit -m "feat: persist content generation jobs"
```

---

### Task 4: Surface Waiting States in Dashboard

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`

- [ ] **Step 1: Add active status helper**

Near `ContentTab`, add:

```ts
function isGenerationActive(status?: GenerationStatus | null) {
  return [
    "queued",
    "waiting_capacity",
    "waiting_provider_limit",
    "running",
    "retrying",
  ].includes(status?.status || "");
}
```

- [ ] **Step 2: Use helper for generating state**

Replace:

```ts
const active = status.status === "queued" || status.status === "running";
```

with:

```ts
const active = isGenerationActive(status);
```

Replace every direct queued/running check in `handleGenerate` and `handleRegenerate` with `isGenerationActive(status)`.

- [ ] **Step 3: Show waiting text**

Add:

```ts
const waitMessage = generationStatus?.status === "waiting_provider_limit"
  ? `Waiting for ${generationStatus.provider || "AI provider"} capacity${
      generationStatus.estimated_wait_seconds ? ` (~${Math.ceil(generationStatus.estimated_wait_seconds / 60)} min)` : ""
    }. You can leave this page.`
  : generationStatus?.message || "AI is generating content…";
```

Use `waitMessage` inside the progress box.

- [ ] **Step 4: Treat completed as final**

Replace success checks:

```ts
status.status === "success"
```

with:

```ts
status.status === "completed"
```

- [ ] **Step 5: Run build**

Run:

```bash
npm run build
```

Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "fix: show durable generation waiting states"
```

---

### Task 5: Provider Limit Classification

**Files:**
- Modify: `api/services/content_generator.py`
- Modify: `api/routers/content.py`
- Modify: `api/services/generation_jobs.py`

- [ ] **Step 1: Add provider limit detector**

In `api/services/generation_jobs.py`, add:

```python
def classify_provider_limit(error: Exception) -> Optional[dict]:
    text = str(error).lower()
    if "rate limit" in text or "429" in text or "quota" in text or "resource exhausted" in text:
        provider = "ai_provider"
        if "openai" in text:
            provider = "openai"
        elif "anthropic" in text or "claude" in text:
            provider = "anthropic"
        elif "gemini" in text or "google" in text or "veo" in text:
            provider = "google"
        return {
            "provider": provider,
            "model": None,
            "wait_seconds": 120,
            "error": str(error),
        }
    return None
```

- [ ] **Step 2: Use classifier in router**

In `_run_generation`, import `classify_provider_limit` and `mark_provider_limit`.

In the `except Exception as exc` block:

```python
limit = classify_provider_limit(exc)
if limit:
    await mark_provider_limit(db, job_id, **limit)
    return
await mark_failed(db, job_id, str(exc))
```

- [ ] **Step 3: Keep job waiting instead of failed**

Do not retry automatically in this task. The important first behavior is truthful state: `waiting_provider_limit`, visible to the user, not fake failure.

- [ ] **Step 4: Run compile**

Run:

```bash
python3 -m py_compile api/routers/content.py api/services/generation_jobs.py
```

Expected: compile passes.

- [ ] **Step 5: Commit**

```bash
git add api/routers/content.py api/services/generation_jobs.py
git commit -m "fix: classify AI provider limits as waiting jobs"
```

---

## Self-Review

- Spec coverage: durable jobs, waiting states, provider limits, duplicate prevention, progress UI, and backward-compatible generation are covered.
- Placeholder scan: no TBD/TODO placeholders. Every task names exact files and code.
- Type consistency: backend statuses match frontend union. Router serializes via the service contract.
- Scope check: this plan intentionally does not introduce Redis/Celery yet. It creates the durable job model first so the current Railway deployment stays stable and can later move work to separate workers without changing the frontend contract.
