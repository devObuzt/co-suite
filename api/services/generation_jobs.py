from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.observability import log_event, notify_generation_job_alert
from ..models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType

import logging

log = logging.getLogger(__name__)

ACTIVE_STATUSES = {
    GenerationJobStatus.queued,
    GenerationJobStatus.waiting_capacity,
    GenerationJobStatus.waiting_provider_limit,
    GenerationJobStatus.running,
    GenerationJobStatus.retrying,
}
TERMINAL_STATUSES = {
    GenerationJobStatus.completed,
    GenerationJobStatus.failed,
    GenerationJobStatus.cancelled,
    GenerationJobStatus.timeout,
}
STALE_UPDATE_SECONDS = 30 * 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _age_seconds(value: Optional[datetime], now: datetime) -> Optional[int]:
    value = _as_aware(value)
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def safe_generation_error(error: Optional[str]) -> Optional[str]:
    if not error:
        return None
    text = str(error).lower()
    if "rate limit" in text or "429" in text or "quota" in text or "resource exhausted" in text:
        return "The AI provider is currently rate limited. Please wait and retry."
    if "api key" in text or "token" in text or "secret" in text or "credential" in text:
        return "The AI provider could not complete this request. Please retry."
    if "timeout" in text or "timed out" in text:
        return "Generation timed out. Please retry."
    return str(error)[:240]


def serialize_job(job: Optional[GenerationJob], suite_id: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    if job is None:
        return {
            "suite_id": suite_id,
            "status": "idle",
            "stage": "idle",
            "message": "No generation is running.",
            "progress": 0,
            "is_active": False,
            "is_terminal": False,
            "is_stale": False,
        }
    created_age = _age_seconds(job.created_at, now)
    updated_age = _age_seconds(job.updated_at or job.started_at or job.created_at, now)
    is_active = job.status in ACTIVE_STATUSES
    is_terminal = job.status in TERMINAL_STATUSES
    is_stale = bool(is_active and updated_age is not None and updated_age > STALE_UPDATE_SECONDS)
    wait_state = {
        "state": job.status.value if job.status in ACTIVE_STATUSES else None,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
        "rate_limit_reset_at": job.rate_limit_reset_at.isoformat() if job.rate_limit_reset_at else None,
        "estimated_wait_seconds": job.estimated_wait_seconds,
    }
    safe_error = safe_generation_error(job.error)
    return {
        "suite_id": job.suite_id,
        "job_id": job.id,
        "type": job.type.value if job.type else None,
        "status": job.status.value,
        "stage": job.stage,
        "message": job.message,
        "progress": job.progress,
        "error": safe_error,
        "safe_error": safe_error,
        "provider": job.provider,
        "model": job.model,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
        "rate_limit_reset_at": job.rate_limit_reset_at.isoformat() if job.rate_limit_reset_at else None,
        "estimated_wait_seconds": job.estimated_wait_seconds,
        "wait_state": wait_state,
        "is_active": is_active,
        "is_terminal": is_terminal,
        "is_stale": is_stale,
        "stale_reason": (
            "No job update has been recorded recently. Background task execution may have stopped."
            if is_stale
            else None
        ),
        "age_seconds": created_age,
        "last_update_age_seconds": updated_age,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "result": job.result,
        "stages": (job.result or {}).get("stages") if isinstance(job.result, dict) else None,
        "partial": (job.result or {}).get("partial") if isinstance(job.result, dict) else None,
        "execution": {
            "mode": "durable_worker",
            "durable_queue": True,
            "warning": None,
        },
    }


async def get_active_job(
    db: AsyncSession,
    suite_id: str,
    job_types: Optional[set[GenerationJobType]] = None,
) -> Optional[GenerationJob]:
    query = (
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.status.in_(ACTIVE_STATUSES))
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    if job_types:
        query = query.where(GenerationJob.type.in_(job_types))
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    return job


async def get_latest_job(db: AsyncSession, suite_id: str) -> Optional[GenerationJob]:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_job_for_input(
    db: AsyncSession,
    suite_id: str,
    input_key: str,
    input_value: str,
    job_types: Optional[set[GenerationJobType]] = None,
) -> Optional[GenerationJob]:
    query = (
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(50)
    )
    if job_types:
        query = query.where(GenerationJob.type.in_(job_types))

    result = await db.execute(query)
    for job in result.scalars().all():
        if str((job.input or {}).get(input_key) or "") == str(input_value):
            return job
    return None


async def create_job(
    db: AsyncSession,
    suite_id: str,
    job_type: GenerationJobType,
    user_id: Optional[str],
    input_data: dict,
    job_id: Optional[str] = None,
) -> GenerationJob:
    # Callers that must stage files under the job id (e.g. montage uploads to
    # R2) pass a pre-generated id so the job only becomes claimable once its
    # input is complete — the worker polls every couple of seconds.
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
    if job_id:
        job.id = job_id
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


async def mark_progress(db: AsyncSession, job_id: str, event: dict) -> Optional[GenerationJob]:
    result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return None
    if job.status in {
        GenerationJobStatus.completed,
        GenerationJobStatus.failed,
        GenerationJobStatus.cancelled,
        GenerationJobStatus.timeout,
    }:
        return job

    allowed = {
        "status",
        "stage",
        "message",
        "progress",
        "error",
        "provider",
        "model",
        "estimated_wait_seconds",
        "next_retry_at",
        "rate_limit_reset_at",
        "result",
    }
    fields = {key: value for key, value in event.items() if key in allowed}
    if isinstance(fields.get("status"), str):
        try:
            fields["status"] = GenerationJobStatus(fields["status"])
        except ValueError:
            fields.pop("status", None)
    # Progress writes are fire-and-forget tasks: an empty partial result must
    # never clobber a final result payload.
    if not fields.get("result"):
        fields.pop("result", None)
    fields = {key: value for key, value in fields.items() if hasattr(GenerationJob, key)}
    if not fields:
        return job
    # Guard again at write time: the job may have been finalized between our
    # read above and this update, and a late progress write must lose.
    await db.execute(
        sa_update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status.not_in(
                [
                    GenerationJobStatus.completed,
                    GenerationJobStatus.failed,
                    GenerationJobStatus.cancelled,
                    GenerationJobStatus.timeout,
                ]
            ),
        )
        .values(**fields)
    )
    await db.commit()
    await db.refresh(job)
    return job


