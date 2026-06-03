import io
import logging
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid as _uuid
from ..core.database import get_db
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite, SuiteStatus
from ..services.brand_ai import extract_brand_from_sources, suggest_brand_identity, suggest_brand_assets
from ..services.media_storage import r2_configured, store_brand_asset
from ..services.strategy_generator import generate_strategy as _generate_strategy

log = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class ExtractBrandRequest(BaseModel):
    suite_id: str
    urls: list[str] = []           # multiple links — website, IG, FB, TikTok, etc.
    business_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    user_language: str = "en"
    ai_provider: Optional[str] = None  # deprecated; onboarding now always uses OpenAI


class SaveBrandRequest(BaseModel):
    suite_id: str
    brand: dict


class GenerateStrategyRequest(BaseModel):
    suite_id: str
    user_language: str = "en"  # UI language selected by user: "ar" | "he" | "en" | "fr" | "es" | "tr"


class SaveBrandStepRequest(BaseModel):
    suite_id: str
    step: str  # "a" | "b" | "c" | "d" | "e" | "f" | "g"
    data: dict


class GenerateBrandAssetsRequest(BaseModel):
    suite_id: str
    generate: list[str]  # ["logo", "colors", "fonts"]
    logo_style: str = "icon_only"  # "icon_only" | "with_name" | "initials"
    user_language: str = "en"


TRANSLATE_LANG_NAMES = {
    "ar": "Arabic (natural Palestinian dialect)",
    "he": "Hebrew",
    "ru": "Russian",
    "fr": "French",
    "es": "Spanish",
    "tr": "Turkish",
    "zh": "Chinese",
}


