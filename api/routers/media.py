from __future__ import annotations

import asyncio
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.observability import log_event
from ..core.security import get_current_user
from ..models.admin import CreativeAsset
from ..models.media_asset import MediaAsset
from ..models.user import User
from ..services.creative_assets import (
    VISUAL_KINDS,
    create_asset_from_bytes,
    is_user_uploaded_asset,
    list_user_background_assets,
    serialize_creative_asset,
)
from ..services.media_library import build_media_tree, serialize_media_asset
from ..services.user_backgrounds import (
    analyze_image_background,
    analyze_video_background,
    extract_video_frames,
    merge_vocab_tags,
    normalize_image_orientation,
)
from ..services.video_montage import (
    normalize_montage_source,
    probe_duration_seconds,
    probe_video_dimensions,
    probe_video_codec,
    safe_filename,
)
from .video_montage import get_owned_suite

log = logging.getLogger(__name__)

router = APIRouter(prefix="/suites/{suite_id}/media", tags=["media"])

MAX_BACKGROUND_FILES = 10
MAX_BACKGROUND_IMAGE_BYTES = 15 * 1024 * 1024
MAX_BACKGROUND_VIDEO_BYTES = 200 * 1024 * 1024


def _prepare_background_video(data: bytes, filename: str) -> tuple[bytes, float, list[bytes]]:
    """Probe + (if needed) transcode an uploaded video to fit 1080x1920 H.264.

    Returns (mp4 bytes, duration seconds, analysis frames). Runs in a thread.
    """
    with tempfile.TemporaryDirectory(prefix="bg-upload-") as tmp:
        tmp_dir = Path(tmp)
        source = tmp_dir / safe_filename(filename, "background.mp4")
        source.write_bytes(data)
        width, height = probe_video_dimensions(source)
        if width <= 0 or height <= 0:
            raise ValueError("The uploaded video could not be read.")
        prepared = source
        if source.suffix.lower() != ".mp4" or width > 1080 or height > 1920 or probe_video_codec(source) != "h264":
            normalized = normalize_montage_source(source, tmp_dir)
            if not normalized:
                raise ValueError("The uploaded video could not be converted.")
            prepared = normalized
        duration = probe_duration_seconds(prepared)
        frames = extract_video_frames(prepared)
        return prepared.read_bytes(), duration, frames


async def _apply_background_analysis(
    db: AsyncSession,
    asset: CreativeAsset,
    analysis: dict[str, Any] | None,
    *,
    suite_id: str,
    duration_seconds: float | None = None,
) -> None:
    """Persist analysis tags/description (or keep classify fallback on failure)."""
    if duration_seconds and duration_seconds > 0:
        asset.duration_seconds = round(float(duration_seconds), 3)
    if analysis:
        merged = merge_vocab_tags(list(analysis.get("tags") or []))
        asset.tags = sorted(set(asset.tags or []) | set(merged))
        metadata = dict(asset.metadata_json or {})
        metadata["analysis"] = analysis
        asset.metadata_json = metadata
    else:
        log_event(
            log,
            logging.WARNING,
            "Background media analysis failed; keeping fallback classification tags.",
            event="background_analysis_failed",
            suite_id=suite_id,
            asset_id=asset.id,
            kind=asset.kind,
        )
    await db.commit()
    await db.refresh(asset)


