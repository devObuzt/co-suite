import logging
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.product_bulk import (
    ProductBulkAsset,
    ProductBulkBatch,
    ProductBulkBatchStatus,
    ProductBulkItem,
    ProductTemplateDirection,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.media_storage import store_brand_asset
from ..services.product_bulk_parser import match_zip_images, parse_workbook

log = logging.getLogger(__name__)

router = APIRouter(prefix="/suites/{suite_id}/product-bulk", tags=["product-bulk"])


async def get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


async def get_batch(db: AsyncSession, suite_id: str, batch_id: str, user: User) -> ProductBulkBatch:
    await get_owned_suite(db, suite_id, user)
    result = await db.execute(
        select(ProductBulkBatch)
        .where(ProductBulkBatch.id == batch_id)
        .where(ProductBulkBatch.suite_id == suite_id)
        .options(
            selectinload(ProductBulkBatch.items).selectinload(ProductBulkItem.assets),
            selectinload(ProductBulkBatch.assets),
            selectinload(ProductBulkBatch.template_directions),
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Product bulk batch not found")
    return batch


def serialize_asset(asset: ProductBulkAsset) -> dict:
    return {
        "id": asset.id,
        "item_id": asset.item_id,
        "template_direction_id": asset.template_direction_id,
        "status": asset.status.value,
        "media_url": asset.media_url,
        "media_type": asset.media_type,
        "feedback": asset.feedback,
        "ai_metadata": asset.ai_metadata,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


def serialize_item(item: ProductBulkItem) -> dict:
    return {
        "id": item.id,
        "row_index": item.row_index,
        "product_name": item.product_name,
        "image_ref": item.image_ref,
        "image_url": item.image_url,
        "slogan": item.slogan,
        "description": item.description,
        "price": item.price,
        "global_addition": item.global_addition,
        "notes": item.notes,
        "raw_row": item.raw_row,
        "status": item.status.value,
        "assets": [serialize_asset(asset) for asset in item.assets],
    }


def serialize_template(direction: ProductTemplateDirection) -> dict:
    return {
        "id": direction.id,
        "name": direction.name,
        "description": direction.description,
        "visual_rules": direction.visual_rules,
        "prompt_rules": direction.prompt_rules,
        "sample_asset_id": direction.sample_asset_id,
        "status": direction.status.value,
    }


def serialize_batch(batch: ProductBulkBatch) -> dict:
    return {
        "id": batch.id,
        "suite_id": batch.suite_id,
        "name": batch.name,
        "status": batch.status.value,
        "source_excel_url": batch.source_excel_url,
        "source_zip_url": batch.source_zip_url,
        "creative_prompt": batch.creative_prompt,
        "column_mapping": batch.column_mapping,
        "approved_template_id": batch.approved_template_id,
        "brand_enabled": batch.brand_enabled,
        "total_products": batch.total_products,
        "completed_products": batch.completed_products,
        "failed_products": batch.failed_products,
        "items": [serialize_item(item) for item in sorted(batch.items, key=lambda item: item.row_index)],
        "template_directions": [serialize_template(direction) for direction in batch.template_directions],
        "assets": [serialize_asset(asset) for asset in batch.assets],
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _zip_filename(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).name or "image"


@router.post("")
async def create_product_bulk_batch(
    suite_id: str,
    excel: UploadFile = File(...),
    images_zip: UploadFile = File(...),
    creative_prompt: str = Form(""),
    brand_enabled: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await get_owned_suite(db, suite_id, current_user)
    excel_bytes = await excel.read()
    zip_bytes = await images_zip.read()

    try:
        parsed = parse_workbook(excel_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}") from exc

    image_refs = [row.get("image_ref", "") for row in parsed.rows]
    try:
        image_matches = match_zip_images(zip_bytes, image_refs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image ZIP file: {exc}") from exc

    batch = ProductBulkBatch(
        suite_id=suite.id,
        created_by=current_user.id,
        name=f"{suite.name} product bulk",
        creative_prompt=creative_prompt.strip(),
        column_mapping=parsed.mapping,
        brand_enabled=brand_enabled,
        total_products=len(parsed.rows),
        status=ProductBulkBatchStatus.mapped if parsed.rows else ProductBulkBatchStatus.uploaded,
    )
    db.add(batch)
    await db.flush()

    for row in parsed.rows:
        image_ref = row.get("image_ref") or ""
        image_url = None
        matched = image_matches.get(image_ref)
        if matched:
            try:
                stored = store_brand_asset(
                    suite_id=suite.id,
                    asset_type="product-bulk",
                    filename=f"{batch.id}/{_zip_filename(matched.filename)}",
                    data=matched.data,
                    content_type=matched.content_type,
                )
                image_url = stored.url
            except Exception as exc:
                log.warning(
                    "Product bulk image storage failed for suite=%s batch=%s file=%s: %s",
                    suite.id,
                    batch.id,
                    matched.filename,
                    exc,
                )

        db.add(
            ProductBulkItem(
                batch_id=batch.id,
                row_index=int(row["row_index"]),
                product_name=(row.get("product_name") or "").strip() or "Unnamed product",
                image_ref=image_ref,
                image_url=image_url,
                slogan=row.get("slogan"),
                description=row.get("description"),
                price=row.get("price"),
                global_addition=row.get("global_addition"),
                notes=row.get("notes"),
                raw_row=row.get("raw_row"),
            )
        )

    await db.commit()
    return serialize_batch(await get_batch(db, suite.id, batch.id, current_user))


@router.get("")
async def list_product_bulk_batches(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    result = await db.execute(
        select(ProductBulkBatch)
        .where(ProductBulkBatch.suite_id == suite_id)
        .order_by(ProductBulkBatch.created_at.desc())
        .options(
            selectinload(ProductBulkBatch.items).selectinload(ProductBulkItem.assets),
            selectinload(ProductBulkBatch.assets),
            selectinload(ProductBulkBatch.template_directions),
        )
    )
    return {"batches": [serialize_batch(batch) for batch in result.scalars().all()]}


@router.get("/{batch_id}")
async def get_product_bulk_batch(
    suite_id: str,
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    return serialize_batch(batch)
