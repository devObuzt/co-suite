import asyncio
import logging
from datetime import timedelta
from typing import Awaitable, Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.observability import log_event, notify_generation_job_alert
from ..core.config import settings
from ..core.database import AsyncSessionLocal
from ..models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
from .content_generator import generate_content_for_suite
from .generation_jobs import (
    STALE_UPDATE_SECONDS,
    classify_provider_limit,
    mark_completed,
    mark_failed,
    mark_progress,
    mark_provider_limit,
    mark_running,
    safe_generation_error,
    update_job,
    utcnow,
)
from .marketing_plan_generator import (
    build_marketing_plan_partial_result,
    generate_marketing_competitor_research,
    generate_marketing_demand_supply_research,
    generate_marketing_plan_execution_section,
    generate_marketing_plan_deck,
    marketing_plan_stage_snapshot,
    normalize_marketing_action_plan,
)
from .product_bulk_generator import (
    generate_all_products,
    generate_first_product_templates,
    regenerate_product_asset,
)
from .media_library import montage_media_asset
from .video_montage import generate_video_montage_for_suite
from ..models.suite import Suite

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
        safe_error = safe_generation_error(str(error)) or "unknown error"
        return {
            "status": GenerationJobStatus.failed,
            "stage": "failed",
            "message": f"Generation failed after retries: {safe_error}",
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


def _suite_strategy(suite: Suite) -> dict:
    return suite.strategy if isinstance(suite.strategy, dict) else {}


def _suite_marketing_plan_deck(suite: Suite) -> Optional[dict]:
    deck = _suite_strategy(suite).get("marketing_plan_deck")
    return deck if isinstance(deck, dict) else None


def _save_suite_marketing_plan_deck(suite: Suite, deck: dict) -> None:
    strategy = dict(_suite_strategy(suite))
    strategy["marketing_plan_deck"] = deck
    suite.strategy = strategy


def _save_suite_marketing_plan_partial(suite: Suite, partial_result: dict) -> None:
    strategy = dict(_suite_strategy(suite))
    intelligence = partial_result.get("intelligence")
    if isinstance(intelligence, dict):
        strategy["marketing_intelligence"] = intelligence
    suite.strategy = strategy


def _save_suite_marketing_plan_execution_section(suite: Suite, section: str, value: dict) -> dict:
    strategy = dict(_suite_strategy(suite))
    deck = dict(_suite_marketing_plan_deck(suite) or {})
    if section == "social":
        deck["monthly_work_plan"] = value
        partial = dict(deck.get("partial") or {})
        partial["social_plan_ready"] = True
        partial["action_plan_ready"] = bool(deck.get("paid_funnel"))
        deck["partial"] = partial
    elif section == "ads":
        deck["paid_funnel"] = value
        partial = dict(deck.get("partial") or {})
        partial["paid_funnel_ready"] = True
        partial["action_plan_ready"] = bool(deck.get("monthly_work_plan"))
        deck["partial"] = partial
    strategy["marketing_plan_deck"] = deck
    strategy["marketing_action_plan"] = normalize_marketing_action_plan(
        dict(strategy.get("marketing_action_plan") or {}),
        deck,
        str(deck.get("language") or ""),
    )
    suite.strategy = strategy
    return deck


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


async def recover_stale_running_jobs(db: AsyncSession) -> int:
    now = utcnow()
    stale_before = now - timedelta(seconds=STALE_UPDATE_SECONDS)
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.status == GenerationJobStatus.running)
        .where(GenerationJob.updated_at <= stale_before)
        .order_by(GenerationJob.updated_at.asc())
        .limit(10)
    )
    stale_jobs = result.scalars().all()
    recovered = 0
    for job in stale_jobs:
        next_retry_count = int(job.retry_count or 0) + 1
        if next_retry_count > int(job.max_retries or 0):
            await update_job(
                db,
                job.id,
                status=GenerationJobStatus.failed,
                stage="failed",
                message="Generation failed after the worker stopped updating this job.",
                progress=100,
                error="Generation worker stopped updating this job before it completed.",
                finished_at=now,
            )
            await notify_generation_job_alert(job, "failed_job")
        else:
            await update_job(
                db,
                job.id,
                status=GenerationJobStatus.retrying,
                stage="retrying",
                message=f"Recovered stale running job. Retrying attempt {next_retry_count} of {job.max_retries}.",
                progress=0,
                retry_count=next_retry_count,
                next_retry_at=now,
                error="Generation worker stopped updating this job before it completed.",
            )
        recovered += 1

    if recovered:
        log_event(
            log,
            logging.WARNING,
            "Recovered stale running generation jobs.",
            event="generation_jobs_recovered",
            recovered=recovered,
        )
    return recovered


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

            if job.type == GenerationJobType.marketing_plan:
                result = await db.execute(select(Suite).where(Suite.id == job.suite_id))
                suite = result.scalar_one_or_none()
                if not suite:
                    return await mark_failed(db, job.id, "Suite not found")

                section = str(input_data.get("section") or "strategy")
                planning_inputs = {
                    "near_term_focus": input_data.get("near_term_focus"),
                    "upcoming_campaigns": input_data.get("upcoming_campaigns") or [],
                    "planning_notes": input_data.get("planning_notes"),
                }
                if section in {"competitors", "demand_supply"}:
                    stage = "competitor_research" if section == "competitors" else "demand_supply"
                    message = (
                        "Scratching competitors and source leads."
                        if section == "competitors"
                        else "Building demand and supply signals from competitors."
                    )
                    await mark_progress(
                        db,
                        job.id,
                        {
                            "stage": stage,
                            "message": message,
                            "progress": 20 if section == "competitors" else 45,
                            "result": {
                                "partial": {
                                    "competitors_ready": False,
                                    "demand_supply_ready": False,
                                    "deck_ready": bool(_suite_marketing_plan_deck(suite)),
                                }
                            },
                        },
                    )
                    intelligence = (
                        await generate_marketing_competitor_research(
                            suite,
                            input_data.get("language"),
                            planning_inputs=planning_inputs,
                        )
                        if section == "competitors"
                        else await generate_marketing_demand_supply_research(
                            suite,
                            input_data.get("language"),
                            planning_inputs=planning_inputs,
                        )
                    )
                    _save_suite_marketing_plan_partial(suite, {"intelligence": intelligence})
                    await db.commit()
                    return await mark_completed(
                        db,
                        job.id,
                        {
                            "section": section,
                            "partial": {
                                "competitors_ready": bool(intelligence.get("competitors")),
                                "demand_supply_ready": section == "demand_supply",
                                "deck_ready": bool(_suite_marketing_plan_deck(suite)),
                            },
                            "intelligence": intelligence,
                        },
                    )
                if section in {"social", "ads"}:
                    existing = _suite_marketing_plan_deck(suite)
                    if not existing:
                        return await mark_failed(db, job.id, "Generate the core marketing plan before this section.")
                    stage = "social_plan" if section == "social" else "ads_funnel"
                    message = (
                        "Building the monthly social work plan."
                        if section == "social"
                        else "Building the paid marketing funnel."
                    )
                    await mark_progress(
                        db,
                        job.id,
                        {
                            "stage": stage,
                            "message": message,
                            "progress": 30,
                            "result": {
                                "partial": existing.get("partial") or {},
                                "deck_ready": True,
                            },
                        },
                    )
                    generated_section = await generate_marketing_plan_execution_section(
                        suite,
                        input_data.get("language"),
                        section,
                        planning_inputs=planning_inputs,
                    )
                    deck = _save_suite_marketing_plan_execution_section(suite, section, generated_section)
                    await db.commit()
                    completed_result = {
                        "section": section,
                        "partial": deck.get("partial") or {},
                        "deck_ready": True,
                        "social_plan_ready": bool(deck.get("monthly_work_plan")),
                        "paid_funnel_ready": bool(deck.get("paid_funnel")),
                    }
                    return await mark_completed(db, job.id, completed_result)

                partial_result = build_marketing_plan_partial_result(
                    suite,
                    input_data.get("language"),
                    planning_inputs=planning_inputs,
                )
                _save_suite_marketing_plan_partial(suite, partial_result)
                await db.commit()
                await mark_progress(
                    db,
                    job.id,
                    {
                        "stage": "ai_strategy",
                        "message": "Market intelligence is ready. Building the full marketing plan with AI.",
                        "progress": 35,
                        "result": partial_result,
                    },
                )
                deck = await generate_marketing_plan_deck(
                    suite,
                    input_data.get("language"),
                    planning_inputs=planning_inputs,
                    include_execution_sections=False,
                )
                existing = _suite_marketing_plan_deck(suite)
                if existing and isinstance(existing.get("share"), dict):
                    deck["share"] = existing["share"]
                _save_suite_marketing_plan_deck(suite, deck)
                await db.commit()
                saving_result = {
                    **partial_result,
                    "stages": marketing_plan_stage_snapshot("saving", {"research", "market", "deck"}),
                    "partial": {
                        "intelligence_ready": True,
                        "deck_ready": True,
                        "action_plan_ready": False,
                        "social_plan_ready": False,
                        "paid_funnel_ready": False,
                    },
                    "deck_ready": True,
                    "generated_at": deck.get("generated_at"),
                }
                await mark_progress(
                    db,
                    job.id,
                    {"stage": "saving", "message": "Marketing plan saved.", "progress": 95, "result": saving_result},
                )
                return await mark_completed(
                    db,
                    job.id,
                    {
                        **saving_result,
                        "stages": marketing_plan_stage_snapshot("", {"research", "market", "deck", "saving"}),
                    },
                )

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

            if job.type == GenerationJobType.video_montage:
                result = await db.execute(select(Suite).where(Suite.id == job.suite_id))
                suite = result.scalar_one_or_none()
                if not suite:
                    return await mark_failed(db, job.id, "Suite not found")
                montage_result = await generate_video_montage_for_suite(
                    db=db,
                    suite=suite,
                    job_id=job.id,
                    input_data=input_data,
                    progress=progress,
                )
                # Auto-file the finished render into the suite's media library.
                # A filing failure must never fail the montage job itself.
                try:
                    media_asset = montage_media_asset(suite, job.id, montage_result)
                    if media_asset:
                        db.add(media_asset)
                        await db.flush()
                except Exception:
                    log.exception("Could not file montage output for job %s into the media library", job.id)
                    await db.rollback()
                return await mark_completed(db, job.id, montage_result)

            return await mark_failed(db, job.id, f"Unsupported generation job type: {job.type}")
        except Exception as exc:
            log.exception("Generation worker failed job %s", job.id)
            await _mark_retry_or_failed(db, job, exc)
            return None