@router.post("/backgrounds")
async def upload_background_media(
    suite_id: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload user images/videos as montage backgrounds; analyze each once."""
    await get_owned_suite(db, suite_id, current_user)
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")
    if len(files) > MAX_BACKGROUND_FILES:
        raise HTTPException(status_code=400, detail=f"Upload at most {MAX_BACKGROUND_FILES} files per request.")

    assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    for upload in files:
        filename = safe_filename(upload.filename, "background")
        content_type = upload.content_type or mimetypes.guess_type(filename)[0] or ""
        is_image = content_type.startswith("image/")
        is_video = content_type.startswith("video/")
        if not is_image and not is_video:
            warnings.append(f"{filename}: unsupported file type ({content_type or 'unknown'}).")
            continue
        data = await upload.read()
        limit = MAX_BACKGROUND_VIDEO_BYTES if is_video else MAX_BACKGROUND_IMAGE_BYTES
        if len(data) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"{filename} is too large. Maximum is {limit // (1024 * 1024)} MB per {'video' if is_video else 'image'}.",
            )
        if not data:
            warnings.append(f"{filename}: the file is empty.")
            continue

        duration_seconds: float | None = None
        frames: list[bytes] = []
        if is_image:
            data, content_type = await asyncio.to_thread(normalize_image_orientation, data, content_type)
            kind = "visual_image"
        else:
            try:
                data, duration_seconds, frames = await asyncio.to_thread(_prepare_background_video, data, filename)
            except Exception as exc:
                log.warning("Background video preparation failed for %s: %s", filename, exc)
                warnings.append(f"{filename}: the video could not be processed.")
                continue
            content_type = "video/mp4"
            kind = "visual_video"

        asset = await create_asset_from_bytes(
            db,
            kind=kind,
            title=filename,
            filename=filename if is_image else f"{Path(filename).stem}.mp4",
            data=data,
            content_type=content_type,
            created_by_user_id=current_user.id,
            metadata={"suite_id": suite_id, "user_uploaded": True, "original_filename": upload.filename},
        )
        # Analyze right away, in this request: rows must never stay unanalyzed.
        if is_image:
            analysis = await asyncio.to_thread(analyze_image_background, data, content_type, suite_id=suite_id)
        else:
            analysis = await asyncio.to_thread(analyze_video_background, frames, suite_id=suite_id)
        if not analysis:
            warnings.append(f"{filename}: automatic analysis failed; generic tags were applied.")
        await _apply_background_analysis(db, asset, analysis, suite_id=suite_id, duration_seconds=duration_seconds)
        assets.append(serialize_creative_asset(asset))

    if not assets:
        raise HTTPException(status_code=400, detail=warnings[0] if warnings else "No usable files were uploaded.")
    return {"assets": assets, "warnings": warnings}


@router.get("/backgrounds")
async def list_background_media(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    rows = await list_user_background_assets(db, suite_id)
    return {"assets": [serialize_creative_asset(row) for row in rows]}


@router.delete("/backgrounds/{asset_id}")
async def delete_background_media(
    suite_id: str,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete: the asset stops being listed/picked but stays in storage."""
    await get_owned_suite(db, suite_id, current_user)
    row = (await db.execute(select(CreativeAsset).where(CreativeAsset.id == asset_id))).scalar_one_or_none()
    metadata = row.metadata_json if row and isinstance(row.metadata_json, dict) else {}
    if (
        not row
        or row.kind not in VISUAL_KINDS
        or not is_user_uploaded_asset(row)
        or str(metadata.get("suite_id") or "") != str(suite_id)
    ):
        raise HTTPException(status_code=404, detail="Background not found")
    row.active = False
    await db.commit()
    return {"ok": True, "asset_id": asset_id}


@router.get("/tree")
async def get_media_tree(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    year = func.extract("year", MediaAsset.created_at)
    month = func.extract("month", MediaAsset.created_at)
    result = await db.execute(
        select(
            MediaAsset.library,
            year.label("year"),
            month.label("month"),
            func.count(MediaAsset.id).label("count"),
        )
        .where(MediaAsset.suite_id == suite_id)
        .group_by(MediaAsset.library, year, month)
    )
    return {"libraries": build_media_tree(result.all())}


@router.get("")
async def list_media_assets(
    suite_id: str,
    library: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    stmt = select(MediaAsset).where(MediaAsset.suite_id == suite_id)
    if library:
        stmt = stmt.where(MediaAsset.library == library)
    if year is not None:
        stmt = stmt.where(func.extract("year", MediaAsset.created_at) == year)
    if month is not None:
        stmt = stmt.where(func.extract("month", MediaAsset.created_at) == month)
    stmt = stmt.order_by(MediaAsset.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    return [serialize_media_asset(asset) for asset in result.scalars().all()]