class TranslateBrandFieldsRequest(BaseModel):
    unique_value: str = ""
    esp: str = ""
    how_they_help: str = ""
    target_language: str = "en"


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
            brand = await extract_brand_from_sources(
                urls,
                data.business_name,
                user_language=data.user_language,
                ai_provider=data.ai_provider,
            )
        elif data.business_name and data.industry:
            brand = await suggest_brand_identity(
                data.business_name,
                data.industry,
                data.description or "",
                user_language=data.user_language,
                ai_provider=data.ai_provider,
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

    return {"brand": brand, "research_debug": (brand or {}).get("research_debug")}


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

    brand = dict(suite.brand or {})

    # Auto-derive target_audience from structured audience_location if missing
    if not brand.get("target_audience"):
        loc = brand.get("audience_location") or {}
        countries = loc.get("countries") or []
        cities = loc.get("cities") or []
        interests = brand.get("audience_interests") or []
        parts = [", ".join(countries + cities)] if (countries or cities) else []
        if interests:
            parts.append("interested in: " + ", ".join(interests))
        brand["target_audience"] = ". ".join(parts) or "General audience"

    # Auto-derive how_they_help from usp_points if missing
    if not brand.get("how_they_help") and brand.get("usp_points"):
        brand["how_they_help"] = brand["usp_points"][0]

    # Auto-derive unique_value from usp_points if missing
    if not brand.get("unique_value") and brand.get("usp_points"):
        brand["unique_value"] = ". ".join(brand["usp_points"])

    # Auto-derive esp from esp_points if missing
    if not brand.get("esp") and brand.get("esp_points"):
        brand["esp"] = ". ".join(brand["esp_points"])

    try:
        strategy = await _generate_strategy(brand, user_language=data.user_language)
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


@router.post("/upload-brand-asset")
async def upload_brand_asset(
    suite_id: str = Form(...),
    asset_type: str = Form(...),   # "logo" | "font" | "persona"
    language: str = Form(default=""),  # language code for fonts (e.g. "ar", "en")
    persona_name: str = Form(default=""),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a logo or font file to R2, save URL to brand."""
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")

    if not r2_configured():
        raise HTTPException(status_code=400, detail="Storage not configured")

    # Validate file type
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if asset_type in ("logo", "persona") and ext not in ("png", "jpg", "jpeg", "svg", "webp"):
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPG, SVG, or WebP")
    if asset_type == "font" and ext not in ("ttf", "otf", "woff", "woff2"):
        raise HTTPException(status_code=400, detail="Font must be TTF, OTF, WOFF, or WOFF2")

    content = await file.read()
    storage_filename = f"{_uuid.uuid4()}.{ext}"

    content_types = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "svg": "image/svg+xml", "webp": "image/webp",
        "ttf": "font/ttf", "otf": "font/otf",
        "woff": "font/woff", "woff2": "font/woff2",
    }

    stored = store_brand_asset(
        suite_id=suite_id,
        asset_type=asset_type,
        filename=storage_filename,
        data=content,
        content_type=content_types.get(ext, "application/octet-stream"),
    )
    url = stored.url

    brand = dict(suite.brand) if suite.brand else {}

    if asset_type == "logo":
        meta = _analyze_image_asset(content, ext)
        brand["logo_url"] = url
        brand["logo_source"] = "uploaded"
        logos = list(brand.get("brand_logos") or [])
        logos.append({
            "name": filename,
            "url": url,
            "format": ext,
            **meta,
        })
        brand["brand_logos"] = logos
    elif asset_type == "font":
        fonts_by_lang = dict(brand.get("fonts_by_language") or {})
        lang_key = language or "all"
        existing = fonts_by_lang.get(lang_key) or []
        if isinstance(existing, list):
            existing = existing + [{"name": filename.rsplit(".", 1)[0], "url": url, "format": ext}]
        fonts_by_lang[lang_key] = existing
        brand["fonts_by_language"] = fonts_by_lang
    elif asset_type == "persona":
        characters = list(brand.get("brand_personas") or [])
        name = (persona_name or "Presenter").strip()
        existing_idx = next((i for i, p in enumerate(characters) if p.get("name") == name), -1)
        image = {"name": filename, "url": url, "format": ext, **_analyze_image_asset(content, ext)}
        if existing_idx >= 0:
            images = list(characters[existing_idx].get("images") or [])
            images.append(image)
            characters[existing_idx]["images"] = images
        else:
            characters.append({"name": name, "role": "", "images": [image]})
        brand["brand_personas"] = characters

    suite.brand = brand
    await db.commit()
    return {"url": url, "brand": brand}


def _analyze_image_asset(content: bytes, ext: str) -> dict:
    """Best-effort dimensions/shape/background analysis for uploaded brand assets."""
    if ext == "svg":
        return {"width": None, "height": None, "shape": "vector", "background": "unknown"}
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(content))
        width, height = image.size
        ratio = width / height if height else 1
        shape = "square" if 0.85 <= ratio <= 1.18 else "horizontal" if ratio > 1.18 else "vertical"
        has_alpha = image.mode in ("RGBA", "LA") or ("transparency" in image.info)
        return {
            "width": width,
            "height": height,
            "shape": shape,
            "background": "transparent" if has_alpha else "unknown",
        }
    except Exception:
        return {"width": None, "height": None, "shape": "unknown", "background": "unknown"}


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
    brand["logo_style"] = data.logo_style
    brand["user_language"] = data.user_language
    try:
        generated = await suggest_brand_assets(brand, data.generate, user_language=data.user_language)
    except Exception as e:
        log.exception("Brand asset generation failed for suite %s", data.suite_id)
        raise HTTPException(status_code=500, detail="Asset generation failed. Please try again.")

    brand.update(generated)
    suite.brand = brand
    await db.commit()
    return {"brand": brand, "generated": generated}


@router.post("/translate-brand-fields")
async def translate_brand_fields(data: TranslateBrandFieldsRequest):
    """Translate USP/ESP/how_they_help from English to the user's preferred language."""
    if not data.target_language or data.target_language == "en":
        return {
            "unique_value": data.unique_value,
            "esp": data.esp,
            "how_they_help": data.how_they_help,
        }

    lang_name = TRANSLATE_LANG_NAMES.get(data.target_language, data.target_language)
    prompt = (
        f"Translate these marketing phrases to {lang_name}. "
        "Keep them natural and professional. "
        "Return ONLY valid JSON with these exact keys, no explanation:\n\n"
        "{\n"
        f'  "unique_value": "{data.unique_value}",\n'
        f'  "esp": "{data.esp}",\n'
        f'  "how_they_help": "{data.how_they_help}"\n'
        "}\n\n"
        f"Translate the VALUES (not the keys) to {lang_name}. If a value is empty, keep it empty."
    )

    try:
        from ..core.llm_client import call_text_ai
        from ..core.config import settings
        from ..services.brand_ai import _parse_json
        raw = await call_text_ai(
            provider="openai",
            model=settings.openai_fast_model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _parse_json(raw)
        return {
            "unique_value": result.get("unique_value") or data.unique_value,
            "esp": result.get("esp") or data.esp,
            "how_they_help": result.get("how_they_help") or data.how_they_help,
        }
    except Exception as e:
        log.warning("Brand field translation failed: %s", e)
        return {
            "unique_value": data.unique_value,
            "esp": data.esp,
            "how_they_help": data.how_they_help,
        }
