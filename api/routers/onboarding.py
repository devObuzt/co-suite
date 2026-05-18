import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite, SuiteStatus
from ..services.brand_ai import extract_brand_from_sources, suggest_brand_identity, suggest_brand_assets
from ..services.strategy_generator import generate_strategy as _generate_strategy

log = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class ExtractBrandRequest(BaseModel):
    suite_id: str
    urls: list[str] = []           # multiple links — website, IG, FB, TikTok, etc.
    business_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None


class SaveBrandRequest(BaseModel):
    suite_id: str
    brand: dict


class GenerateStrategyRequest(BaseModel):
    suite_id: str


class SaveBrandStepRequest(BaseModel):
    suite_id: str
    step: str  # "a" | "b" | "c" | "d" | "e" | "f" | "g"
    data: dict


class GenerateBrandAssetsRequest(BaseModel):
    suite_id: str
    generate: list[str]  # ["logo", "colors", "fonts"]


@router.post("/extract-brand")
async def extract_brand(
    data: ExtractBrandRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    # Filter empty strings
    urls = [u.strip() for u in data.urls if u.strip()]

    try:
        if urls:
            brand = await extract_brand_from_sources(urls, data.business_name)
        elif data.business_name and data.industry:
            brand = await suggest_brand_identity(
                data.business_name,
                data.industry,
                data.description or "",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide at least one URL, or a business name + industry"
            )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Brand extraction failed")
        err_str = str(e).lower()
        if "529" in str(e) or "overloaded" in err_str:
            raise HTTPException(status_code=503, detail="The AI service is temporarily busy. Please try again in a few seconds.")
        raise HTTPException(status_code=500, detail="Brand research failed. Please try again.")

    return {"brand": brand}


@router.post("/save-brand")
async def save_brand(
    data: SaveBrandRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    suite.brand = data.brand
    suite.status = SuiteStatus.active
    await db.commit()
    return {"ok": True, "suite_id": suite.id}


@router.post("/generate-strategy")
async def generate_strategy_endpoint(
    data: GenerateStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = suite.brand or {}
    required = ["services", "target_audience", "how_they_help", "unique_value", "esp"]
    missing = [f for f in required if f not in brand or brand[f] is None or brand[f] == "" or brand[f] == []]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required brand fields: {', '.join(missing)}"
        )

    try:
        strategy = await _generate_strategy(brand)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Strategy generation failed for suite %s", data.suite_id)
        err_str = str(e).lower()
        if "529" in str(e) or "overloaded" in err_str:
            raise HTTPException(status_code=503, detail="The AI service is temporarily busy. Please try again in a few seconds.")
        raise HTTPException(status_code=500, detail="Strategy generation failed. Please try again.")

    suite.strategy = strategy
    await db.commit()
    return {"strategy": strategy}


@router.post("/save-brand-step")
async def save_brand_step(
    data: SaveBrandStepRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = dict(suite.brand) if suite.brand else {}
    brand.update(data.data)
    suite.brand = brand
    await db.commit()
    return {"ok": True}


@router.post("/generate-brand-assets")
async def generate_brand_assets_endpoint(
    data: GenerateBrandAssetsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    brand = dict(suite.brand) if suite.brand else {}
    try:
        generated = await suggest_brand_assets(brand, data.generate)
    except Exception as e:
        log.exception("Brand asset generation failed for suite %s", data.suite_id)
        raise HTTPException(status_code=500, detail="Asset generation failed. Please try again.")

    brand.update(generated)
    suite.brand = brand
    await db.commit()
    return {"brand": brand, "generated": generated}
