# Product Bulk Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated Product Bulk Studio where users upload an Excel sheet and product-image ZIP, approve one of three sample templates for the first product, then generate and review the full catalog.

**Architecture:** Add dedicated product bulk database models and router instead of overloading `content_posts`. Keep parsing, media matching, and image generation in focused services. Reuse the existing durable `generation_jobs` pattern so long-running AI work survives refreshes and exposes provider-limit states.

**Tech Stack:** FastAPI, SQLAlchemy async models, existing R2/local media storage service, existing Gemini image generation path, Next.js dashboard pages, TypeScript API client.

---

## File Structure

- Create `api/models/product_bulk.py`
  - Product bulk batch, item, asset, and template direction models.
- Modify `api/models/__init__.py`
  - Export new models so `Base.metadata.create_all` creates tables.
- Modify `api/models/generation_job.py`
  - Add product bulk job types.
- Create `api/services/product_bulk_parser.py`
  - Parse `.xlsx`, detect column mapping, match ZIP image filenames, normalize rows.
- Create `api/services/product_bulk_generator.py`
  - Generate first-product template candidates, approve template, generate remaining assets, regenerate one asset.
- Create `api/routers/product_bulk.py`
  - Suite-owned API endpoints for upload, mapping, generation, approval, rejection, regeneration, status.
- Modify `api/main.py`
  - Include product bulk router.
- Create `tests/test_product_bulk_parser.py`
  - Cover Hebrew column auto-detection and ZIP image matching.
- Create `tests/test_product_bulk_models.py`
  - Cover enum values and model serialization assumptions.
- Modify `web/src/lib/api.ts`
  - Add Product Bulk types and API methods.
- Modify `web/src/app/(dashboard)/suite/[id]/page.tsx`
  - Add entry point under Create & generate or dashboard action area.
- Create `web/src/app/(dashboard)/suite/[id]/product-bulk/page.tsx`
  - Dedicated Product Bulk Studio UI.

## Task 1: Backend Models

**Files:**
- Create: `api/models/product_bulk.py`
- Modify: `api/models/__init__.py`
- Modify: `api/models/generation_job.py`
- Test: `tests/test_product_bulk_models.py`

- [ ] **Step 1: Write model enum tests**

Create `tests/test_product_bulk_models.py`:

```python
from api.models.generation_job import GenerationJobType
from api.models.product_bulk import (
    ProductBulkAssetStatus,
    ProductBulkBatchStatus,
    ProductBulkItemStatus,
    ProductTemplateDirectionStatus,
)


def test_product_bulk_status_values_are_stable():
    assert ProductBulkBatchStatus.uploaded.value == "uploaded"
    assert ProductBulkBatchStatus.awaiting_template_approval.value == "awaiting_template_approval"
    assert ProductBulkBatchStatus.generating_all.value == "generating_all"
    assert ProductBulkBatchStatus.completed.value == "completed"

    assert ProductBulkItemStatus.pending.value == "pending"
    assert ProductBulkItemStatus.generated.value == "generated"
    assert ProductBulkAssetStatus.approved.value == "approved"
    assert ProductTemplateDirectionStatus.candidate.value == "candidate"


def test_generation_job_types_include_product_bulk_jobs():
    assert GenerationJobType.product_bulk_generate_first.value == "product_bulk_generate_first"
    assert GenerationJobType.product_bulk_generate_all.value == "product_bulk_generate_all"
    assert GenerationJobType.product_bulk_regenerate_asset.value == "product_bulk_regenerate_asset"
```

- [ ] **Step 2: Run the failing model tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest tests/test_product_bulk_models.py -v
```

Expected: FAIL because `api.models.product_bulk` and the new `GenerationJobType` values do not exist.

- [ ] **Step 3: Create product bulk models**

Create `api/models/product_bulk.py`:

```python
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class ProductBulkBatchStatus(str, enum.Enum):
    uploaded = "uploaded"
    mapped = "mapped"
    first_generating = "first_generating"
    awaiting_template_approval = "awaiting_template_approval"
    approved_template = "approved_template"
    generating_all = "generating_all"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ProductBulkItemStatus(str, enum.Enum):
    pending = "pending"
    first_sample = "first_sample"
    generating = "generating"
    generated = "generated"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class ProductBulkAssetStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    generated = "generated"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class ProductTemplateDirectionStatus(str, enum.Enum):
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"


class ProductBulkBatch(Base):
    __tablename__ = "product_bulk_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="Product bulk batch")
    status: Mapped[ProductBulkBatchStatus] = mapped_column(
        Enum(ProductBulkBatchStatus),
        nullable=False,
        default=ProductBulkBatchStatus.uploaded,
        index=True,
    )
    source_excel_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_zip_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    column_mapping: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approved_template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brand_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["ProductBulkItem"]] = relationship("ProductBulkItem", back_populates="batch", cascade="all, delete-orphan")
    assets: Mapped[list["ProductBulkAsset"]] = relationship("ProductBulkAsset", back_populates="batch", cascade="all, delete-orphan")
    template_directions: Mapped[list["ProductTemplateDirection"]] = relationship(
        "ProductTemplateDirection",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class ProductBulkItem(Base):
    __tablename__ = "product_bulk_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    image_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slogan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    global_addition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_row: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[ProductBulkItemStatus] = mapped_column(
        Enum(ProductBulkItemStatus),
        nullable=False,
        default=ProductBulkItemStatus.pending,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="items")
    assets: Mapped[list["ProductBulkAsset"]] = relationship("ProductBulkAsset", back_populates="item", cascade="all, delete-orphan")


