"""One durable job that builds the whole marketing plan, stage by stage.

The plan page used to chain the per-stage endpoints from the browser:
keywords, then competitors, then demand & supply, then personas, then the
marketing message. A refresh, a locked phone or a closed tab killed that chain
mid-way and left a half-built plan that nothing ever resumed — the page saw
"some data exists" and never picked the work back up.

The chain now runs here, inside the generation-queue worker. The job row is the
single source of truth for "which stage are we on": the page polls it and shows
the live stage, and a refresh changes nothing because the work never lived in
the browser. The run is also resumable — a stage that already has data is
skipped, so a retry after a crash finishes the plan instead of rebuilding it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.generation_job import GenerationJob
from ..models.suite import Suite
from .generation_jobs import mark_completed, mark_failed, mark_progress

log = logging.getLogger(__name__)

# Personas stream in small batches so the first ones land quickly; the page
# keeps a "still generating" marker until the target is reached.
PERSONA_TARGET = 10
PERSONA_BATCH = 2

# Stage order is the plan's reading order — each stage feeds the next.
STAGE_ORDER = ["keywords", "competitors", "demand_supply", "personas", "message"]

# (stage, progress when it starts, progress when it ends)
_STAGE_PROGRESS: dict[str, tuple[int, int]] = {
    "keywords": (10, 25),
    "competitors": (25, 45),
    "demand_supply": (45, 65),
    "personas": (65, 90),
    "message": (90, 98),
}

_STAGE_MESSAGE = {
    "keywords": "Building the keyword list.",
    "competitors": "Researching competitors.",
    "demand_supply": "Measuring demand and supply.",
    "personas": "Building customer personas.",
    "message": "Writing the marketing message.",
}


def _strategy(suite: Suite) -> dict[str, Any]:
    return dict(suite.strategy or {})


def _stored_intelligence(suite: Suite) -> dict[str, Any]:
    value = _strategy(suite).get("marketing_intelligence")
    return value if isinstance(value, dict) else {}


def plan_stage_status(suite: Suite) -> dict[str, bool]:
    """Which plan stages already hold data — the resume map.

    Kept in step with the plan page's own readiness test so the server and the
    browser never disagree about what is still missing.
    """
    strategy = _strategy(suite)
    intel = _stored_intelligence(suite)
    return {
        "keywords": len(intel.get("keywords") or []) > 0,
        "competitors": len(intel.get("competitors") or []) > 0,
        "demand_supply": bool(intel.get("demand_supply"))
        or len(intel.get("demand_signals") or []) > 0
        or len(intel.get("supply_signals") or []) > 0,
        "personas": len(intel.get("personas") or []) > 0,
        "message": bool(str(strategy.get("marketing_message") or "").strip()),
    }


def pending_plan_stages(suite: Suite) -> list[str]:
    done = plan_stage_status(suite)
    return [stage for stage in STAGE_ORDER if not done.get(stage)]


async def _run_keywords(suite: Suite, language: str | None) -> None:
    # The stage generators live in the marketing-plan router next to ~1,600
    # lines of scraping and keyword-planner helpers they depend on. Importing
    # them here (lazily, so no import cycle can form) keeps the worker and the
    # per-stage endpoints running the exact same code.
    from ..routers import marketing_plans as mp
    from .marketing_plan_generator import (
        infer_plan_language,
        normalize_marketing_intelligence,
        suite_research_payload,
    )

    output_language = infer_plan_language(suite, language)
    intelligence = normalize_marketing_intelligence(
        {**_stored_intelligence(suite), "phase": "keywords"},
        suite_research_payload(suite),
        output_language,
    )
    intelligence["keywords"] = await mp._generate_keywords(suite, output_language, [], more=False)
    intelligence["status"] = "keywords_ready"
    intelligence["generated_at"] = datetime.now(timezone.utc).isoformat()
    mp._save_marketing_intelligence(suite, intelligence)


async def _run_competitors(suite: Suite, language: str | None) -> None:
    from ..routers import marketing_plans as mp

    await mp._save_competitor_scratch_from_search(suite, language)


async def _run_demand_supply(suite: Suite, language: str | None) -> None:
    from ..routers import marketing_plans as mp

    await mp._save_demand_supply_from_google_ads(suite, language, more=False)


async def _run_personas(db: AsyncSession, suite: Suite, language: str | None) -> None:
    from ..routers import marketing_plans as mp
    from .marketing_plan_generator import (
        generate_marketing_customer_personas_research,
        infer_plan_language,
    )

    output_language = infer_plan_language(suite, language)
    existing = [
        str(persona.get("name") or persona.get("id") or "").strip()
        for persona in (_stored_intelligence(suite).get("personas") or [])
        if isinstance(persona, dict)
    ]
    existing = [value for value in existing if value]

    # Batch-by-batch, committing as we go: a worker restart resumes from the
    # personas already on disk instead of starting the list over.
    while len(existing) < PERSONA_TARGET:
        intelligence = await generate_marketing_customer_personas_research(
            suite,
            output_language,
            count=PERSONA_BATCH,
            existing_persona_values=existing,
            append=bool(existing),
        )
        mp._save_marketing_intelligence(suite, intelligence)
        await db.commit()
        personas = intelligence.get("personas") if isinstance(intelligence.get("personas"), list) else []
        next_existing = [
            str(persona.get("name") or persona.get("id") or "").strip()
            for persona in personas
            if isinstance(persona, dict)
        ]
        next_existing = [value for value in next_existing if value]
        # No forward progress (the model returned nothing new) — stop rather
        # than spin for the rest of the batch budget.
        if len(next_existing) <= len(existing):
            return
        existing = next_existing


async def _run_message(suite: Suite, language: str | None) -> None:
    from .marketing_plan_generator import infer_plan_language
    from .strategy_generator import derive_brand_defaults, generate_strategy

    output_language = infer_plan_language(suite, language)
    strategy = await generate_strategy(
        derive_brand_defaults(dict(suite.brand or {})),
        user_language=output_language,
    )
    # MERGE — the strategy column also holds the plan deck and the
    # intelligence; replacing it would wipe the plan we just built.
    suite.strategy = {**_strategy(suite), **strategy}


_STAGE_RUNNERS: dict[str, Callable] = {
    "keywords": lambda db, suite, lang: _run_keywords(suite, lang),
    "competitors": lambda db, suite, lang: _run_competitors(suite, lang),
    "demand_supply": lambda db, suite, lang: _run_demand_supply(suite, lang),
    "personas": _run_personas,
    "message": lambda db, suite, lang: _run_message(suite, lang),
}


async def run_full_marketing_plan(
    db: AsyncSession,
    job: GenerationJob,
    suite: Suite,
    language: str | None,
) -> GenerationJob | None:
    """Build every missing plan stage, reporting the live stage on the job."""
    done = plan_stage_status(suite)
    failed: list[str] = []
    ran: list[str] = []

    for stage in STAGE_ORDER:
        if done.get(stage):
            continue
        start, end = _STAGE_PROGRESS[stage]
        await mark_progress(
            db,
            job.id,
            {
                "stage": stage,
                "message": _STAGE_MESSAGE[stage],
                "progress": start,
                "result": {"stages": {**done, stage: False}, "running_stage": stage},
            },
        )
        try:
            await _STAGE_RUNNERS[stage](db, suite, language)
            await db.commit()
            done = plan_stage_status(suite)
            ran.append(stage)
        except Exception as exc:  # one dead stage must not block the rest
            await db.rollback()
            log.exception("Marketing plan stage %s failed for suite %s", stage, suite.id)
            failed.append(stage)
            done = plan_stage_status(suite)
            await mark_progress(
                db,
                job.id,
                {
                    "stage": stage,
                    "message": f"{_STAGE_MESSAGE[stage]} failed: {str(exc)[:160]}",
                    "progress": end,
                    "result": {"stages": done, "failed": failed},
                },
            )
            continue
        await mark_progress(
            db,
            job.id,
            {
                "stage": stage,
                "message": _STAGE_MESSAGE[stage],
                "progress": end,
                "result": {"stages": done, "failed": failed},
            },
        )

    result = {"stages": done, "failed": failed, "generated": ran}
    # Everything we attempted blew up — that is a failed job, not a quiet
    # "completed" with an empty plan behind it.
    if failed and not ran:
        return await mark_failed(db, job.id, f"Marketing plan stages failed: {', '.join(failed)}", result=result)
    return await mark_completed(db, job.id, result)
