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
from ..services.content_rules import (
    new_rule,
    normalize_content_rules,
    suggest_rules_from_feedback,
)
from ..services.suite_memory import build_suite_memory_v0, merge_suite_brand

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
    suite_memory: Optional[dict] = None

    class Config:
        from_attributes = True


class SocialLoopRequest(BaseModel):
    id: Optional[str] = None
    name: str = "Social loop"
    status: str = "draft"
    content_pillars: list[dict] = Field(default_factory=list)
    content_mix: list[dict] = Field(default_factory=list)
    divisions: list[str] = Field(default_factory=list)
    formats: list[dict] = Field(default_factory=list)
    cadence: Optional[dict] = None
    platforms: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    approval_flow: Optional[dict] = None
    scheduling_handoff: Optional[dict] = None
    notes: Optional[str] = None


def serialize_suite(suite: Suite) -> dict:
    return {
        "id": suite.id,
        "name": suite.name,
        "slug": suite.slug,
        "status": suite.status.value if suite.status else None,
        "brand": suite.brand,
        "strategy": suite.strategy,
        "suite_memory": build_suite_memory_v0(suite.brand, suite.strategy, suite.connections),
    }


@router.get("/", response_model=list[SuiteResponse])
async def list_suites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.owner_id == current_user.id))
    return [
        serialize_suite(suite)
        for suite in result.scalars().all()
        if not (suite.brand or {}).get("account_level_draft")
    ]


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
    return serialize_suite(suite)