class ProductBulkAsset(Base):
    __tablename__ = "product_bulk_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_items.id"), nullable=False, index=True)
    template_direction_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("product_template_directions.id"), nullable=True)
    status: Mapped[ProductBulkAssetStatus] = mapped_column(
        Enum(ProductBulkAssetStatus),
        nullable=False,
        default=ProductBulkAssetStatus.pending,
        index=True,
    )
    media_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False, default="image")
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="assets")
    item: Mapped["ProductBulkItem"] = relationship("ProductBulkItem", back_populates="assets")


class ProductTemplateDirection(Base):
    __tablename__ = "product_template_directions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visual_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    sample_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[ProductTemplateDirectionStatus] = mapped_column(
        Enum(ProductTemplateDirectionStatus),
        nullable=False,
        default=ProductTemplateDirectionStatus.candidate,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="template_directions")
```

- [ ] **Step 4: Export product bulk models**

Modify `api/models/__init__.py`:

```python
from .product_bulk import (
    ProductBulkAsset,
    ProductBulkAssetStatus,
    ProductBulkBatch,
    ProductBulkBatchStatus,
    ProductBulkItem,
    ProductBulkItemStatus,
    ProductTemplateDirection,
    ProductTemplateDirectionStatus,
)
```

Add the same names to `__all__`.

- [ ] **Step 5: Add product bulk job types**

Modify `GenerationJobType` in `api/models/generation_job.py`:

```python
class GenerationJobType(str, enum.Enum):
    content_generation = "content_generation"
    content_regeneration = "content_regeneration"
    product_bulk_import = "product_bulk_import"
    product_bulk_generate_first = "product_bulk_generate_first"
    product_bulk_generate_all = "product_bulk_generate_all"
    product_bulk_regenerate_asset = "product_bulk_regenerate_asset"
```

- [ ] **Step 6: Run model tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest tests/test_product_bulk_models.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit backend models**

Run:

```bash
git add api/models/product_bulk.py api/models/__init__.py api/models/generation_job.py tests/test_product_bulk_models.py
git commit -m "feat: add product bulk models"
```

## Task 2: Excel and ZIP Parser

**Files:**
- Create: `api/services/product_bulk_parser.py`
- Test: `tests/test_product_bulk_parser.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_product_bulk_parser.py`:

```python
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from api.services.product_bulk_parser import (
    DEFAULT_HEBREW_MAPPING,
    detect_column_mapping,
    match_zip_images,
    parse_workbook,
)


