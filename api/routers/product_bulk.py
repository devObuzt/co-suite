import asyncio
import logging
import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.database import AsyncSessionLocal, get_db
from ..core.security import get_current_user
from ..models.generation_job import GenerationJobType
from ..models.product_bulk import (
    ProductBulkAsset,
    ProductBulkAssetStatus,
    ProductBulkBatch,
    ProductBulkBatchStatus,
    ProductBulkItem,
    ProductBulkItemStatus,
    ProductTemplateDirection,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.billing import enforce_generation_gate
from ..services.generation_jobs import (
    classify_provider_limit,
    create_job,
    get_active_job,
    get_latest_job_for_input,
    mark_completed,
    mark_failed,
    mark_progress,
    mark_provider_limit,
    mark_running,
    serialize_job,
)
from ..services.media_storage import store_brand_asset
from ..services.product_bulk_generator import (
    approve_template_direction,
    generate_all_products,
    generate_first_product_templates,
    regenerate_product_asset,
)
from ..services.product_bulk_parser import (
    IMAGE_CONTENT_TYPES,
    fill_missing_image_refs_from_zip,
    fill_missing_images_from_workbook,
    match_zip_images,
    normalize_filename,
    parse_workbook,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/suites/{suite_id}/product-bulk", tags=["product-bulk"])

MAX_EXCEL_MB = 50
MAX_EXCEL_BYTES = MAX_EXCEL_MB * 1024 * 1024
MAX_ZIP_BYTES = 250 * 1024 * 1024
MAX_PRODUCT_ROWS = 500
MAX_ZIP_ENTRIES = 1000
MAX_MATCHED_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_MATCHED_IMAGE_BYTES = 200 * 1024 * 1024
PRODUCT_BULK_FIRST_TEMPLATE_TOKENS = 300
PRODUCT_BULK_ASSET_TOKENS = 180


class RegenerateAssetRequest(BaseModel):
    feedback: str | None = None


class RejectAssetRequest(BaseModel):
    feedback: str | None = None


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


def _sanitized_zip_basename(filename: str) -> str:
    basename = _zip_filename(filename)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return safe or "image"


def _validate_zip_metadata(zip_bytes: bytes, image_refs: list[str]) -> None:
    wanted = {normalize_filename(ref): ref for ref in image_refs if ref}
    seen_refs: set[str] = set()
    total_matched_bytes = 0

    try:
        with ZipFile(BytesIO(zip_bytes)) as zf:
            entries = zf.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image ZIP contains too many entries. Maximum is {MAX_ZIP_ENTRIES}.",
                )

            for info in entries:
                suffix = PurePosixPath(info.filename).suffix.lower()
                if info.is_dir() or suffix not in IMAGE_CONTENT_TYPES:
                    continue

                original_ref = wanted.get(normalize_filename(info.filename))
                if not original_ref or original_ref in seen_refs:
                    continue

                seen_refs.add(original_ref)
                if info.file_size > MAX_MATCHED_IMAGE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Matched image '{_zip_filename(info.filename)}' is too large. "
                            "Maximum is 15 MB per image."
                        ),
                    )
                total_matched_bytes += info.file_size
                if total_matched_bytes > MAX_TOTAL_MATCHED_IMAGE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Matched images are too large in total. Maximum is 200 MB.",
                    )
    except HTTPException:
        raise
    except BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid image ZIP file.") from exc


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

    if len(excel_bytes) > MAX_EXCEL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Excel file is too large. Maximum is {MAX_EXCEL_MB} MB.",
        )
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="Image ZIP file is too large. Maximum is 250 MB.")

    try:
        parsed = parse_workbook(excel_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}") from exc

    if len(parsed.rows) > MAX_PRODUCT_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"Product import contains too many rows. Maximum is {MAX_PRODUCT_ROWS}.",
        )

    try:
        fill_missing_image_refs_from_zip(parsed.rows, zip_bytes)
        fill_missing_images_from_workbook(parsed.rows, excel_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid product images: {exc}") from exc

    image_refs = [row.get("image_ref", "") for row in parsed.rows]
    _validate_zip_metadata(zip_bytes, image_refs)

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
        matched = image_matches.get(image_ref) or row.get("__embedded_image")
        if matched:
            try:
                row_index = int(row["row_index"])
                stored = store_brand_asset(
                    suite_id=suite.id,
                    asset_type="product-bulk",
                    filename=f"{batch.id}/{row_index}_{_sanitized_zip_basename(matched.filename)}",
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
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Matched product image could not be stored. "
                        "Check public storage configuration and retry."
                    ),
                ) from exc

        db.add(
            ProductBulkItem(
                batch_id=batch.id,
                row_index=int(row["row_index"]),
                product_name=(row.get("product_name") or row.get("description") or "").strip() or "Unnamed product",
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


PRODUCT_BULK_JOB_TYPES = {
    GenerationJobType.product_bulk_generate_first,
    GenerationJobType.product_bulk_generate_all,
    GenerationJobType.product_bulk_regenerate_asset,
}


@router.get("/{batch_id}/generation-status")
async def get_product_bulk_generation_status(
    suite_id: str,
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_batch(db, suite_id, batch_id, current_user)
    job = await get_latest_job_for_input(
        db,
        suite_id=suite_id,
        input_key="batch_id",
        input_value=batch_id,
        job_types=PRODUCT_BULK_JOB_TYPES,
    )
    return serialize_job(job, suite_id=suite_id)


def progress_writer(job_id: str):
    def progress(event: dict) -> None:
        async def _write() -> None:
            async with AsyncSessionLocal() as progress_db:
                await mark_progress(progress_db, job_id, event)

        try:
            asyncio.create_task(_write())
        except RuntimeError:
            pass

    return progress


async def _run_generate_first(suite_id: str, batch_id: str, job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await mark_running(db, job_id, "Generating first product templates.")
        try:
            asset_ids = await generate_first_product_templates(db, suite_id, batch_id, progress_writer(job_id))
            await mark_completed(db, job_id, {"batch_id": batch_id, "asset_ids": asset_ids})
        except Exception as exc:
            limit = classify_provider_limit(exc)
            if limit:
                await mark_provider_limit(db, job_id, **limit)
                return
            await mark_failed(db, job_id, str(exc))


async def _run_generate_all(suite_id: str, batch_id: str, job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await mark_running(db, job_id, "Generating product batch.")
        try:
            asset_ids = await generate_all_products(db, suite_id, batch_id, progress_writer(job_id))
            await mark_completed(db, job_id, {"batch_id": batch_id, "asset_ids": asset_ids})
        except Exception as exc:
            limit = classify_provider_limit(exc)
            if limit:
                await mark_provider_limit(db, job_id, **limit)
                return
            await mark_failed(db, job_id, str(exc))


async def _run_regenerate_asset(
    suite_id: str,
    batch_id: str,
    asset_id: str,
    job_id: str,
    feedback: str | None,
) -> None:
    async with AsyncSessionLocal() as db:
        await mark_running(db, job_id, "Regenerating product asset.")
        try:
            new_asset_id = await regenerate_product_asset(
                db,
                suite_id,
                batch_id,
                asset_id,
                feedback=feedback,
                progress=progress_writer(job_id),
            )
            await mark_completed(
                db,
                job_id,
                {"batch_id": batch_id, "asset_id": new_asset_id, "regenerated_from_asset_id": asset_id},
            )
        except Exception as exc:
            limit = classify_provider_limit(exc)
            if limit:
                await mark_provider_limit(db, job_id, **limit)
                return
            await mark_failed(db, job_id, str(exc))


@router.post("/{batch_id}/generate-first", status_code=202)
async def generate_first(
    suite_id: str,
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    if not batch.items:
        raise HTTPException(status_code=400, detail="Product bulk batch has no products.")
    existing = await get_active_job(db, suite_id)
    if existing:
        return serialize_job(existing)

    await enforce_generation_gate(
        suite_id,
        db,
        required_tokens=PRODUCT_BULK_FIRST_TEMPLATE_TOKENS,
        requested_units=1,
        allow_free_trial=False,
        event_type="product_bulk_generate_first",
        metadata={"job_type": GenerationJobType.product_bulk_generate_first.value, "batch_id": batch.id},
    )
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.product_bulk_generate_first,
        user_id=current_user.id,
        input_data={"batch_id": batch.id},
    )
    return serialize_job(job)


@router.post("/{batch_id}/templates/{template_id}/approve")
async def approve_template(
    suite_id: str,
    batch_id: str,
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    if not any(direction.id == template_id for direction in batch.template_directions):
        raise HTTPException(status_code=404, detail="Product template direction not found")

    await approve_template_direction(db, batch_id, template_id)
    return {"ok": True, "template_id": template_id, "status": "approved_template"}


@router.post("/{batch_id}/generate-all", status_code=202)
async def generate_all(
    suite_id: str,
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    if not batch.approved_template_id:
        raise HTTPException(status_code=400, detail="Approve a template direction before generating all products.")
    if not any(direction.id == batch.approved_template_id for direction in batch.template_directions):
        raise HTTPException(status_code=400, detail="Approved template direction is no longer available.")
    existing = await get_active_job(db, suite_id)
    if existing:
        return serialize_job(existing)

    item_count = max(1, len(batch.items or []))
    await enforce_generation_gate(
        suite_id,
        db,
        required_tokens=item_count * PRODUCT_BULK_ASSET_TOKENS,
        requested_units=item_count,
        allow_free_trial=False,
        event_type="product_bulk_generate_all",
        metadata={
            "job_type": GenerationJobType.product_bulk_generate_all.value,
            "batch_id": batch.id,
            "template_id": batch.approved_template_id,
        },
    )
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.product_bulk_generate_all,
        user_id=current_user.id,
        input_data={"batch_id": batch.id, "template_id": batch.approved_template_id},
    )
    return serialize_job(job)


async def get_asset(db: AsyncSession, batch_id: str, asset_id: str) -> ProductBulkAsset:
    result = await db.execute(
        select(ProductBulkAsset)
        .where(ProductBulkAsset.id == asset_id)
        .where(ProductBulkAsset.batch_id == batch_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Product bulk asset not found")
    return asset


@router.post("/{batch_id}/assets/{asset_id}/approve")
async def approve_asset(
    suite_id: str,
    batch_id: str,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    asset = await get_asset(db, batch.id, asset_id)
    asset.status = ProductBulkAssetStatus.approved
    item = next((product for product in batch.items if product.id == asset.item_id), None)
    if item:
        item.status = ProductBulkItemStatus.approved
    await db.commit()
    return {"ok": True, "asset_id": asset.id, "status": "approved"}


@router.post("/{batch_id}/assets/{asset_id}/reject")
async def reject_asset(
    suite_id: str,
    batch_id: str,
    asset_id: str,
    data: RejectAssetRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    asset = await get_asset(db, batch.id, asset_id)
    feedback = ((data.feedback if data else None) or "").strip()
    asset.status = ProductBulkAssetStatus.rejected
    asset.feedback = feedback or asset.feedback
    asset.ai_metadata = {
        **(asset.ai_metadata or {}),
        "rejection_feedback": feedback,
    }
    item = next((product for product in batch.items if product.id == asset.item_id), None)
    if item:
        item.status = ProductBulkItemStatus.rejected
    await db.commit()
    return {"ok": True, "asset_id": asset.id, "status": "rejected", "feedback": feedback}


@router.post("/{batch_id}/assets/{asset_id}/regenerate", status_code=202)
async def regenerate_asset(
    suite_id: str,
    batch_id: str,
    asset_id: str,
    data: RegenerateAssetRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    asset = await get_asset(db, batch.id, asset_id)
    if not any(item.id == asset.item_id for item in batch.items):
        raise HTTPException(status_code=404, detail="Product bulk item not found")
    if asset.template_direction_id and not any(
        direction.id == asset.template_direction_id for direction in batch.template_directions
    ):
        raise HTTPException(status_code=400, detail="Product template direction is no longer available.")

    existing = await get_active_job(db, suite_id)
    if existing:
        return serialize_job(existing)

    feedback = (data.feedback or "").strip()
    await enforce_generation_gate(
        suite_id,
        db,
        required_tokens=PRODUCT_BULK_ASSET_TOKENS,
        requested_units=1,
        allow_free_trial=False,
        event_type="product_bulk_regenerate_asset",
        metadata={
            "job_type": GenerationJobType.product_bulk_regenerate_asset.value,
            "batch_id": batch.id,
            "asset_id": asset.id,
        },
    )
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.product_bulk_regenerate_asset,
        user_id=current_user.id,
        input_data={"batch_id": batch.id, "asset_id": asset.id, "feedback": feedback},
    )
    return serialize_job(job)
