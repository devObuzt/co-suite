import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.product_bulk import (
    ProductBulkAsset,
    ProductBulkAssetStatus,
    ProductBulkBatch,
    ProductBulkBatchStatus,
    ProductBulkItem,
    ProductBulkItemStatus,
    ProductTemplateDirection,
    ProductTemplateDirectionStatus,
)
from ..models.suite import Suite
from .ai_router import (
    AiRoute,
    AiRouteDecision,
    language_prompt_rules,
    media_backend_for_urls,
    public_url_ready,
    resolve_ai_route,
    text_rendering_mode_for_media,
)
from .content_generator import _generate_image
from .generation_jobs import classify_provider_limit
from .media_storage import store_post_media

log = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[dict], None]]

TEMPLATE_DIRECTIONS = [
    {
        "name": "Sales-forward product ad",
        "description": "Direct product offer with strong price visibility and clear visual hierarchy.",
        "visual_rules": {"style": "sales", "price_prominence": "high"},
        "prompt_rules": {"layout": "product, benefit, price, clear CTA"},
    },
    {
        "name": "Clean catalog showcase",
        "description": "Minimal product-first layout suitable for product catalogs and retargeting.",
        "visual_rules": {"style": "catalog", "price_prominence": "medium"},
        "prompt_rules": {"layout": "large product image, clean details, restrained CTA"},
    },
    {
        "name": "Brand-led premium social design",
        "description": "More expressive branded design with premium feel and social scroll appeal.",
        "visual_rules": {"style": "premium_social", "price_prominence": "balanced"},
        "prompt_rules": {"layout": "brand mood, product, slogan, soft CTA"},
    },
]


def _direction_data(direction: ProductTemplateDirection) -> dict:
    return {
        "name": direction.name,
        "description": direction.description,
        "visual_rules": direction.visual_rules or {},
        "prompt_rules": direction.prompt_rules or {},
    }


def _detect_text_language(*values: str | None) -> str | None:
    text = " ".join(value or "" for value in values)
    if any("\u0600" <= ch <= "\u06ff" for ch in text):
        return "ar"
    if any("\u0590" <= ch <= "\u05ff" for ch in text):
        return "he"
    return None


def _suite_language(suite: Suite, item: ProductBulkItem | None = None) -> str:
    if item:
        detected = _detect_text_language(item.product_name, item.slogan, item.description, item.notes)
        if detected:
            return detected
    brand = suite.brand or {}
    languages = brand.get("audience_languages") or brand.get("languages") or []
    if languages:
        return str(languages[0]).split("-", 1)[0].lower() or "en"
    user_language = brand.get("user_language")
    if user_language:
        return str(user_language).split("-", 1)[0].lower() or "en"
    return "en"


def _asset_ai_metadata(
    *,
    direction_data: dict,
    phase: str,
    decision: AiRouteDecision,
    language: str,
    media_url: str | None = None,
) -> dict:
    urls = [media_url] if media_url else []
    return {
        "template_direction": direction_data,
        "phase": phase,
        "ai_route": decision.route,
        "provider": decision.provider,
        "model": decision.model,
        "model_version": decision.model_version,
        "prompt_policy_version": decision.prompt_policy_version,
        "language": language,
        "text_rendering_mode": text_rendering_mode_for_media(language, "native_text_design"),
        "media_backend": media_backend_for_urls(urls),
        "public_url_ready": public_url_ready(urls),
        "fallback_chain_used": [],
        "cost_estimate": decision.cost_estimate,
        "usage_event_id": "usage_event_pending",
        "safety_status": "not_checked",
    }