async def run_once(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    recover: bool = True,
) -> Optional[str]:
    async with session_factory() as db:
        if recover:
            await recover_stale_running_jobs(db)
        job = await claim_next_job(db)
        if not job:
            return None
        job_id = job.id

    await execute_claimed_job(job_id, session_factory)
    return job_id


async def _worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    poll_interval_seconds: int,
    recover: bool,
) -> None:
    while True:
        try:
            claimed = await run_once(session_factory, recover=recover)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Generation queue worker loop crashed; continuing after backoff.")
            await asyncio.sleep(min(30, max(1, poll_interval_seconds * 5)))
            continue
        if not claimed:
            await asyncio.sleep(poll_interval_seconds)


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
    concurrency: Optional[int] = None,
) -> None:
    if concurrency is None:
        concurrency = settings.generation_worker_concurrency
    concurrency = max(1, int(concurrency))
    if concurrency == 1:
        await _worker_loop(session_factory, poll_interval_seconds, recover=True)
        return

    log_event(
        log,
        logging.INFO,
        "Starting generation queue worker loops.",
        event="generation_worker_started",
        concurrency=concurrency,
    )
    # Stale-job recovery mutates without row locks, so only loop 0 runs it.
    await asyncio.gather(
        *(
            _worker_loop(session_factory, poll_interval_seconds, recover=(index == 0))
            for index in range(concurrency)
        )
    )
