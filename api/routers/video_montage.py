from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.generation_job import GenerationJob, GenerationJobType
from ..models.suite import Suite
from ..models.user import User
from ..services.generation_jobs import ACTIVE_STATUSES, create_job, serialize_job, update_job
from ..services.video_montage import job_dir, safe_filename

router = APIRouter(prefix="/suites/{suite_id}/video-montage", tags=["video-montage"])

MAX_UPLOAD_BYTES = 500 * 1024 * 1024


async def get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    result = await db.execute(select(Suite).where(Suite.id == suite_id, Suite.owner_id == user.id))
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


async def latest_video_montage_job(db: AsyncSession, suite_id: str) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.type == GenerationJobType.video_montage)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def active_video_montage_job(db: AsyncSession, suite_id: str) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.type == GenerationJobType.video_montage)
        .where(GenerationJob.status.in_(ACTIVE_STATUSES))
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def parse_options(options_json: str | None) -> list[str]:
    if not options_json:
        return []
    try:
        parsed = json.loads(options_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid options JSON.") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="Options must be a list.")
    return [str(item)[:80] for item in parsed[:20] if str(item).strip()]


def parse_text_overrides(overrides_json: str | None, *, max_items: int = 18) -> list[str]:
    if not overrides_json:
        return []
    try:
        parsed = json.loads(overrides_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid text overrides JSON.") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="Text overrides must be a list.")
    values: list[str] = []
    for item in parsed[:max_items]:
        text = str(item or "").strip()
        if text:
            values.append(text[:360])
        else:
            values.append("")
    return values


@router.get("/jobs/latest")
async def get_latest_video_montage_job(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    job = await latest_video_montage_job(db, suite_id)
    return serialize_job(job, suite_id=suite_id)


@router.get("/jobs/{job_id}")
async def get_video_montage_job(
    suite_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.id == job_id)
        .where(GenerationJob.type == GenerationJobType.video_montage)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video montage job not found")
    return serialize_job(job, suite_id=suite_id)


def parse_zoom(raw: str) -> float:
    """Clamp the requested subject zoom to 1.0-3.0 in 0.25 steps."""
    try:
        value = float(str(raw).strip() or "1")
    except ValueError:
        value = 1.0
    return max(1.0, min(3.0, round(value * 4) / 4))


@router.post("/jobs")
async def create_video_montage_job(
    suite_id: str,
    mode: str = Form("talking_head"),
    source_url: str = Form(""),
    options_json: str = Form("[]"),
    caption_overrides_json: str = Form("[]"),
    title_overrides_json: str = Form("[]"),
    notes: str = Form(""),
    zoom: str = Form("1"),
    source_file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    existing = await active_video_montage_job(db, suite_id)
    if existing:
        return serialize_job(existing, suite_id=suite_id)

    options = parse_options(options_json)
    caption_overrides = parse_text_overrides(caption_overrides_json)
    title_overrides = parse_text_overrides(title_overrides_json)
    input_data: dict[str, Any] = {
        "mode": mode[:80],
        "source_url": source_url.strip()[:1500],
        "options": options,
        "caption_overrides": caption_overrides,
        "title_overrides": title_overrides,
        "notes": notes.strip()[:3000],
        "zoom": parse_zoom(zoom),
    }
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.video_montage,
        user_id=current_user.id,
        input_data=input_data,
    )

    if source_file and source_file.filename:
        data = await source_file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Video file is too large. Maximum is 500 MB.")
        output_dir = job_dir(job.id)
        filename = safe_filename(source_file.filename, "source.mp4")
        source_path = output_dir / filename
        source_path.write_bytes(data)
        input_data["source_file_path"] = str(source_path)
        input_data["source_file_name"] = filename
        input_data["source_content_type"] = source_file.content_type
        job = await update_job(db, job.id, input=input_data) or job

    return serialize_job(job, suite_id=suite_id)