def _product_prompt(suite: Suite, batch: ProductBulkBatch, item: ProductBulkItem, direction: dict) -> str:
    language = _suite_language(suite, item)
    lines = [
        "Create a finished product marketing image.",
        "Use the attached product image as the exact product reference.",
        "Do not invent, replace, distort, or redesign the product itself.",
        "Keep the design production-ready for social media and ads.",
        f"Use exactly one product/business language in all visible text: {language}.",
        *language_prompt_rules(language),
        "",
    ]

    if batch.brand_enabled:
        lines.extend(
            [
                f"Business: {suite.name}",
                f"Brand data: {suite.brand or {}}",
                "",
            ]
        )

    lines.extend(
        [
            f"Product name: {item.product_name}",
            f"Slogan: {item.slogan or ''}",
            f"Description: {item.description or ''}",
            f"Price: {item.price or ''}",
            f"Global addition for all designs: {item.global_addition or ''}",
            f"Notes: {item.notes or ''}",
            f"User creative direction: {batch.creative_prompt or ''}",
            "",
            f"Template direction: {direction.get('name')}",
            f"Direction description: {direction.get('description')}",
            f"Visual rules: {direction.get('visual_rules')}",
            f"Prompt rules: {direction.get('prompt_rules')}",
            "Output should be a single 4:5 image. If text is included, keep it readable and use the product/business language.",
        ]
    )
    return "\n".join(lines)


def _open_reference_image(data: bytes):
    from PIL import Image

    image = Image.open(BytesIO(data))
    image.load()
    return image


def _load_product_reference_image(image_url: str):
    try:
        if image_url.startswith("/static/"):
            path = Path(__file__).parent.parent / image_url.lstrip("/")
            if not path.exists():
                raise FileNotFoundError(path)
            return _open_reference_image(path.read_bytes())

        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Unsupported product image URL scheme.")

        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
            return _open_reference_image(response.content)
    except Exception:
        log.exception("Could not load product reference image %s", image_url)
        raise


def _generate_and_store_product_image(
    asset_id: str,
    image_url: str,
    prompt: str,
    filename: str,
    language: str,
    route: AiRoute,
) -> Optional[str]:
    reference_image = _load_product_reference_image(image_url)
    image_bytes = _generate_image(
        prompt,
        "4:5",
        extra_images=[reference_image],
        route=route,
        language=language,
        visible_text="product text",
    )
    if not image_bytes:
        return None

    stored = store_post_media(asset_id, f"{asset_id}_{filename}", image_bytes, "image/png")
    return stored.url


async def _load_batch(db: AsyncSession, batch_id: str) -> ProductBulkBatch:
    result = await db.execute(
        select(ProductBulkBatch)
        .where(ProductBulkBatch.id == batch_id)
        .options(
            selectinload(ProductBulkBatch.items).selectinload(ProductBulkItem.assets),
            selectinload(ProductBulkBatch.template_directions),
            selectinload(ProductBulkBatch.assets),
        )
    )
    return result.scalar_one()


async def _create_asset(
    db: AsyncSession,
    batch: ProductBulkBatch,
    item: ProductBulkItem,
    direction: ProductTemplateDirection,
    direction_data: dict,
    prompt: str,
    phase: str,
    decision: AiRouteDecision,
    language: str,
) -> ProductBulkAsset:
    asset = ProductBulkAsset(
        batch_id=batch.id,
        item_id=item.id,
        template_direction_id=direction.id,
        status=ProductBulkAssetStatus.generating,
        media_type="image",
        prompt=prompt,
        ai_metadata=_asset_ai_metadata(
            direction_data=direction_data,
            phase=phase,
            decision=decision,
            language=language,
        ),
    )
    db.add(asset)
    await db.flush()
    return asset


async def _generate_asset_image(
    db: AsyncSession,
    asset: ProductBulkAsset,
    item: ProductBulkItem,
    prompt: str,
    filename: str,
    language: str,
    route: AiRoute,
) -> bool:
    if not item.image_url:
        asset.status = ProductBulkAssetStatus.failed
        asset.feedback = "Missing product image. Generation requires a matched stored product image."
        await db.flush()
        return False

    try:
        media_url = await asyncio.to_thread(
            _generate_and_store_product_image,
            asset.id,
            item.image_url,
            prompt,
            filename,
            language,
            route,
        )
    except Exception as exc:
        if classify_provider_limit(exc):
            raise
        asset.status = ProductBulkAssetStatus.failed
        asset.feedback = str(exc)
        await db.flush()
        return False

    if not media_url:
        asset.status = ProductBulkAssetStatus.failed
        asset.feedback = "Image provider returned no product image."
        await db.flush()
        return False

    asset.media_url = media_url
    asset.ai_metadata = {
        **(asset.ai_metadata or {}),
        "media_backend": media_backend_for_urls([media_url]),
        "public_url_ready": public_url_ready([media_url]),
    }
    asset.status = ProductBulkAssetStatus.generated
    await db.flush()
    return True


