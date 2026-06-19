from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime, timezone
import asyncio
import mimetypes
import re
import uuid

from ..core.database import get_db, AsyncSessionLocal
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite, SuiteMember, SuiteStatus, MemberRole
from ..models.content import ContentPost, PostStatus
from ..models.generation_job import GenerationJobType
from ..services.billing import enforce_generation_gate, estimate_content_generation_tokens
from ..services.content_generator import generate_content_for_suite
from ..services.generation_jobs import (
    classify_provider_limit,
    create_job,
    get_active_job,
    get_latest_job,
    mark_completed,
    mark_failed,
    mark_progress,
    mark_provider_limit,
    mark_running,
    serialize_job,
)
from ..services.media_storage import StoredMedia, media_readiness_for_post, r2_configured, store_brand_asset
from ..services.publisher import publish_post as _publish_post

router = APIRouter(prefix="/content", tags=["content"])


class PostOut(BaseModel):
    id: str
    format: str
    status: str
    topic: Optional[str]
    caption: Optional[str]
    hashtags: Optional[list]
    media_urls: Optional[list]
    media_readiness: Optional[dict] = None
    ai_metadata: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    count: int = 3
    prompt: Optional[str] = None
    mode: Optional[str] = "set"
    content_type: Optional[str] = "mixed"
    aspect_ratio: Optional[str] = "Auto"
    destination: Optional[str] = "social"
    model_tier: Optional[str] = "auto"
    use_brand: bool = True
    language: Optional[str] = None
    creative_brief: Optional[dict[str, Any]] = None


class RegenerateRequest(BaseModel):
    feedback: Optional[str] = None


class RejectPostRequest(BaseModel):
    reason: Optional[str] = None