@router.get("/{suite_id}/memory")
async def get_suite_memory(
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
    return build_suite_memory_v0(suite.brand, suite.strategy, suite.connections)


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
    return serialize_suite(suite)


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


@router.delete("/{suite_id}")
async def delete_suite(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a suite and everything that belongs to it.

    Linked users are never deleted — only their membership links. Audit and
    provider-usage history is kept for admins with the suite reference nulled.
    """
    from sqlalchemy import delete as sa_delete, update as sa_update

    from ..models.admin import AuditLog, ProviderUsageEvent
    from ..models.billing import Subscription, UsageEvent
    from ..models.content import ContentPost
    from ..models.generation_job import GenerationJob
    from ..models.media_asset import MediaAsset
    from ..models.product_bulk import (
        ProductBulkAsset,
        ProductBulkBatch,
        ProductBulkItem,
        ProductTemplateDirection,
    )

    suite = await _get_owned_suite(db, suite_id, current_user)

    batch_ids = select(ProductBulkBatch.id).where(ProductBulkBatch.suite_id == suite_id)
    await db.execute(sa_delete(ProductBulkAsset).where(ProductBulkAsset.batch_id.in_(batch_ids)))
    await db.execute(sa_delete(ProductBulkItem).where(ProductBulkItem.batch_id.in_(batch_ids)))
    await db.execute(sa_delete(ProductTemplateDirection).where(ProductTemplateDirection.batch_id.in_(batch_ids)))
    await db.execute(sa_delete(ProductBulkBatch).where(ProductBulkBatch.suite_id == suite_id))
    await db.execute(sa_delete(ContentPost).where(ContentPost.suite_id == suite_id))
    await db.execute(sa_delete(GenerationJob).where(GenerationJob.suite_id == suite_id))
    await db.execute(sa_delete(MediaAsset).where(MediaAsset.suite_id == suite_id))
    await db.execute(sa_delete(UsageEvent).where(UsageEvent.suite_id == suite_id))
    await db.execute(sa_delete(Subscription).where(Subscription.suite_id == suite_id))
    await db.execute(sa_delete(SuiteMember).where(SuiteMember.suite_id == suite_id))
    await db.execute(sa_update(AuditLog).where(AuditLog.suite_id == suite_id).values(suite_id=None))
    await db.execute(sa_update(ProviderUsageEvent).where(ProviderUsageEvent.suite_id == suite_id).values(suite_id=None))
    await db.delete(suite)
    await db.commit()
    return {"ok": True, "deleted_suite_id": suite_id}


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

    suite.brand = merge_suite_brand(suite.brand, brand)
    if suite.status == SuiteStatus.onboarding:
        suite.status = SuiteStatus.active
    await db.commit()
    return {"ok": True}


class ContentRuleInput(BaseModel):
    text: str = ""
    replace_from: str = Field(default="", alias="from")
    replace_to: str = Field(default="", alias="to")

    model_config = {"populate_by_name": True}


class AddContentRulesRequest(BaseModel):
    rules: list[ContentRuleInput] = Field(default_factory=list)
    source: str = "manual"


class TeachContentRulesRequest(BaseModel):
    feedback: str = ""
    original: str = ""
    edited: str = ""


async def _get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


@router.get("/{suite_id}/content-rules")
async def list_content_rules(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_owned_suite(db, suite_id, current_user)
    return {"rules": normalize_content_rules((suite.brand or {}).get("content_rules"))}


@router.post("/{suite_id}/content-rules")
async def add_content_rules(
    suite_id: str,
    data: AddContentRulesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_owned_suite(db, suite_id, current_user)
    incoming = []
    for item in data.rules:
        rule = new_rule(
            text=item.text,
            replace_from=item.replace_from,
            replace_to=item.replace_to,
            source=data.source or "manual",
        )
        if rule:
            incoming.append(rule)
    if not incoming:
        raise HTTPException(status_code=422, detail="No valid rules in request")
    brand = dict(suite.brand or {})
    rules = normalize_content_rules([*(brand.get("content_rules") or []), *incoming])
    brand["content_rules"] = rules
    suite.brand = brand
    await db.commit()
    return {"ok": True, "rules": rules}


@router.delete("/{suite_id}/content-rules/{rule_id}")
async def delete_content_rule(
    suite_id: str,
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_owned_suite(db, suite_id, current_user)
    brand = dict(suite.brand or {})
    rules = normalize_content_rules(brand.get("content_rules"))
    remaining = [rule for rule in rules if rule.get("id") != rule_id]
    if len(remaining) == len(rules):
        raise HTTPException(status_code=404, detail="Rule not found")
    brand["content_rules"] = remaining
    suite.brand = brand
    await db.commit()
    return {"ok": True, "rules": remaining}


@router.post("/{suite_id}/content-rules/teach")
async def teach_content_rules(
    suite_id: str,
    data: TeachContentRulesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_suite(db, suite_id, current_user)
    suggestions = await suggest_rules_from_feedback(data.feedback, data.original, data.edited)
    return {"suggestions": suggestions}


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
    strategy = suite.strategy or {}
    return {
        "loops": brand.get("social_loops") or [],
        "suggestions": _loop_suggestions(brand, strategy),
        "generated_plan": _build_content_plan(brand, strategy, suite.connections or {}),
    }


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
    loop = _normalize_social_loop(data, len(loops))
    existing_idx = next((i for i, item in enumerate(loops) if item.get("id") == loop["id"]), -1)
    if existing_idx >= 0:
        loops[existing_idx] = loop
    else:
        loops.append(loop)
    brand["social_loops"] = loops
    suite.brand = brand
    await db.commit()
    return {"ok": True, "loop": loop, "loops": loops}


def _unique_strings(values: list | tuple | set) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _connected_platforms(connections: dict) -> list[str]:
    platforms = []
    for platform in ["facebook", "instagram", "tiktok", "google_ads"]:
        value = connections.get(platform)
        if isinstance(value, dict) and value:
            platforms.append(platform)
    return platforms or ["instagram", "facebook"]


def _content_pillars(brand: dict, strategy: dict) -> list[dict]:
    plan = strategy.get("marketing_plan") or {}
    candidates = [
        *(plan.get("content_themes") or []),
        *(brand.get("content_themes") or []),
        *(brand.get("services") or brand.get("products") or []),
        brand.get("unique_value"),
    ]
    names = _unique_strings(candidates)[:5] or ["Education", "Trust", "Offer", "Community"]
    percentages = [30, 25, 20, 15, 10]
    return [
        {
            "name": name,
            "percentage": percentages[index] if index < len(percentages) else 10,
            "notes": "Editable pillar for recurring social content.",
        }
        for index, name in enumerate(names)
    ]


def _build_content_plan(brand: dict, strategy: dict, connections: dict) -> dict:
    business_name = (brand.get("name") or "Suite").strip()
    languages = _unique_strings(brand.get("audience_languages") or brand.get("audience_language_names") or ["en"])
    platforms = _connected_platforms(connections)
    return {
        "id": "generated-social-content-plan",
        "name": f"{business_name} social content plan",
        "status": "draft",
        "content_pillars": _content_pillars(brand, strategy),
        "content_mix": _loop_suggestions(brand, strategy)["content_mix"],
        "divisions": _loop_suggestions(brand, strategy)["divisions"],
        "cadence": {
            "posts_per_week": 3,
            "preferred_days": ["Monday", "Wednesday", "Thursday"],
            "preferred_hours": ["10:00", "19:00"],
            "review_buffer_hours": 24,
        },
        "platforms": platforms,
        "formats": [
            {"type": "image", "enabled": True},
            {"type": "carousel", "enabled": True},
            {"type": "short_video", "enabled": "instagram" in platforms or "tiktok" in platforms},
            {"type": "story", "enabled": "instagram" in platforms or "facebook" in platforms},
        ],
        "languages": languages,
        "approval_flow": {
            "required": True,
            "steps": ["draft", "owner_review", "approved", "scheduled"],
            "rejection_path": "Return to draft with feedback before scheduling.",
        },
        "scheduling_handoff": {
            "status": "ready_for_calendar",
            "target": "suite_calendar",
            "requires_connected_platform": False,
            "notes": "Approved items can be handed to the calendar or exported for manual scheduling.",
        },
        "notes": "",
    }


def _normalize_social_loop(data: SocialLoopRequest, existing_count: int) -> dict:
    loop = data.model_dump()
    loop["id"] = loop.get("id") or slugify(loop["name"]) or f"loop-{existing_count + 1}"
    loop["content_pillars"] = list(loop.get("content_pillars") or [])
    loop["content_mix"] = list(loop.get("content_mix") or [])
    loop["divisions"] = _unique_strings(loop.get("divisions") or [])
    loop["formats"] = list(loop.get("formats") or [])
    loop["cadence"] = loop.get("cadence") or {}
    loop["platforms"] = _unique_strings(loop.get("platforms") or [])
    loop["languages"] = _unique_strings(loop.get("languages") or [])
    loop["approval_flow"] = loop.get("approval_flow") or {"required": True, "steps": ["draft", "owner_review", "approved"]}
    loop["scheduling_handoff"] = loop.get("scheduling_handoff") or {"status": "ready_for_calendar"}
    return loop


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