def _existing_full_batch_asset(item: ProductBulkItem, template_id: str) -> Optional[ProductBulkAsset]:
    for asset in item.assets:
        if (
            asset.template_direction_id == template_id
            and asset.status in {ProductBulkAssetStatus.generated, ProductBulkAssetStatus.approved}
            and asset.ai_metadata
            and asset.ai_metadata.get("phase") == "full_batch"
        ):
            return asset
    return None


async def generate_first_product_templates(
    db: AsyncSession,
    suite_id: str,
    batch_id: str,
    progress: ProgressCallback = None,
) -> list[str]:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one()
    batch = await _load_batch(db, batch_id)
    items = sorted(batch.items, key=lambda item: item.row_index)
    if not items:
        raise ValueError("Product bulk batch has no products.")
    if batch.template_directions:
        raise ValueError("Template directions already exist for this batch.")

    first_item = items[0]
    if not first_item.image_url:
        first_item.status = ProductBulkItemStatus.failed
        batch.status = ProductBulkBatchStatus.failed
        await db.commit()
        raise ValueError("First product has no stored product image. Upload a matched product image before generating templates.")

    batch.status = ProductBulkBatchStatus.first_generating
    first_item.status = ProductBulkItemStatus.first_sample
    await db.commit()

    created_asset_ids: list[str] = []
    for idx, direction_data in enumerate(TEMPLATE_DIRECTIONS, start=1):
        if progress:
            progress(
                {
                    "status": "running",
                    "stage": "template",
                    "message": f"Generating template {idx}/3.",
                    "progress": 10 + idx * 25,
                }
            )

        direction = ProductTemplateDirection(batch_id=batch.id, **direction_data)
        db.add(direction)
        await db.flush()

        prompt = _product_prompt(suite, batch, first_item, direction_data)
        language = _suite_language(suite, first_item)
        decision = resolve_ai_route(
            AiRoute.product_bulk_template,
            tenant_context={"language": language},
            request_context={"language": language, "visible_text": True, "count": 1},
        )
        asset = await _create_asset(
            db,
            batch,
            first_item,
            direction,
            direction_data,
            prompt,
            "first_product",
            decision,
            language,
        )
        await db.commit()
        try:
            await _generate_asset_image(
                db,
                asset,
                first_item,
                prompt,
                "product-template.png",
                language,
                AiRoute.product_bulk_template,
            )
        except Exception as exc:
            if classify_provider_limit(exc):
                raise
            asset.status = ProductBulkAssetStatus.failed
            asset.feedback = str(exc)
        direction.sample_asset_id = asset.id
        created_asset_ids.append(asset.id)
        await db.commit()

    batch.status = ProductBulkBatchStatus.awaiting_template_approval
    await db.commit()
    return created_asset_ids


async def approve_template_direction(db: AsyncSession, batch_id: str, template_id: str) -> None:
    batch = await _load_batch(db, batch_id)
    selected = next((direction for direction in batch.template_directions if direction.id == template_id), None)
    if not selected:
        raise ValueError("Template direction does not belong to this batch.")

    for direction in batch.template_directions:
        direction.status = (
            ProductTemplateDirectionStatus.approved
            if direction.id == template_id
            else ProductTemplateDirectionStatus.rejected
        )
    batch.approved_template_id = selected.id
    batch.status = ProductBulkBatchStatus.approved_template
    await db.commit()