def make_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["שם", "תמונה", "סלוגן", "תיאור המוצר", "מחיר לסט שלם + מע\"מ", "תוספת בכל העיצובים", "הערות"])
    ws.append(["שולחן עבודה", "desk 01.jpg", "עובדים נכון", "שולחן למשרד ביתי", "1290", "להוסיף לוגו", "צבע עץ"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def make_zip() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w") as zf:
        zf.writestr("products/desk 01.jpg", b"fake-image")
        zf.writestr("ignore/readme.txt", b"not image")
    return out.getvalue()


def test_detect_column_mapping_supports_hebrew_headers():
    headers = ["שם", "תמונה", "סלוגן", "תיאור המוצר", "מחיר לסט שלם + מע\"מ", "תוספת בכל העיצובים", "הערות"]

    mapping = detect_column_mapping(headers)

    assert mapping["product_name"] == "שם"
    assert mapping["image_ref"] == "תמונה"
    assert mapping["slogan"] == "סלוגן"
    assert mapping["description"] == "תיאור המוצר"
    assert mapping["price"] == "מחיר לסט שלם + מע\"מ"
    assert mapping["global_addition"] == "תוספת בכל העיצובים"
    assert mapping["notes"] == "הערות"
    assert DEFAULT_HEBREW_MAPPING["שם"] == "product_name"


def test_parse_workbook_returns_normalized_products():
    parsed = parse_workbook(make_xlsx())

    assert parsed.headers[0] == "שם"
    assert parsed.mapping["product_name"] == "שם"
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row["product_name"] == "שולחן עבודה"
    assert row["image_ref"] == "desk 01.jpg"
    assert row["price"] == "1290"
    assert row["raw_row"]["הערות"] == "צבע עץ"


def test_match_zip_images_matches_by_basename_and_ignores_non_images():
    matches = match_zip_images(make_zip(), ["desk 01.jpg", "missing.jpg"])

    assert "desk 01.jpg" in matches
    assert matches["desk 01.jpg"].filename == "products/desk 01.jpg"
    assert matches["desk 01.jpg"].content_type == "image/jpeg"
    assert "missing.jpg" not in matches
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest tests/test_product_bulk_parser.py -v
```

Expected: FAIL because parser service does not exist.

- [ ] **Step 3: Implement parser service**

Create `api/services/product_bulk_parser.py`:

```python
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook


DEFAULT_HEBREW_MAPPING = {
    "שם": "product_name",
    "תמונה": "image_ref",
    "סלוגן": "slogan",
    "תיאור המוצר": "description",
    "מחיר לסט שלם + מע\"מ": "price",
    "תוספת בכל העיצובים": "global_addition",
    "הערות": "notes",
}

IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass
class ParsedWorkbook:
    headers: list[str]
    mapping: dict[str, str]
    rows: list[dict[str, Any]]


@dataclass
class ZipImage:
    filename: str
    data: bytes
    content_type: str


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_filename(value: str) -> str:
    cleaned = clean_cell(value).replace("\\", "/")
    return PurePosixPath(cleaned).name.strip().lower()


def detect_column_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        target = DEFAULT_HEBREW_MAPPING.get(clean_cell(header))
        if target:
            mapping[target] = header
    return mapping


def parse_workbook(xlsx_bytes: bytes, mapping: dict[str, str] | None = None) -> ParsedWorkbook:
    wb = load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_row = next((row for row in rows if any(clean_cell(cell) for cell in row)), None)
    if not header_row:
        return ParsedWorkbook(headers=[], mapping={}, rows=[])

    headers = [clean_cell(cell) for cell in header_row]
    active_mapping = mapping or detect_column_mapping(headers)
    header_index = {header: idx for idx, header in enumerate(headers)}
    data_rows: list[dict[str, Any]] = []
    start_idx = rows.index(header_row) + 1

    for row_index, row in enumerate(rows[start_idx:], start=start_idx + 1):
        raw_row = {header: clean_cell(row[idx] if idx < len(row) else "") for header, idx in header_index.items()}
        if not any(raw_row.values()):
            continue
        normalized: dict[str, Any] = {"row_index": row_index, "raw_row": raw_row}
        for field, header in active_mapping.items():
            normalized[field] = raw_row.get(header, "")
        normalized.setdefault("product_name", "")
        normalized.setdefault("image_ref", "")
        data_rows.append(normalized)

    return ParsedWorkbook(headers=headers, mapping=active_mapping, rows=data_rows)


def match_zip_images(zip_bytes: bytes, image_refs: list[str]) -> dict[str, ZipImage]:
    wanted = {normalize_filename(ref): ref for ref in image_refs if clean_cell(ref)}
    matches: dict[str, ZipImage] = {}
    with ZipFile(BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            suffix = PurePosixPath(info.filename).suffix.lower()
            if info.is_dir() or suffix not in IMAGE_CONTENT_TYPES:
                continue
            normalized = normalize_filename(info.filename)
            original_ref = wanted.get(normalized)
            if original_ref and original_ref not in matches:
                matches[original_ref] = ZipImage(
                    filename=info.filename,
                    data=zf.read(info),
                    content_type=IMAGE_CONTENT_TYPES[suffix],
                )
    return matches
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest tests/test_product_bulk_parser.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit parser service**

Run:

```bash
git add api/services/product_bulk_parser.py tests/test_product_bulk_parser.py
git commit -m "feat: parse product bulk uploads"
```

## Task 3: Product Bulk Router Upload and Mapping

**Files:**
- Create: `api/routers/product_bulk.py`
- Modify: `api/main.py`
- Modify: `api/requirements.txt` if `openpyxl` is missing

- [ ] **Step 1: Confirm Excel dependency**

Run:

```bash
rg -n "openpyxl" api/requirements.txt
```

Expected: if no output, add:

```txt
openpyxl>=3.1.5
```

- [ ] **Step 2: Implement serializer and ownership helpers**

Create `api/routers/product_bulk.py` with:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
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
    ProductTemplateDirectionStatus,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.generation_jobs import create_job, mark_completed, mark_failed, mark_progress, mark_running, serialize_job
from ..services.media_storage import store_brand_asset
from ..services.product_bulk_parser import parse_workbook, match_zip_images

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
```

- [ ] **Step 3: Add upload/list/detail/mapping endpoints**

Append to `api/routers/product_bulk.py`:

```python
@router.post("")
async def create_product_bulk_batch(
    background_tasks: BackgroundTasks,
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
            stored = store_brand_asset(
                suite_id=suite.id,
                asset_type="product-bulk",
                filename=f"{batch.id}/{matched.filename}",
                data=matched.data,
                content_type=matched.content_type,
            )
            image_url = stored.url
        db.add(ProductBulkItem(
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
        ))

    await db.commit()
    return serialize_batch(await get_batch(db, suite.id, batch.id, current_user))


@router.get("")
async def list_product_bulk_batches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_suite(db, suite_id, current_user)
    result = await db.execute(
        select(ProductBulkBatch)
        .where(ProductBulkBatch.suite_id == suite_id)
        .order_by(ProductBulkBatch.created_at.desc())
        .options(selectinload(ProductBulkBatch.items), selectinload(ProductBulkBatch.template_directions))
    )
    return {"batches": [serialize_batch(batch) for batch in result.scalars().all()]}


@router.get("/{batch_id}")
async def get_product_bulk_batch(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    return serialize_batch(batch)
```

Note: `suite_id` is available from the router path.

- [ ] **Step 4: Include router in FastAPI**

Modify `api/main.py`:

```python
from .routers import product_bulk
```

and:

```python
app.include_router(product_bulk.router, prefix="/api/v1")
```

- [ ] **Step 5: Run import smoke test**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m compileall api/routers/product_bulk.py api/models/product_bulk.py api/services/product_bulk_parser.py
```

Expected: compiles without syntax errors.

- [ ] **Step 6: Commit upload and mapping API**

Run:

```bash
git add api/routers/product_bulk.py api/main.py api/requirements.txt
git commit -m "feat: add product bulk upload api"
```

## Task 4: Product Bulk Generation Service

**Files:**
- Create: `api/services/product_bulk_generator.py`
- Modify: `api/routers/product_bulk.py`

- [ ] **Step 1: Implement generation service**

Create `api/services/product_bulk_generator.py`:

```python
import uuid
from typing import Callable, Optional

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
from .content_generator import _generate_image
from .media_storage import store_post_media

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


def _product_prompt(suite: Suite, batch: ProductBulkBatch, item: ProductBulkItem, direction: dict) -> str:
    brand = suite.brand or {}
    prompt = (
        "Create a finished product marketing image.\n"
        "Use the attached product image as the exact product reference.\n"
        "Do not invent a different product.\n"
        "Keep the design production-ready for social media and ads.\n\n"
        f"Business: {suite.name}\n"
        f"Brand data: {brand if batch.brand_enabled else 'Brand disabled by user'}\n"
        f"Product name: {item.product_name}\n"
        f"Slogan: {item.slogan or ''}\n"
        f"Description: {item.description or ''}\n"
        f"Price: {item.price or ''}\n"
        f"Global addition for all designs: {item.global_addition or ''}\n"
        f"Notes: {item.notes or ''}\n"
        f"User creative direction: {batch.creative_prompt or ''}\n\n"
        f"Template direction: {direction.get('name')}\n"
        f"Direction description: {direction.get('description')}\n"
        f"Visual rules: {direction.get('visual_rules')}\n"
        f"Prompt rules: {direction.get('prompt_rules')}\n"
        "Output should be a single 4:5 image. If text is included, keep it readable and use the product/business language."
    )
    return prompt


async def _load_batch(db: AsyncSession, batch_id: str) -> ProductBulkBatch:
    result = await db.execute(
        select(ProductBulkBatch)
        .where(ProductBulkBatch.id == batch_id)
        .options(
            selectinload(ProductBulkBatch.items),
            selectinload(ProductBulkBatch.template_directions),
            selectinload(ProductBulkBatch.assets),
        )
    )
    batch = result.scalar_one()
    return batch


async def generate_first_product_templates(
    db: AsyncSession,
    suite_id: str,
    batch_id: str,
    progress: ProgressCallback = None,
) -> list[str]:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one()
    batch = await _load_batch(db, batch_id)
    first_item = sorted(batch.items, key=lambda item: item.row_index)[0]
    batch.status = ProductBulkBatchStatus.first_generating
    first_item.status = ProductBulkItemStatus.first_sample
    await db.commit()

    created_asset_ids: list[str] = []
    for idx, direction_data in enumerate(TEMPLATE_DIRECTIONS, start=1):
        if progress:
            progress({"status": "running", "stage": "template", "message": f"Generating template {idx}/3.", "progress": 20 + idx * 20})
        direction = ProductTemplateDirection(batch_id=batch.id, **direction_data)
        db.add(direction)
        await db.flush()
        prompt = _product_prompt(suite, batch, first_item, direction_data)
        image_bytes = _generate_image(prompt, "4:5")
        asset = ProductBulkAsset(
            batch_id=batch.id,
            item_id=first_item.id,
            template_direction_id=direction.id,
            status=ProductBulkAssetStatus.generated if image_bytes else ProductBulkAssetStatus.failed,
            media_type="image",
            prompt=prompt,
            ai_metadata={"template_direction": direction_data, "phase": "first_product"},
        )
        db.add(asset)
        await db.flush()
        if image_bytes:
            stored = store_post_media(asset.id, "product-template.png", image_bytes, "image/png")
            asset.media_url = stored.url
        direction.sample_asset_id = asset.id
        created_asset_ids.append(asset.id)

    batch.status = ProductBulkBatchStatus.awaiting_template_approval
    await db.commit()
    return created_asset_ids


async def approve_template_direction(db: AsyncSession, batch_id: str, template_id: str) -> None:
    batch = await _load_batch(db, batch_id)
    for direction in batch.template_directions:
        direction.status = (
            ProductTemplateDirectionStatus.approved
            if direction.id == template_id
            else ProductTemplateDirectionStatus.rejected
        )
    batch.approved_template_id = template_id
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
    direction = next((d for d in batch.template_directions if d.id == batch.approved_template_id), None)
    if not direction:
        raise ValueError("Approve a template direction before generating all products.")
    direction_data = {
        "name": direction.name,
        "description": direction.description,
        "visual_rules": direction.visual_rules,
        "prompt_rules": direction.prompt_rules,
    }
    batch.status = ProductBulkBatchStatus.generating_all
    await db.commit()

    items = sorted(batch.items, key=lambda item: item.row_index)
    asset_ids: list[str] = []
    for idx, item in enumerate(items, start=1):
        if progress:
            progress({"status": "running", "stage": "batch", "message": f"Generating product {idx}/{len(items)}.", "progress": 10 + int(80 * idx / max(1, len(items)))})
        item.status = ProductBulkItemStatus.generating
        prompt = _product_prompt(suite, batch, item, direction_data)
        image_bytes = _generate_image(prompt, "4:5")
        asset = ProductBulkAsset(
            batch_id=batch.id,
            item_id=item.id,
            template_direction_id=direction.id,
            status=ProductBulkAssetStatus.generated if image_bytes else ProductBulkAssetStatus.failed,
            media_type="image",
            prompt=prompt,
            ai_metadata={"template_direction": direction_data, "phase": "full_batch"},
        )
        db.add(asset)
        await db.flush()
        if image_bytes:
            stored = store_post_media(asset.id, "product.png", image_bytes, "image/png")
            asset.media_url = stored.url
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
```

- [ ] **Step 2: Add background runners and generation endpoints**

Append imports and functions to `api/routers/product_bulk.py`:

```python
import asyncio

from ..services.generation_jobs import classify_provider_limit, mark_provider_limit
from ..services.product_bulk_generator import (
    approve_template_direction,
    generate_all_products,
    generate_first_product_templates,
)


def progress_writer(job_id: str):
    def progress(event: dict):
        async def _write():
            async with AsyncSessionLocal() as progress_db:
                await mark_progress(progress_db, job_id, event)
        try:
            asyncio.create_task(_write())
        except RuntimeError:
            pass
    return progress


async def _run_generate_first(suite_id: str, batch_id: str, job_id: str):
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


async def _run_generate_all(suite_id: str, batch_id: str, job_id: str):
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
```

Add endpoints:

```python
@router.post("/{batch_id}/generate-first", status_code=202)
async def generate_first(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.product_bulk_generate_first,
        user_id=current_user.id,
        input_data={"batch_id": batch.id},
    )
    background_tasks.add_task(_run_generate_first, suite_id, batch.id, job.id)
    return serialize_job(job)


@router.post("/{batch_id}/templates/{template_id}/approve")
async def approve_template(
    batch_id: str,
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_batch(db, suite_id, batch_id, current_user)
    await approve_template_direction(db, batch_id, template_id)
    return {"ok": True, "template_id": template_id}


@router.post("/{batch_id}/generate-all", status_code=202)
async def generate_all(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, suite_id, batch_id, current_user)
    if not batch.approved_template_id:
        raise HTTPException(status_code=400, detail="Approve a template direction before generating all products.")
    job = await create_job(
        db,
        suite_id=suite_id,
        job_type=GenerationJobType.product_bulk_generate_all,
        user_id=current_user.id,
        input_data={"batch_id": batch.id, "template_id": batch.approved_template_id},
    )
    background_tasks.add_task(_run_generate_all, suite_id, batch.id, job.id)
    return serialize_job(job)
```

- [ ] **Step 3: Add asset state endpoints**

Append to `api/routers/product_bulk.py`:

```python
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
    batch_id: str,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_batch(db, suite_id, batch_id, current_user)
    asset = await get_asset(db, batch_id, asset_id)
    asset.status = ProductBulkAssetStatus.approved
    await db.commit()
    return {"ok": True, "status": "approved"}


@router.post("/{batch_id}/assets/{asset_id}/reject")
async def reject_asset(
    batch_id: str,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_batch(db, suite_id, batch_id, current_user)
    asset = await get_asset(db, batch_id, asset_id)
    asset.status = ProductBulkAssetStatus.rejected
    await db.commit()
    return {"ok": True, "status": "rejected"}
```

- [ ] **Step 4: Compile router and service**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m compileall api/routers/product_bulk.py api/services/product_bulk_generator.py
```

Expected: compiles without syntax errors.

- [ ] **Step 5: Commit generation backend**

Run:

```bash
git add api/routers/product_bulk.py api/services/product_bulk_generator.py
git commit -m "feat: generate product bulk assets"
```

## Task 5: Web API Client

**Files:**
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Add TypeScript types**

Append interfaces to `web/src/lib/api.ts` near the other exported interfaces:

```ts
export interface ProductBulkAsset {
  id: string;
  item_id: string;
  template_direction_id?: string | null;
  status: "pending" | "generating" | "generated" | "approved" | "rejected" | "failed";
  media_url?: string | null;
  media_type: string;
  feedback?: string | null;
  ai_metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProductBulkItem {
  id: string;
  row_index: number;
  product_name: string;
  image_ref?: string | null;
  image_url?: string | null;
  slogan?: string | null;
  description?: string | null;
  price?: string | null;
  global_addition?: string | null;
  notes?: string | null;
  raw_row?: Record<string, string> | null;
  status: "pending" | "first_sample" | "generating" | "generated" | "approved" | "rejected" | "failed";
  assets: ProductBulkAsset[];
}

export interface ProductTemplateDirection {
  id: string;
  name: string;
  description?: string | null;
  visual_rules?: Record<string, unknown> | null;
  prompt_rules?: Record<string, unknown> | null;
  sample_asset_id?: string | null;
  status: "candidate" | "approved" | "rejected";
}

export interface ProductBulkBatch {
  id: string;
  suite_id: string;
  name: string;
  status: "uploaded" | "mapped" | "first_generating" | "awaiting_template_approval" | "approved_template" | "generating_all" | "completed" | "failed" | "cancelled";
  source_excel_url?: string | null;
  source_zip_url?: string | null;
  creative_prompt?: string | null;
  column_mapping?: Record<string, string> | null;
  approved_template_id?: string | null;
  brand_enabled: boolean;
  total_products: number;
  completed_products: number;
  failed_products: number;
  items: ProductBulkItem[];
  template_directions: ProductTemplateDirection[];
  assets: ProductBulkAsset[];
  created_at?: string | null;
  updated_at?: string | null;
}
```

- [ ] **Step 2: Add API methods**

Inside `export const api`, add:

```ts
  productBulk: {
    list: (suiteId: string) =>
      request<{ batches: ProductBulkBatch[] }>(`/suites/${suiteId}/product-bulk`),
    get: (suiteId: string, batchId: string) =>
      request<ProductBulkBatch>(`/suites/${suiteId}/product-bulk/${batchId}`),
    create: (suiteId: string, data: { excel: File; imagesZip: File; creativePrompt?: string; brandEnabled?: boolean }) => {
      const form = new FormData();
      form.append("excel", data.excel);
      form.append("images_zip", data.imagesZip);
      form.append("creative_prompt", data.creativePrompt || "");
      form.append("brand_enabled", String(data.brandEnabled ?? true));
      return request<ProductBulkBatch>(`/suites/${suiteId}/product-bulk`, { method: "POST", body: form, headers: {} });
    },
    generateFirst: (suiteId: string, batchId: string) =>
      request<GenerationStatus>(`/suites/${suiteId}/product-bulk/${batchId}/generate-first`, { method: "POST", body: "{}" }),
    approveTemplate: (suiteId: string, batchId: string, templateId: string) =>
      request<{ ok: boolean; template_id: string }>(`/suites/${suiteId}/product-bulk/${batchId}/templates/${templateId}/approve`, { method: "POST", body: "{}" }),
    generateAll: (suiteId: string, batchId: string) =>
      request<GenerationStatus>(`/suites/${suiteId}/product-bulk/${batchId}/generate-all`, { method: "POST", body: "{}" }),
    approveAsset: (suiteId: string, batchId: string, assetId: string) =>
      request<{ ok: boolean; status: string }>(`/suites/${suiteId}/product-bulk/${batchId}/assets/${assetId}/approve`, { method: "POST", body: "{}" }),
    rejectAsset: (suiteId: string, batchId: string, assetId: string) =>
      request<{ ok: boolean; status: string }>(`/suites/${suiteId}/product-bulk/${batchId}/assets/${assetId}/reject`, { method: "POST", body: "{}" }),
  },
```

- [ ] **Step 3: Build web client**

Run:

```bash
cd web
npm run build
```

Expected: PASS.

- [ ] **Step 4: Commit API client**

Run:

```bash
git add web/src/lib/api.ts
git commit -m "feat: add product bulk web client"
```

## Task 6: Product Bulk Studio Page

**Files:**
- Create: `web/src/app/(dashboard)/suite/[id]/product-bulk/page.tsx`

- [ ] **Step 1: Create the page component**

Create `web/src/app/(dashboard)/suite/[id]/product-bulk/page.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CheckCircle2, Download, FileSpreadsheet, Images, Loader2, RefreshCw, Upload, Wand2, XCircle } from "lucide-react";
import { api, GenerationStatus, ProductBulkAsset, ProductBulkBatch, ProductTemplateDirection } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

export default function ProductBulkStudioPage() {
  const params = useParams();
  const suiteId = params.id as string;
  const [batch, setBatch] = useState<ProductBulkBatch | null>(null);
  const [excel, setExcel] = useState<File | null>(null);
  const [zip, setZip] = useState<File | null>(null);
  const [creativePrompt, setCreativePrompt] = useState("");
  const [brandEnabled, setBrandEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<GenerationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!batch) return;
    const next = await api.productBulk.get(suiteId, batch.id);
    setBatch(next);
  }

  useEffect(() => {
    if (!batch) return;
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, 3500);
    return () => clearInterval(timer);
  }, [batch?.id]);

  const firstItem = useMemo(() => batch?.items?.[0], [batch]);
  const approvedTemplate = batch?.template_directions.find((template) => template.status === "approved");

  async function uploadBatch() {
    if (!excel || !zip) {
      setError("Upload Excel and ZIP files first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const created = await api.productBulk.create(suiteId, { excel, imagesZip: zip, creativePrompt, brandEnabled });
      setBatch(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function generateFirst() {
    if (!batch) return;
    setLoading(true);
    setError(null);
    try {
      const status = await api.productBulk.generateFirst(suiteId, batch.id);
      setJob(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  }

  async function approveTemplate(templateId: string) {
    if (!batch) return;
    await api.productBulk.approveTemplate(suiteId, batch.id, templateId);
    await refresh();
  }

  async function generateAll() {
    if (!batch) return;
    setLoading(true);
    setError(null);
    try {
      const status = await api.productBulk.generateAll(suiteId, batch.id);
      setJob(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch generation failed");
    } finally {
      setLoading(false);
    }
  }

  async function setAssetStatus(asset: ProductBulkAsset, action: "approve" | "reject") {
    if (!batch) return;
    if (action === "approve") {
      await api.productBulk.approveAsset(suiteId, batch.id, asset.id);
    } else {
      await api.productBulk.rejectAsset(suiteId, batch.id, asset.id);
    }
    await refresh();
  }

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <Link href={`/suite/${suiteId}`} className="mb-3 inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white">
            <ArrowLeft size={16} /> Back to suite
          </Link>
          <h1 className="text-2xl font-semibold text-white">Product Bulk Studio</h1>
          <p className="mt-1 text-sm text-zinc-500">Upload products, approve one design direction, then generate the full catalog.</p>
        </div>
        {batch && <Badge className="bg-zinc-800 text-zinc-200">{batch.status.replaceAll("_", " ")}</Badge>}
      </div>

      {error && <div className="rounded-lg border border-red-900/70 bg-red-950/40 p-3 text-sm text-red-200">{error}</div>}
      {job && <div className="rounded-lg border border-indigo-900/70 bg-indigo-950/30 p-3 text-sm text-indigo-100">{job.message || job.status}</div>}

      {!batch && (
        <Card className="border-zinc-800 bg-zinc-950">
          <CardHeader><CardTitle className="text-white">Upload product batch</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <div>
              <Label className="text-zinc-300">Excel file</Label>
              <Input type="file" accept=".xlsx" onChange={(event) => setExcel(event.target.files?.[0] || null)} className="mt-2" />
            </div>
            <div>
              <Label className="text-zinc-300">Product images ZIP</Label>
              <Input type="file" accept=".zip" onChange={(event) => setZip(event.target.files?.[0] || null)} className="mt-2" />
            </div>
            <div className="md:col-span-2">
              <Label className="text-zinc-300">Extra creative prompt</Label>
              <textarea value={creativePrompt} onChange={(event) => setCreativePrompt(event.target.value)} className="mt-2 min-h-24 w-full rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-sm text-white" />
            </div>
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input type="checkbox" checked={brandEnabled} onChange={(event) => setBrandEnabled(event.target.checked)} />
              Use business profile and brand
            </label>
            <div className="md:col-span-2">
              <Button disabled={loading} onClick={uploadBatch} className="bg-indigo-600 hover:bg-indigo-500">
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />} Upload and preview
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {batch && (
        <>
          <Card className="border-zinc-800 bg-zinc-950">
            <CardHeader><CardTitle className="text-white">Import preview</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <Stat icon={<FileSpreadsheet size={18} />} label="Products" value={batch.total_products} />
                <Stat icon={<Images size={18} />} label="Matched images" value={batch.items.filter((item) => item.image_url).length} />
                <Stat icon={<CheckCircle2 size={18} />} label="Approved assets" value={batch.assets.filter((asset) => asset.status === "approved").length} />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-zinc-500"><tr><th className="py-2">Product</th><th>Image</th><th>Price</th><th>Status</th></tr></thead>
                  <tbody className="divide-y divide-zinc-900">
                    {batch.items.slice(0, 12).map((item) => (
                      <tr key={item.id} className="text-zinc-300">
                        <td className="py-2">{item.product_name}</td>
                        <td>{item.image_url ? "matched" : "missing"}</td>
                        <td>{item.price || "-"}</td>
                        <td>{item.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Button disabled={loading || batch.template_directions.length > 0} onClick={generateFirst} className="bg-indigo-600 hover:bg-indigo-500">
                <Wand2 className="mr-2 h-4 w-4" /> Generate first product templates
              </Button>
            </CardContent>
          </Card>

          {batch.template_directions.length > 0 && (
            <Card className="border-zinc-800 bg-zinc-950">
              <CardHeader><CardTitle className="text-white">Choose template direction</CardTitle></CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-3">
                {batch.template_directions.map((template) => (
                  <TemplateCard key={template.id} template={template} batch={batch} onApprove={() => approveTemplate(template.id)} />
                ))}
              </CardContent>
            </Card>
          )}

          {approvedTemplate && (
            <Card className="border-zinc-800 bg-zinc-950">
              <CardHeader><CardTitle className="text-white">Generate all products</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-zinc-400">Approved direction: {approvedTemplate.name}</p>
                <Button disabled={loading || batch.status === "generating_all"} onClick={generateAll} className="bg-emerald-600 hover:bg-emerald-500">
                  {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wand2 className="mr-2 h-4 w-4" />} Generate all
                </Button>
              </CardContent>
            </Card>
          )}

          {batch.assets.length > 0 && (
            <div className="grid gap-4 md:grid-cols-3">
              {batch.assets.map((asset) => (
                <AssetCard key={asset.id} asset={asset} onApprove={() => setAssetStatus(asset, "approve")} onReject={() => setAssetStatus(asset, "reject")} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-zinc-100"><div className="text-zinc-500">{icon}</div><div className="mt-2 text-2xl font-semibold">{value}</div><div className="text-xs text-zinc-500">{label}</div></div>;
}

function TemplateCard({ template, batch, onApprove }: { template: ProductTemplateDirection; batch: ProductBulkBatch; onApprove: () => void }) {
  const asset = batch.assets.find((candidate) => candidate.id === template.sample_asset_id);
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="aspect-[4/5] overflow-hidden rounded-md bg-zinc-950">
        {asset?.media_url ? <img src={asset.media_url} alt={template.name} className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-zinc-600">No preview</div>}
      </div>
      <h3 className="mt-3 text-sm font-semibold text-white">{template.name}</h3>
      <p className="mt-1 min-h-10 text-xs text-zinc-500">{template.description}</p>
      <Button disabled={template.status === "approved"} onClick={onApprove} className="mt-3 w-full bg-indigo-600 hover:bg-indigo-500">
        {template.status === "approved" ? "Approved" : "Approve direction"}
      </Button>
    </div>
  );
}

function AssetCard({ asset, onApprove, onReject }: { asset: ProductBulkAsset; onApprove: () => void; onReject: () => void }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <div className="aspect-[4/5] overflow-hidden rounded-md bg-zinc-900">
        {asset.media_url ? <img src={asset.media_url} alt="Generated product" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-zinc-600">No media</div>}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-zinc-500">
        <span>{asset.status}</span>
        {asset.media_url && <a href={asset.media_url} download target="_blank" className="inline-flex items-center gap-1 text-indigo-300"><Download size={14} /> Download</a>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button size="sm" onClick={onReject} variant="outline"><XCircle className="mr-1 h-4 w-4" /> Reject</Button>
        <Button size="sm" onClick={onApprove} className="bg-emerald-600 hover:bg-emerald-500"><CheckCircle2 className="mr-1 h-4 w-4" /> Approve</Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build web**

Run:

```bash
cd web
npm run build
```

Expected: PASS. If TypeScript complains about `React.ReactNode`, import `type { ReactNode } from "react"` and use `ReactNode`.

- [ ] **Step 3: Commit studio page**

Run:

```bash
git add web/src/app/\(dashboard\)/suite/\[id\]/product-bulk/page.tsx
git commit -m "feat: add product bulk studio page"
```

## Task 7: Dashboard Entry Point

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`

- [ ] **Step 1: Add Product Bulk Studio action**

In `CreateCommandCenter`, add a visible action card or button that links to:

```tsx
<Link
  href={`/suite/${suiteId}/product-bulk`}
  className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-100 hover:border-indigo-500"
>
  <span className="block font-medium">Product bulk studio</span>
  <span className="mt-1 block text-xs text-zinc-500">Upload Excel + ZIP, approve one template, generate the full catalog.</span>
</Link>
```

If `CreateCommandCenter` does not currently import `Link`, add:

```tsx
import Link from "next/link";
```

Do not replace the current create options. Add this as a new option under Create & generate.

- [ ] **Step 2: Build web**

Run:

```bash
cd web
npm run build
```

Expected: PASS.

- [ ] **Step 3: Commit dashboard entry**

Run:

```bash
git add web/src/app/\(dashboard\)/suite/\[id\]/page.tsx
git commit -m "feat: link product bulk studio from dashboard"
```

## Task 8: Verification and Ship

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest tests/test_product_bulk_models.py tests/test_product_bulk_parser.py tests/test_generation_jobs.py -v
```

Expected: PASS.

- [ ] **Step 2: Run web build**

Run:

```bash
cd web
npm run build
```

Expected: PASS.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short
```

Expected: only unrelated pre-existing files may remain:

```txt
 M api/**/__pycache__/*.pyc
 M docs/Prompts/may2026
?? api/static/
?? docs/railway-env-vars.md
?? docs/railway-env-vars.pdf
```

- [ ] **Step 4: Push root repo**

Run:

```bash
git push
```

Expected: push succeeds.

- [ ] **Step 5: Push nested web repo if it has separate git history**

Run:

```bash
cd web
git status --short
git push
```

Expected: push succeeds if `web` is a nested repo. If `web` is not a git repo in the active workspace, skip this step.

## Self-Review

- Spec coverage: The plan covers dedicated batch entities, Excel + ZIP upload, Hebrew mapping, first product three-template approval, full-batch generation, individual asset review, durable jobs, and a dedicated UI page.
- Placeholder scan: The plan avoids TBD/TODO placeholders and includes concrete code/commands for each implementation task.
- Type consistency: Backend model names, endpoint paths, and TypeScript types use the same ProductBulk naming and status values throughout.
