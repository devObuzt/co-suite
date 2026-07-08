"""Backfill media_assets from completed video_montage generation jobs.

Idempotent: jobs whose id already appears in media_assets.source_job_id are
skipped, so the script can be re-run safely. Assets are filed under the month
the montage actually finished (finished_at, falling back to created_at).

Run manually against the target database:

    python -m api.scripts.backfill_media_assets
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..core.database import AsyncSessionLocal
from ..models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
from ..models.media_asset import MediaAsset
from ..models.suite import Suite
from ..services.media_library import montage_media_asset


async def backfill() -> int:
    inserted = 0
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(MediaAsset.source_job_id).where(MediaAsset.source_job_id.is_not(None))
        )
        seen_job_ids = {row[0] for row in existing}

        result = await db.execute(
            select(GenerationJob, Suite)
            .join(Suite, Suite.id == GenerationJob.suite_id)
            .where(GenerationJob.type == GenerationJobType.video_montage)
            .where(GenerationJob.status == GenerationJobStatus.completed)
            .order_by(GenerationJob.created_at.asc())
        )
        for job, suite in result.all():
            if job.id in seen_job_ids:
                continue
            montage_result = job.result if isinstance(job.result, dict) else {}
            asset = montage_media_asset(suite, job.id, montage_result)
            if not asset:
                continue
            finished = job.finished_at or job.created_at
            if finished:
                # File under the month the montage was actually rendered.
                asset.created_at = finished
                asset.title = f"مونتاج {suite.name} — {finished:%Y-%m-%d}"
            db.add(asset)
            seen_job_ids.add(job.id)
            inserted += 1

        await db.commit()
    return inserted


def main() -> None:
    inserted = asyncio.run(backfill())
    print(f"Inserted {inserted} media asset(s).")


if __name__ == "__main__":
    main()