async def generate_all_products(
    db: AsyncSession,
    suite_id: str,
    batch_id: str,
    progress: ProgressCallback = None,
) -> list[str]:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one()
    batch = await _load_batch(db, batch_id)
    direction = next((item for item in batch.template_directions if item.id == batch.approved_template_id), None)
    if not direction:
        raise ValueError("Approve a template direction before generating all products.")

    direction_data = _direction_data(direction)
    items = sorted(batch.items, key=lambda item: item.row_index)
    if items and not any(item.image_url for item in items):
        batch.status = ProductBulkBatchStatus.failed
        batch.completed_products = 0
        batch.failed_products = len(items)
        for item in items:
            item.status = ProductBulkItemStatus.failed
        await db.commit()
        raise ValueError("No products have stored product images. Upload matched product images before generating.")

    batch.status = ProductBulkBatchStatus.generating_all
    batch.completed_products = 0
    batch.failed_products = 0
    await db.commit()

    asset_ids: list[str] = []
    for idx, item in enumerate(items, start=1):
        if progress:
            progress(
                {
                    "status": "running",
                    "stage": "batch",
                    "message": f"Generating product {idx}/{len(items)}.",
                    "progress": 10 + int(80 * idx / max(1, len(items))),
                }
            )

        reusable = _existing_full_batch_asset(item, direction.id)
        if reusable:
            item.status = ProductBulkItemStatus.generated
            batch.completed_products += 1
            asset_ids.append(reusable.id)
            await db.commit()
            continue

        item.status = ProductBulkItemStatus.generating
        prompt = _product_prompt(suite, batch, item, direction_data)
        language = _suite_language(suite, item)
        decision = resolve_ai_route(
            AiRoute.product_bulk_asset,
            tenant_context={"language": language},
            request_context={"language": language, "visible_text": True, "count": 1},
        )
        asset = await _create_asset(
            db,
            batch,
            item,
            direction,
            direction_data,
            prompt,
            "full_batch",
            decision,
            language,
        )
        await db.commit()
        try:
            generated = await _generate_asset_image(
                db,
                asset,
                item,
                prompt,
                "product.png",
                language,
                AiRoute.product_bulk_asset,
            )
        except Exception as exc:
            if classify_provider_limit(exc):
                raise
            generated = False
            asset.status = ProductBulkAssetStatus.failed
            asset.feedback = str(exc)

        if generated:
            item.status = ProductBulkItemStatus.generated
            batch.completed_products += 1
        else:
            item.status = ProductBulkItemStatus.failed
            batch.failed_products += 1
        asset_ids.append(asset.id)
        await db.commit()

    batch.status = ProductBulkBatchStatus.completed
    await db.commit()
    return asset_ids


async def regenerate_product_asset(
    db: AsyncSession,
    suite_id: str,
    batch_id: str,
    asset_id: str,
    feedback: Optional[str] = None,
    progress: ProgressCallback = None,
) -> str:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one()
    batch = await _load_batch(db, batch_id)
    original_asset = next((asset for asset in batch.assets if asset.id == asset_id), None)
    if not original_asset:
        raise ValueError("Product bulk asset does not belong to this batch.")

    item = next((product for product in batch.items if product.id == original_asset.item_id), None)
    if not item:
        raise ValueError("Product bulk asset item does not belong to this batch.")

    direction = next(
        (
            template
            for template in batch.template_directions
            if template.id == (original_asset.template_direction_id or batch.approved_template_id)
        ),
        None,
    )
    if not direction:
        raise ValueError("Product bulk asset template direction is no longer available.")

    direction_data = _direction_data(direction)
    prompt = _product_prompt(suite, batch, item, direction_data)
    clean_feedback = (feedback or "").strip()
    if clean_feedback:
        prompt += f"\n\nRegeneration feedback: {clean_feedback}"

    if progress:
        progress(
            {
                "status": "running",
                "stage": "regenerate",
                "message": "Regenerating product asset.",
                "progress": 35,
            }
        )

    item.status = ProductBulkItemStatus.generating
    language = _suite_language(suite, item)
    decision = resolve_ai_route(
        AiRoute.product_bulk_asset,
        tenant_context={"language": language},
        request_context={"language": language, "visible_text": True, "count": 1},
    )
    new_asset = await _create_asset(
        db,
        batch,
        item,
        direction,
        direction_data,
        prompt,
        "regenerate_asset",
        decision,
        language,
    )
    new_asset.ai_metadata = {
        **(new_asset.ai_metadata or {}),
        "regenerated_from_asset_id": original_asset.id,
        "feedback": clean_feedback,
    }
    await db.commit()

    try:
        generated = await _generate_asset_image(
            db,
            new_asset,
            item,
            prompt,
            "product-regenerate.png",
            language,
            AiRoute.product_bulk_asset,
        )
    except Exception as exc:
        if classify_provider_limit(exc):
            raise
        generated = False
        new_asset.status = ProductBulkAssetStatus.failed
        new_asset.feedback = str(exc)

    if generated:
        item.status = ProductBulkItemStatus.generated
    else:
        item.status = ProductBulkItemStatus.failed
    await db.commit()
    return new_asset.id
