import asyncio
import logging
from datetime import timedelta
from typing import Awaitable, Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.observability import log_event, notify_generation_job_alert
from ..core.database import AsyncSessionLocal
from ..models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
from .content_generator import generate_content_for_suite
from .generation_jobs import (
    classify_provider_limit,
    mark_completed,
    mark_failed,
    mark_progress,
    mark_provider_limit,
    mark_running,
    update_job,
    utcnow,
)
from .product_bulk_generator import (
    generate_all_products,
    generate_first_product_templates,
    regenerate_product_asset,
)

log = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 300
POLL_INTERVAL_SECONDS = 2


def retry_delay_seconds(job: GenerationJob) -> int:
    retry_count = max(0, int(job.retry_count or 0))
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** retry_count))


def retry_fields_for_error(job: GenerationJob, error: Exception) -> dict:
    next_retry_count = int(job.retry_count or 0) + 1
    if next_retry_count > int(job.max_retries or 0):
        return {
            "status": GenerationJobStatus.failed,
            "stage": "failed",
            "message": "Generation failed after retries.",
            "progress": 100,
            "error": str(error),
            "finished_at": utcnow(),
        }

    return {
        "status": GenerationJobStatus.retrying,
        "stage": "retrying",
        "message": f"Generation failed. Retrying attempt {next_retry_count} of {job.max_retries}.",
        "progress": 0,
        "error": str(error),
        "retry_count": next_retry_count,
        "next_retry_at": utcnow() + timedelta(seconds=retry_delay_seconds(job)),
    }


def progress_writer(job_id: str) -> Callable[[dict], None]:
    def progress(event: dict) -> None:
        async def _write() -> None:
            async with AsyncSessionLocal() as progress_db:
                await mark_progress(progress_db, job_id, event)

        try:
            asyncio.create_task(_write())
        except RuntimeError:
            pass

    return progress


async def claim_next_job(db: AsyncSession) -> Optional[GenerationJob]:
    now = utcnow()
    runnable_status = or_(
        GenerationJob.status == GenerationJobStatus.queued,
        (
            GenerationJob.status.in_(
                {
                    GenerationJobStatus.retrying,
                    GenerationJobStatus.waiting_provider_limit,
                    GenerationJobStatus.waiting_capacity,
                }
            )
            & ((GenerationJob.next_retry_at.is_(None)) | (GenerationJob.next_retry_at <= now))
        ),
    )
    result = await db.execute(
        select(GenerationJob)
        .where(runnable_status)
        .order_by(GenerationJob.priority.desc(), GenerationJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return None

    await mark_running(db, job.id, "Worker claimed generation job.")
    return job


async def _mark_retry_or_failed(db: AsyncSession, job: GenerationJob, error: Exception) -> None:
    limit = classify_provider_limit(error)
    if limit:
        await mark_provider_limit(db, job.id, **limit)
        return
    fields = retry_fields_for_error(job, error)
    updated = await update_job(db, job.id, **fields)
    if fields.get("status") == GenerationJobStatus.failed:
        log_event(
            log,
            logging.ERROR,
            "Generation worker exhausted job retries.",
            event="generation_job_failed",
            job_id=job.id,
            suite_id=job.suite_id,
            provider=updated.provider if updated else job.provider,
            model=updated.model if updated else job.model,
            attempt=updated.retry_count if updated else job.retry_count,
            status=GenerationJobStatus.failed.value,
            safe_error_class="generation_failure",
        )
        await notify_generation_job_alert(updated, "failed_job")


async def execute_claimed_job(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> Optional[GenerationJob]:
    async with session_factory() as db:
        result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            log.warning("Generation worker could not find job %s", job_id)
            return None

        try:
            input_data = dict(job.input or {})
            progress = progress_writer(job.id)

            if job.type in {GenerationJobType.content_generation, GenerationJobType.content_regeneration}:
                count = max(1, min(int(input_data.get("count") or 1), 12))
                options = {key: value for key, value in input_data.items() if key != "count"}
                post_ids = await generate_content_for_suite(
                    job.suite_id,
                    db,
                    count=count,
                    options=options,
                    progress=progress,
                )
                return await mark_completed(db, job.id, {"post_ids": post_ids, "count": len(post_ids)})

            if job.type == GenerationJobType.product_bulk_generate_first:
                batch_id = str(input_data.get("batch_id") or "")
                asset_ids = await generate_first_product_templates(db, job.suite_id, batch_id, progress)
                return await mark_completed(db, job.id, {"batch_id": batch_id, "asset_ids": asset_ids})

            if job.type == GenerationJobType.product_bulk_generate_all:
                batch_id = str(input_data.get("batch_id") or "")
                asset_ids = await generate_all_products(db, job.suite_id, batch_id, progress)
                return await mark_completed(db, job.id, {"batch_id": batch_id, "asset_ids": asset_ids})

            if job.type == GenerationJobType.product_bulk_regenerate_asset:
                batch_id = str(input_data.get("batch_id") or "")
                asset_id = str(input_data.get("asset_id") or "")
                feedback = input_data.get("feedback")
                new_asset_id = await regenerate_product_asset(
                    db,
                    job.suite_id,
                    batch_id,
                    asset_id,
                    feedback=str(feedback or ""),
                    progress=progress,
                )
                return await mark_completed(
                    db,
                    job.id,
                    {"batch_id": batch_id, "asset_id": new_asset_id, "regenerated_from_asset_id": asset_id},
                )

            return await mark_failed(db, job.id, f"Unsupported generation job type: {job.type}")
        except Exception as exc:
            log.exception("Generation worker failed job %s", job.id)
            await _mark_retry_or_failed(db, job, exc)
            return None


async def run_once(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> Optional[str]:
    async with session_factory() as db:
        job = await claim_next_job(db)
        if not job:
            return None
        job_id = job.id

    await execute_claimed_job(job_id, session_factory)
    return job_id


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> None:
    while True:
        claimed = await run_once(session_factory)
        if not claimed:
            await asyncio.sleep(poll_interval_seconds)
