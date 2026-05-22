from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from ..core.database import get_db, AsyncSessionLocal
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite
from ..models.content import ContentPost, PostStatus
from ..services.content_generator import generate_content_for_suite
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


class RegenerateRequest(BaseModel):
    feedback: Optional[str] = None


class UpdatePostRequest(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    topic: Optional[str] = None


class SchedulePostRequest(BaseModel):
    publish_at: datetime


async def _run_generation(suite_id: str, count: int = 3, options: Optional[dict] = None):
    """Background task — runs outside the request's DB session."""
    async with AsyncSessionLocal() as db:
        await generate_content_for_suite(suite_id, db, count=count, options=options or {})


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

    options = {
        "prompt": data.prompt,
        "mode": data.mode,
        "content_type": data.content_type,
        "aspect_ratio": data.aspect_ratio,
        "destination": data.destination,
        "model_tier": data.model_tier,
        "use_brand": data.use_brand,
    }
    background_tasks.add_task(_run_generation, suite_id, data.count, options)
    return {"message": "Generation started", "suite_id": suite_id}


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
    return posts_result.scalars().all()


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
    return post


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await _get_post(suite_id, post_id, current_user, db)
    post.status = PostStatus.rejected
    await db.commit()
    return {"ok": True, "status": "rejected"}


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
    await db.delete(post)
    await db.commit()
    background_tasks.add_task(_run_generation_one, suite_id, options)
    return {"message": "Regenerating"}


async def _run_generation_one(suite_id: str, options: Optional[dict] = None):
    async with AsyncSessionLocal() as db:
        await generate_content_for_suite(suite_id, db, count=1, options=options or {})


class PublishRequest(BaseModel):
    platforms: list[str] = ["facebook", "instagram"]


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

    import asyncio
    publish_result = await asyncio.to_thread(_publish_post, post, connections, data.platforms)

    success = "facebook" in publish_result or "instagram" in publish_result
    if success:
        post.status = PostStatus.published
        post.platform_post_ids = {
            k: v for k, v in publish_result.items()
            if k in ("facebook", "instagram")
        }
        from datetime import datetime, timezone
        post.published_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "ok": success,
        "results": publish_result,
        "status": "published" if success else "failed",
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
