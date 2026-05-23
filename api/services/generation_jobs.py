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
    job = result.scalar_one_or_none()
    retry_at = job.next_retry_at if job else None
    if retry_at and retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    if job and job.status == GenerationJobStatus.waiting_provider_limit and retry_at and retry_at <= utcnow():
        job.status = GenerationJobStatus.failed
        job.stage = "failed"
        job.message = "AI provider limit wait expired. Please retry."
        job.progress = 100
        job.finished_at = utcnow()
        await db.commit()
        return None
    return job


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
    for key, value in fields.items():
        if hasattr(job, key):
            setattr(job, key, value)
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
    return await update_job(
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
