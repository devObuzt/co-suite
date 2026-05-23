import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional
from ..core.database import get_db
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite, SuiteMember, SuiteStatus, MemberRole
from ..services.media_storage import storage_status, test_public_storage
from ..services.multi_scraper import search_market_content
from ..services.meta_ads_library import fetch_meta_ads_inspiration

router = APIRouter(prefix="/suites", tags=["suites"])


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug


class CreateSuiteRequest(BaseModel):
    name: str
    website_url: Optional[str] = None
    social_url: Optional[str] = None


class SuiteResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    brand: Optional[dict] = None
    strategy: Optional[dict] = None

    class Config:
        from_attributes = True


class SocialLoopRequest(BaseModel):
    id: Optional[str] = None
    name: str = "Social loop"
    status: str = "draft"
    content_mix: list[dict] = Field(default_factory=list)
    divisions: list[str] = Field(default_factory=list)
    formats: list[dict] = Field(default_factory=list)
    cadence: Optional[dict] = None
    notes: Optional[str] = None


@router.get("/", response_model=list[SuiteResponse])
async def list_suites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.owner_id == current_user.id))
    return result.scalars().all()


@router.post("/", response_model=SuiteResponse, status_code=status.HTTP_201_CREATED)
async def create_suite(
    data: CreateSuiteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_slug = slugify(data.name)
    slug = base_slug
    counter = 1
    while True:
        result = await db.execute(select(Suite).where(Suite.slug == slug))
        if not result.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    suite = Suite(owner_id=current_user.id, name=data.name, slug=slug, status=SuiteStatus.onboarding)
    db.add(suite)
    await db.flush()

    member = SuiteMember(suite_id=suite.id, user_id=current_user.id, role=MemberRole.owner, can_chat_ai=True)
    db.add(member)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.get("/{suite_id}", response_model=SuiteResponse)
async def get_suite(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if suite.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return suite


@router.get("/{suite_id}/storage-status")
async def get_storage_status(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return storage_status()


@router.post("/{suite_id}/storage-test")
async def run_storage_test(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return await test_public_storage()


@router.patch("/{suite_id}/brand")
async def update_brand(
    suite_id: str,
    brand: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    suite.brand = brand
    if suite.status == SuiteStatus.onboarding:
        suite.status = SuiteStatus.active
    await db.commit()
    return {"ok": True}


@router.get("/{suite_id}/loops")
async def list_social_loops(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    brand = suite.brand or {}
    return {"loops": brand.get("social_loops") or [], "suggestions": _loop_suggestions(brand, suite.strategy or {})}


@router.post("/{suite_id}/loops")
async def save_social_loop(
    suite_id: str,
    data: SocialLoopRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    brand = dict(suite.brand or {})
    loops = list(brand.get("social_loops") or [])
    loop = data.model_dump()
    loop["id"] = loop.get("id") or slugify(loop["name"]) or f"loop-{len(loops) + 1}"
    existing_idx = next((i for i, item in enumerate(loops) if item.get("id") == loop["id"]), -1)
    if existing_idx >= 0:
        loops[existing_idx] = loop
    else:
        loops.append(loop)
    brand["social_loops"] = loops
    suite.brand = brand
    await db.commit()
    return {"ok": True, "loop": loop, "loops": loops}


def _loop_suggestions(brand: dict, strategy: dict) -> dict:
    services = brand.get("services") or brand.get("products") or []
    plan = strategy.get("marketing_plan") or {}
    themes = plan.get("content_themes") or []
    divisions = []
    for item in [brand.get("name"), *(services[:4]), *(themes[:4])]:
        if item and item not in divisions:
            divisions.append(item)
    return {
        "content_mix": [
            {"type": "educational", "label": "Educational", "percentage": 30},
            {"type": "branding", "label": "Branding", "percentage": 20},
            {"type": "trust", "label": "Trust", "percentage": 20},
            {"type": "sales", "label": "Sales", "percentage": 20},
            {"type": "results", "label": "Results", "percentage": 10},
        ],
        "divisions": divisions or ["Business", "Services", "Results", "Team"],
        "formats": [
            {"type": "ai_image", "label": "AI image", "enabled": True},
            {"type": "ai_image_text", "label": "AI image with text", "enabled": True},
            {"type": "ai_carousel", "label": "AI carousel", "enabled": True},
            {"type": "ai_carousel_text", "label": "AI carousel with text", "enabled": True},
            {"type": "ai_video_branding", "label": "AI branding video", "enabled": True},
            {"type": "ai_video_animation", "label": "AI animation video", "enabled": True},
            {"type": "manual_upload", "label": "Manual upload", "enabled": True},
        ],
    }


@router.get("/{suite_id}/market-research")
async def market_research(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search for competitor content and trending social posts in the market."""
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = suite.brand or {}
    strategy_data = suite.strategy or {}

    keyword = brand.get("niche") or brand.get("industry") or brand.get("name") or ""
    loc = brand.get("audience_location") or {}
    countries = loc.get("countries") or []
    cities = loc.get("cities") or []
    location = " ".join((cities[:1] + countries[:1])).strip()

    items = await search_market_content(keyword, location, strategy_data)
    return {"results": items}


@router.get("/{suite_id}/meta-ads")
async def meta_ads(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch active Meta Ad Library ads for inspiration."""
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = suite.brand or {}
    connections = dict(suite.connections or {})
    await db.close()

    return await fetch_meta_ads_inspiration(suite.name, brand, connections)