class UpdatePostRequest(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    topic: Optional[str] = None


class SchedulePostRequest(BaseModel):
    publish_at: datetime


ACCOUNT_DRAFT_MARKER = "account_level_draft"
QUICK_ASSET_KINDS = {"logo", "product", "style", "character", "icon"}
QUICK_ASSET_EXTENSIONS = {"png", "jpg", "jpeg", "svg", "webp"}
QUICK_ASSET_MAX_BYTES = 15 * 1024 * 1024


def _media_content_type(filename: str, fallback: str | None = None) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return fallback or guessed or "application/octet-stream"


def _serialize_stored_media(stored: StoredMedia) -> dict:
    return {
        "url": stored.url,
        "backend": stored.backend,
        "key": stored.key,
        "public": stored.public,
        "content_type": stored.content_type,
    }


def _slugify(value: str) -> str:
    slug = value.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug or "quick-create"


def serialize_post(post: ContentPost) -> dict:
    return {
        "id": post.id,
        "format": post.format.value if post.format else None,
        "status": post.status.value if post.status else None,
        "topic": post.topic,
        "caption": post.caption,
        "hashtags": post.hashtags,
        "media_urls": post.media_urls,
        "media_readiness": media_readiness_for_post(post),
        "ai_metadata": post.ai_metadata,
        "created_at": post.created_at,
    }


def _apply_rejection_metadata(post: ContentPost, reason: str, user_id: str) -> dict:
    meta = dict(post.ai_metadata or {})
    rejection = {
        "reason": reason,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "rejected_by": user_id,
    }
    meta["last_rejection"] = rejection
    history = list(meta.get("rejection_history") or [])
    history.append(rejection)
    meta["rejection_history"] = history[-20:]
    post.ai_metadata = meta
    return rejection


def _normalize_rejection_reason(data: Optional[RejectPostRequest]) -> str:
    reason = ((data.reason if data else None) or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    return reason


def _mark_regeneration_requested(post: ContentPost, feedback: str, user_id: str) -> dict:
    meta = dict(post.ai_metadata or {})
    request = {
        "feedback": feedback,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": user_id,
    }
    meta["regeneration_requested"] = request
    post.ai_metadata = meta
    return request


def _record_publish_attempt(
    post: ContentPost,
    requested_platforms: set[str],
    successful_platforms: set[str],
    fully_published: bool,
    preflight: dict,
    publish_result: dict,
) -> dict:
    success = bool(successful_platforms)
    status = "published" if fully_published else ("partially_published" if success else "failed")
    attempt = {
        "requested_platforms": sorted(requested_platforms),
        "successful_platforms": sorted(successful_platforms),
        "fully_published": fully_published,
        "publish_mode": preflight.get("publish_mode"),
        "media_readiness": preflight.get("media_readiness"),
        "results": publish_result,
        "status": status,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    meta = dict(post.ai_metadata or {})
    meta["last_publish_result"] = attempt
    attempts = list(meta.get("publish_attempts") or [])
    attempts.append(attempt)
    meta["publish_attempts"] = attempts[-20:]
    post.ai_metadata = meta
    return attempt


async def _run_generation(
    suite_id: str,
    job_id: str,
    count: int = 3,
    options: Optional[dict] = None,
):
    """Background task — runs outside the request's DB session."""
    def progress(event: dict):
        async def _write():
            async with AsyncSessionLocal() as progress_db:
                await mark_progress(progress_db, job_id, event)

        try:
            asyncio.create_task(_write())
        except RuntimeError:
            pass

    async with AsyncSessionLocal() as db:
        await mark_running(db, job_id, "Preparing content generation.")
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
            limit = classify_provider_limit(exc)
            if limit:
                await mark_provider_limit(db, job_id, **limit)
                return
            await mark_failed(db, job_id, str(exc))


async def _get_or_create_account_draft_suite(current_user: User, db: AsyncSession) -> Suite:
    result = await db.execute(select(Suite).where(Suite.owner_id == current_user.id))
    for suite in result.scalars().all():
        if (suite.brand or {}).get(ACCOUNT_DRAFT_MARKER):
            return suite

    email_name = (current_user.email or "account").split("@")[0]
    display_name = current_user.full_name or email_name or "Quick Create"
    base_slug = _slugify(f"quick-create-{current_user.id[:8]}")
    slug = base_slug
    counter = 1
    while True:
        existing = await db.execute(select(Suite).where(Suite.slug == slug))
        if not existing.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    suite = Suite(
        owner_id=current_user.id,
        name="Quick Create",
        slug=slug,
        status=SuiteStatus.active,
        brand={
            ACCOUNT_DRAFT_MARKER: True,
            "name": display_name,
            "description": "Account-level quick generation workspace.",
            "tone": "clear, useful, professional",
            "audience_languages": ["en"],
            "services": [],
            "content_rules": [],
        },
        strategy={},
    )
    db.add(suite)
    await db.flush()
    db.add(SuiteMember(suite_id=suite.id, user_id=current_user.id, role=MemberRole.owner, can_chat_ai=True))
    await db.commit()
    await db.refresh(suite)
    return suite


def _validate_quick_creative_brief(data: GenerateRequest) -> None:
    if (data.mode or "") != "quick" or not data.creative_brief:
        return
    brief = data.creative_brief
    if not isinstance(brief, dict):
        raise HTTPException(status_code=422, detail="creative_brief must be an object")

    required_sizes = brief.get("required_sizes") or {}
    if required_sizes:
        valid_size_ids = {
            "image_all",
            "instagram_post_4_5",
            "meta_square_1_1",
            "vertical_story_9_16",
            "wide_16_9",
            "google_ads_all",
            "video_story_reel_9_16",
            "video_wide_16_9",
        }
        ids = required_sizes.get("ids") or []
        if not isinstance(ids, list) or any(size_id not in valid_size_ids for size_id in ids):
            raise HTTPException(status_code=422, detail="Unsupported required size in creative brief")

    logo = brief.get("logo") or {}
    if isinstance(logo, dict) and logo.get("enabled") and logo.get("source") == "uploaded":
        url = str(logo.get("url") or "")
        if not url.startswith("https://"):
            raise HTTPException(status_code=422, detail="Uploaded logo must have a public HTTPS URL before generation")

    for group in brief.get("reference_assets") or []:
        if not isinstance(group, dict):
            raise HTTPException(status_code=422, detail="Invalid reference asset group")
        kind = str(group.get("kind") or "")
        if kind not in {"product", "style", "character", "icon"}:
            raise HTTPException(status_code=422, detail="Unsupported reference asset kind")
        urls = group.get("urls") or []
        count = int(group.get("count") or 0)
        if count > 0 and (not isinstance(urls, list) or len(urls) < count):
            raise HTTPException(status_code=422, detail="Reference assets must be uploaded before generation")
        if any(not isinstance(url, str) or not url.startswith("https://") for url in urls):
            raise HTTPException(status_code=422, detail="Reference asset URLs must be public HTTPS URLs")

    text_limits = {
        "hook": 30,
        "short_description": 60,
        "terms": 25,
    }
    for field, limit in text_limits.items():
        value = brief.get(field)
        if isinstance(value, str) and len(value) > limit:
            raise HTTPException(status_code=422, detail=f"{field} exceeds {limit} characters")


def _account_options(data: GenerateRequest) -> dict:
    language = (data.language or "en").strip() or "en"
    return {
        "prompt": data.prompt,
        "mode": data.mode or "quick",
        "content_type": data.content_type,
        "aspect_ratio": data.aspect_ratio,
        "destination": data.destination,
        "model_tier": data.model_tier,
        "use_brand": False,
        "account_level": True,
        "language": language,
        "creative_brief": data.creative_brief,
    }


@router.post("/account/generate", status_code=202)
async def generate_account_content(
    data: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_or_create_account_draft_suite(current_user, db)
    brand = dict(suite.brand or {})
    language = (data.language or "en").strip() or "en"
    brand["audience_languages"] = [language]
    brand["name"] = brand.get("name") or current_user.full_name or current_user.email or "Quick Create"
    brand[ACCOUNT_DRAFT_MARKER] = True
    suite.brand = brand
    await db.commit()

    _validate_quick_creative_brief(data)
    options = _account_options(data)
    existing = await get_active_job(db, suite.id)
    if existing:
        return serialize_job(existing)

    count = max(1, min(data.count or 1, 3))
    content_type = data.content_type or "mixed"
    await enforce_generation_gate(
        suite.id,
        db,
        required_tokens=estimate_content_generation_tokens(count, content_type),
        requested_units=count,
        allow_free_trial=content_type.lower() != "video",
        event_type="account_content_generation",
        metadata={"job_type": GenerationJobType.content_generation.value, "content_type": content_type},
    )
    job = await create_job(
        db,
        suite_id=suite.id,
        job_type=GenerationJobType.content_generation,
        user_id=current_user.id,
        input_data={**options, "count": count},
    )
    return serialize_job(job)


@router.get("/account/generation-status")
async def account_generation_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_or_create_account_draft_suite(current_user, db)
    job = await get_latest_job(db, suite.id)
    return serialize_job(job, suite_id=suite.id)


@router.get("/account", response_model=list[PostOut])
async def list_account_posts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_or_create_account_draft_suite(current_user, db)
    posts_result = await db.execute(
        select(ContentPost)
        .where(ContentPost.suite_id == suite.id)
        .order_by(ContentPost.created_at.desc())
        .limit(24)
    )
    return [serialize_post(post) for post in posts_result.scalars().all()]


async def _upload_quick_asset_for_suite(
    suite_id: str,
    kind: str,
    file: UploadFile,
) -> dict:
    clean_kind = (kind or "").strip().lower()
    if clean_kind not in QUICK_ASSET_KINDS:
        raise HTTPException(status_code=400, detail="Unsupported quick asset kind")
    if not r2_configured():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "public_storage_required",
                "message": "Quick Post/Ad reference uploads require public R2 storage before generation.",
            },
        )

    original_name = file.filename or "quick-asset"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in QUICK_ASSET_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Quick assets must be PNG, JPG, SVG, or WebP")

    content = await file.read(QUICK_ASSET_MAX_BYTES + 1)
    if len(content) > QUICK_ASSET_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Quick asset is too large. Maximum is 15 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded quick asset is empty")

    storage_filename = f"{uuid.uuid4().hex}.{ext}"
    stored = store_brand_asset(
        suite_id=suite_id,
        asset_type=f"quick-{clean_kind}",
        filename=storage_filename,
        data=content,
        content_type=_media_content_type(original_name, file.content_type),
    )
    return {
        "id": uuid.uuid4().hex,
        "kind": clean_kind,
        "name": original_name,
        "url": stored.url,
        "size": len(content),
        "storage": _serialize_stored_media(stored),
    }


@router.post("/account/quick-assets")
async def upload_account_quick_asset(
    kind: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_or_create_account_draft_suite(current_user, db)
    return await _upload_quick_asset_for_suite(suite.id, kind, file)


@router.post("/{suite_id}/quick-assets")
async def upload_quick_asset(
    suite_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return await _upload_quick_asset_for_suite(suite_id, kind, file)


@router.post("/{suite_id}/generate", status_code=202)
async def generate_content(
    suite_id: str,
    data: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    if not suite.brand:
        raise HTTPException(status_code=400, detail="Complete suite onboarding first")

    _validate_quick_creative_brief(data)

    options = {
        "prompt": data.prompt,
        "mode": data.mode,
        "content_type": data.content_type,
        "aspect_ratio": data.aspect_ratio,
        "destination": data.destination,
        "model_tier": data.model_tier,
        "use_brand": data.use_brand,
        "creative_brief": data.creative_brief,
    }
    existing = await get_active_job(db, suite_id)
    if existing:
        return serialize_job(existing)

    content_type = data.content_type or "mixed"
    await enforce_generation_gate(
        suite_id,
        db,
        required_tokens=estimate_content_generation_tokens(data.count, content_type),
        requested_units=max(1, int(data.count or 1)),
        allow_free_trial=content_type.lower() != "video",
        event_type="suite_content_generation",
        metadata={"job_type": GenerationJobType.content_generation.value, "content_type": content_type},
    )
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.content_generation,
        user_id=current_user.id,
        input_data={**options, "count": data.count},
    )
    return serialize_job(job)


@router.get("/{suite_id}/generation-status")
async def generation_status(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    job = await get_latest_job(db, suite_id)
    return serialize_job(job, suite_id=suite_id)


@router.get("/{suite_id}", response_model=list[PostOut])
async def list_posts(
    suite_id: str,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    q = select(ContentPost).where(ContentPost.suite_id == suite_id)
    if status:
        try:
            q = q.where(ContentPost.status == PostStatus(status))
        except ValueError:
            pass
    q = q.order_by(ContentPost.created_at.desc())

    posts_result = await db.execute(q)
    return [serialize_post(post) for post in posts_result.scalars().all()]


@router.patch("/{suite_id}/{post_id}", response_model=PostOut)
async def update_post(
    suite_id: str,
    post_id: str,
    data: UpdatePostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    if data.caption is not None:
        post.caption = data.caption
    if data.hashtags is not None:
        post.hashtags = data.hashtags
    if data.topic is not None:
        post.topic = data.topic
    await db.commit()
    await db.refresh(post)
    return serialize_post(post)


@router.post("/{suite_id}/{post_id}/approve")
async def approve_post(
    suite_id: str,
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    post.status = PostStatus.approved
    await db.commit()
    return {"ok": True, "status": "approved"}


@router.post("/{suite_id}/{post_id}/reject")
async def reject_post(
    suite_id: str,
    post_id: str,
    data: Optional[RejectPostRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    reason = _normalize_rejection_reason(data)
    _apply_rejection_metadata(post, reason, current_user.id)
    post.status = PostStatus.rejected
    await db.commit()
    return {"ok": True, "status": "rejected", "reason": reason}


@router.post("/{suite_id}/{post_id}/schedule")
async def schedule_post(
    suite_id: str,
    post_id: str,
    data: SchedulePostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    post.publish_at = data.publish_at
    post.status = PostStatus.scheduled
    await db.commit()
    return {"ok": True, "status": "scheduled", "publish_at": post.publish_at}


@router.post("/{suite_id}/{post_id}/mark-used")
async def mark_post_used(
    suite_id: str,
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    meta = dict(post.ai_metadata or {})
    meta["used_externally"] = True
    meta["used_externally_at"] = datetime.now(timezone.utc).isoformat()
    post.ai_metadata = meta
    post.platform_post_ids = {**(post.platform_post_ids or {}), "external": "used_without_app"}
    post.status = PostStatus.published
    post.published_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "status": "published", "used_externally": True}


@router.post("/{suite_id}/{post_id}/regenerate", status_code=202)
async def regenerate_post(
    suite_id: str,
    post_id: str,
    data: RegenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    existing = await get_active_job(db, suite_id)
    if existing:
        return serialize_job(existing)

    suite_result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = suite_result.scalar_one_or_none()
    feedback = (data.feedback or "").strip()
    if feedback and suite:
        brand = dict(suite.brand or {})
        rules = list(brand.get("content_rules") or [])
        rules.append({
            "text": feedback,
            "source": "regenerate_feedback",
            "post_id": post_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        brand["content_rules"] = rules[-50:]
        suite.brand = brand

    options = {
        "mode": "quick",
        "content_type": post.format.value,
        "feedback": feedback,
        "prompt": feedback,
        "regenerate_from": post.ai_metadata or {},
        "use_brand": True,
    }
    _mark_regeneration_requested(post, feedback, current_user.id)
    await db.commit()

    await enforce_generation_gate(
        suite_id,
        db,
        required_tokens=estimate_content_generation_tokens(1, post.format.value if post.format else "mixed"),
        requested_units=1,
        allow_free_trial=(post.format.value if post.format else "mixed") != "video",
        event_type="content_regeneration",
        metadata={"job_type": GenerationJobType.content_regeneration.value, "post_id": post_id},
    )
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.content_regeneration,
        user_id=current_user.id,
        input_data={**options, "count": 1, "post_id": post_id, "preserve_original": True},
    )
    return serialize_job(job)


class PublishRequest(BaseModel):
    platforms: list[str] = ["facebook", "instagram"]
    allow_text_only: bool = False


def _publish_preflight(post: ContentPost, platforms: list[str], allow_text_only: bool = False) -> tuple[list[str], dict]:
    requested = [platform for platform in platforms if platform in {"facebook", "instagram"}]
    readiness = media_readiness_for_post(post, requested)
    if readiness.get("state") == "not_required":
        if set(requested).issubset({"facebook"}):
            return ["facebook"], {
                "media_readiness": readiness,
                "publish_mode": "text_only",
                "warnings": [],
            }
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Instagram publishing requires public media.",
                "media_readiness": readiness,
                "allowed_actions": [
                    "retry_media_generation",
                    "configure_public_media_storage",
                    "publish_facebook_text_only",
                ],
            },
        )

    if readiness.get("publish_ready"):
        return requested, {
            "media_readiness": readiness,
            "publish_mode": "media",
            "warnings": [],
        }

    if allow_text_only and set(requested).issubset({"facebook"}):
        return ["facebook"], {
            "media_readiness": readiness,
            "publish_mode": "text_only",
            "warnings": [
                readiness.get("reason")
                or "Media is not publish-ready, so this will publish as a Facebook text-only post."
            ],
        }

    raise HTTPException(
        status_code=400,
        detail={
            "message": "Media is not ready for publishing.",
            "media_readiness": readiness,
            "allowed_actions": [
                "retry_media_generation",
                "configure_public_media_storage",
                "publish_facebook_text_only",
            ],
        },
    )


@router.post("/{suite_id}/{post_id}/publish")
async def publish_post(
    suite_id: str,
    post_id: str,
    data: PublishRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    if post.status not in (PostStatus.approved, PostStatus.scheduled):
        raise HTTPException(status_code=400, detail="Post must be approved before publishing")

    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    connections = suite.connections or {}

    if not connections.get("facebook") and not connections.get("instagram"):
        raise HTTPException(status_code=400, detail="No platforms connected. Connect Facebook or Instagram first.")

    publish_platforms, preflight = _publish_preflight(post, data.platforms, data.allow_text_only)
    publish_result = await asyncio.to_thread(
        _publish_post,
        post,
        connections,
        publish_platforms,
        allow_text_only=preflight.get("publish_mode") == "text_only",
    )
    if preflight.get("warnings"):
        publish_result.setdefault("warnings", [])
        publish_result["warnings"].extend(preflight["warnings"])

    requested_platforms = {platform for platform in publish_platforms if platform in ("facebook", "instagram")}
    successful_platforms = {
        platform for platform in ("facebook", "instagram")
        if platform in publish_result
    }
    success = bool(successful_platforms)
    fully_published = success and requested_platforms.issubset(successful_platforms)

    existing_platform_ids = dict(post.platform_post_ids or {})
    if success:
        existing_platform_ids.update({
            k: v for k, v in publish_result.items()
            if k in ("facebook", "instagram")
        })
        post.platform_post_ids = existing_platform_ids

    publish_attempt = _record_publish_attempt(
        post,
        requested_platforms,
        successful_platforms,
        fully_published,
        preflight,
        publish_result,
    )
    if not success:
        existing_platform_ids["last_failed_publish"] = publish_attempt["attempted_at"]
        post.platform_post_ids = existing_platform_ids

    if fully_published:
        post.status = PostStatus.published
        post.published_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "ok": success,
        "results": publish_result,
        "status": "published" if fully_published else ("partially_published" if success else "failed"),
        "fully_published": fully_published,
        "media_readiness": preflight.get("media_readiness"),
    }


async def _get_post(suite_id: str, post_id: str, current_user: User, db: AsyncSession) -> ContentPost:
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    post_result = await db.execute(
        select(ContentPost).where(ContentPost.id == post_id, ContentPost.suite_id == suite_id)
    )
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post
