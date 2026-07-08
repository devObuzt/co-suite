from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.generation_job import GenerationJob, GenerationJobType
from ..models.suite import Suite
from ..models.user import User
from ..services.generation_jobs import create_job, serialize_job
from ..services.media_storage import r2_configured, upload_bytes
from ..services.video_montage import (
    download_source,
    job_dir,
    normalize_montage_source,
    publish_veed_source,
    safe_filename,
)

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


def job_input_summary(job: GenerationJob) -> dict[str, Any]:
    """Trimmed job input for the jobs list (source label, notes, options)."""
    input_data = job.input if isinstance(job.input, dict) else {}
    return {
        "source_url": str(input_data.get("source_url") or "") or None,
        "source_file_name": str(input_data.get("source_file_name") or "") or None,
        "notes": str(input_data.get("notes") or "") or None,
        "options": input_data.get("options") if isinstance(input_data.get("options"), list) else [],
    }


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


@router.get("/jobs")
async def list_video_montage_jobs(
    suite_id: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent montage jobs for the suite, newest first (multi-job queue UI)."""
    await get_owned_suite(db, suite_id, current_user)
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.suite_id == suite_id)
        .where(GenerationJob.type == GenerationJobType.video_montage)
        .order_by(GenerationJob.created_at.desc())
        .limit(max(1, min(50, limit)))
    )
    jobs = result.scalars().all()
    payload = []
    for job in jobs:
        serialized = serialize_job(job, suite_id=suite_id)
        serialized["input"] = job_input_summary(job)
        payload.append(serialized)
    return {"jobs": payload}


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


class StageSourceRequest(BaseModel):
    source_url: str


@router.post("/stage-source")
async def stage_video_montage_source(
    suite_id: str,
    payload: StageSourceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download + normalize a remote source and publish it to R2.

    Gives the UI a directly playable preview URL (Drive links only serve
    HTML to browsers) and lets the render reuse the staged file.
    """
    await get_owned_suite(db, suite_id, current_user)
    source_url = str(payload.source_url or "").strip()[:1500]
    if not source_url.startswith("http"):
        raise HTTPException(status_code=400, detail="A valid source URL is required.")

    staging_id = f"staging-{uuid.uuid4().hex[:10]}"
    output_dir = job_dir(staging_id)
    try:
        source_path, warning = await download_source(source_url, output_dir / "source_from_url.mp4")
        if not source_path:
            raise HTTPException(status_code=400, detail=warning or "Could not download the source video.")
        normalized = await asyncio.to_thread(normalize_montage_source, source_path, output_dir)
        if not normalized:
            raise HTTPException(status_code=500, detail="Could not prepare the source video.")
        staged_url = await asyncio.to_thread(publish_veed_source, staging_id, normalized)
        if not staged_url or not staged_url.startswith("https://"):
            raise HTTPException(status_code=500, detail="Cloud storage is not available for staging.")
        return {"staged_url": staged_url}
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def parse_offset(raw: str) -> float:
    """Clamp a subject position offset to -40..40 percent of the canvas."""
    try:
        value = float(str(raw).strip() or "0")
    except ValueError:
        value = 0.0
    return max(-40.0, min(40.0, round(value, 1)))


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
    subject_offset_x: str = Form("0"),
    subject_offset_y: str = Form("0"),
    source_file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    # Multiple montage jobs may queue at once; the worker serializes actual
    # renders through its render-slot gate, so no active-job early return.
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
        "subject_offset_x": parse_offset(subject_offset_x),
        "subject_offset_y": parse_offset(subject_offset_y),
    }
    # Stage the uploaded source BEFORE the job row exists. The worker polls
    # for queued jobs every couple of seconds, so creating the job first and
    # attaching the source afterwards let the worker claim a job whose input
    # had no source yet — it then "completed" instantly with nothing rendered.
    job_id = str(uuid.uuid4())
    if source_file and source_file.filename:
        data = await source_file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Video file is too large. Maximum is 500 MB.")
        filename = safe_filename(source_file.filename, "source.mp4")
        content_type = source_file.content_type or "video/mp4"
        # The worker runs in a separate container, so a local path on the API
        # container is invisible to it — uploads must go through R2.
        if r2_configured():
            stored = await asyncio.to_thread(
                upload_bytes, f"video_montage/{job_id}/upload-{filename}", data, content_type
            )
            input_data["source_url"] = stored.url
            input_data.pop("source_file_path", None)
        else:
            output_dir = job_dir(job_id)
            source_path = output_dir / filename
            source_path.write_bytes(data)
            input_data["source_file_path"] = str(source_path)
        input_data["source_file_name"] = filename
        input_data["source_content_type"] = content_type

    if not input_data.get("source_url") and not input_data.get("source_file_path"):
        raise HTTPException(status_code=400, detail="Provide a source video URL or upload a video file.")

    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.video_montage,
        user_id=current_user.id,
        input_data=input_data,
        job_id=job_id,
    )

    return serialize_job(job, suite_id=suite_id)