async def mark_provider_limit(
    db: AsyncSession,
    job_id: str,
    provider: str,
    model: Optional[str],
    wait_seconds: int,
    error: str,
) -> Optional[GenerationJob]:
    result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    job = result.scalar_one_or_none()
    retry_count = (job.retry_count + 1) if job else 1
    now = utcnow()
    updated = await update_job(
        db,
        job_id,
        status=GenerationJobStatus.waiting_provider_limit,
        stage="provider_limit",
        message=f"Waiting for {provider} API capacity.",
        provider=provider,
        model=model,
        retry_count=retry_count,
        next_retry_at=now + timedelta(seconds=wait_seconds),
        rate_limit_reset_at=now + timedelta(seconds=wait_seconds),
        estimated_wait_seconds=wait_seconds,
        error=error,
    )
    log_event(
        log,
        logging.WARNING,
        "Generation job waiting on provider limit.",
        event="generation_job_provider_limit",
        job_id=job_id,
        suite_id=updated.suite_id if updated else None,
        provider=provider,
        model=model,
        attempt=updated.retry_count if updated else retry_count,
        status=GenerationJobStatus.waiting_provider_limit.value,
        safe_error_class="provider_limit",
    )
    await notify_generation_job_alert(updated, "provider_limit")
    return updated


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


async def mark_failed(
    db: AsyncSession,
    job_id: str,
    error: str,
    result: Optional[dict] = None,
) -> Optional[GenerationJob]:
    fields = dict(
        status=GenerationJobStatus.failed,
        stage="failed",
        message="Generation failed.",
        progress=100,
        error=error,
        finished_at=utcnow(),
    )
    if result is not None:
        # Keep the diagnostic payload (warnings, fallback reasons) with the
        # failed job instead of throwing it away.
        fields["result"] = result
    updated = await update_job(db, job_id, **fields)
    log_event(
        log,
        logging.ERROR,
        "Generation job failed.",
        event="generation_job_failed",
        job_id=job_id,
        suite_id=updated.suite_id if updated else None,
        provider=updated.provider if updated else None,
        model=updated.model if updated else None,
        attempt=updated.retry_count if updated else None,
        status=GenerationJobStatus.failed.value,
        safe_error_class="generation_failure",
    )
    await notify_generation_job_alert(updated, "failed_job")
    return updated


def classify_provider_limit(error: Exception) -> Optional[dict]:
    text = str(error).lower()
    if "rate limit" not in text and "429" not in text and "quota" not in text and "resource exhausted" not in text:
        return None

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
