import pytest
from fastapi import BackgroundTasks, HTTPException

from api.models.product_bulk import (
    ProductBulkAsset,
    ProductBulkAssetStatus,
    ProductBulkBatch,
    ProductBulkBatchStatus,
    ProductBulkItem,
    ProductBulkItemStatus,
    ProductTemplateDirection,
    ProductTemplateDirectionStatus,
)
from api.models.suite import Suite
from api.models.user import User
from api.routers import product_bulk


def make_user() -> User:
    return User(id="user-1", email="owner@example.com", hashed_password="x")


def make_suite() -> Suite:
    return Suite(id="suite-1", owner_id="user-1", name="Connec", slug="connec")


def make_batch(items: list[ProductBulkItem] | None = None) -> ProductBulkBatch:
    batch = ProductBulkBatch(
        id="batch-1",
        suite_id="suite-1",
        created_by="user-1",
        name="Connec product bulk",
        status=ProductBulkBatchStatus.mapped,
        total_products=len(items or []),
    )
    batch.items = items or []
    batch.assets = []
    batch.template_directions = []
    for item in batch.items:
        item.batch_id = batch.id
        item.batch = batch
    return batch


def make_item(item_id: str = "item-1") -> ProductBulkItem:
    return ProductBulkItem(
        id=item_id,
        batch_id="batch-1",
        row_index=2,
        product_name="Product",
        image_ref="product.png",
        image_url="/static/product.png",
        status=ProductBulkItemStatus.generated,
    )


def make_direction(direction_id: str = "direction-1") -> ProductTemplateDirection:
    return ProductTemplateDirection(
        id=direction_id,
        batch_id="batch-1",
        name="Sales-forward product ad",
        description="A clear sales direction.",
        visual_rules={},
        prompt_rules={},
        status=ProductTemplateDirectionStatus.candidate,
    )


def make_asset(asset_id: str = "asset-1", item_id: str = "item-1", direction_id: str | None = "direction-1"):
    return ProductBulkAsset(
        id=asset_id,
        batch_id="batch-1",
        item_id=item_id,
        template_direction_id=direction_id,
        status=ProductBulkAssetStatus.generated,
        media_type="image",
        media_url="https://cdn.example/product.png",
    )


def patch_batch(monkeypatch, batch: ProductBulkBatch) -> None:
    async def fake_get_batch(_db, _suite_id, _batch_id, _user):
        return batch

    monkeypatch.setattr(product_bulk, "get_batch", fake_get_batch)


def patch_asset(monkeypatch, asset: ProductBulkAsset) -> None:
    async def fake_get_asset(_db, _batch_id, _asset_id):
        return asset

    monkeypatch.setattr(product_bulk, "get_asset", fake_get_asset)


class FakeUpload:
    def __init__(self, data: bytes, filename: str = "upload.bin"):
        self.data = data
        self.filename = filename

    async def read(self):
        return self.data


class FakeDb:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


def patch_owned_suite(monkeypatch, suite: Suite | None = None) -> None:
    async def fake_get_owned_suite(_db, _suite_id, _user):
        return suite or make_suite()

    monkeypatch.setattr(product_bulk, "get_owned_suite", fake_get_owned_suite)


@pytest.mark.asyncio
async def test_generate_first_route_rejects_empty_batch(monkeypatch):
    batch = make_batch([])
    patch_batch(monkeypatch, batch)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.generate_first("suite-1", batch.id, BackgroundTasks(), make_user(), object())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Product bulk batch has no products."


@pytest.mark.asyncio
async def test_generate_all_route_requires_approved_template(monkeypatch):
    item = make_item()
    batch = make_batch([item])
    batch.template_directions.append(make_direction())
    patch_batch(monkeypatch, batch)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.generate_all("suite-1", batch.id, BackgroundTasks(), make_user(), object())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Approve a template direction before generating all products."


@pytest.mark.asyncio
async def test_generate_all_route_rejects_missing_approved_template_direction(monkeypatch):
    item = make_item()
    batch = make_batch([item])
    batch.approved_template_id = "missing-direction"
    batch.template_directions.append(make_direction())
    patch_batch(monkeypatch, batch)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.generate_all("suite-1", batch.id, BackgroundTasks(), make_user(), object())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Approved template direction is no longer available."


@pytest.mark.asyncio
async def test_approve_template_route_rejects_template_from_another_batch(monkeypatch):
    batch = make_batch([make_item()])
    batch.template_directions.append(make_direction())
    patch_batch(monkeypatch, batch)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.approve_template("suite-1", batch.id, "other-direction", make_user(), object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "Product template direction not found"


@pytest.mark.asyncio
async def test_regenerate_asset_route_rejects_asset_without_batch_item(monkeypatch):
    batch = make_batch([make_item("item-1")])
    batch.template_directions.append(make_direction())
    patch_batch(monkeypatch, batch)
    patch_asset(monkeypatch, make_asset(item_id="missing-item"))

    with pytest.raises(HTTPException) as exc:
        await product_bulk.regenerate_asset(
            "suite-1",
            batch.id,
            "asset-1",
            product_bulk.RegenerateAssetRequest(feedback="try again"),
            BackgroundTasks(),
            make_user(),
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Product bulk item not found"


@pytest.mark.asyncio
async def test_regenerate_asset_route_rejects_missing_template_direction(monkeypatch):
    batch = make_batch([make_item("item-1")])
    batch.template_directions.append(make_direction("direction-1"))
    patch_batch(monkeypatch, batch)
    patch_asset(monkeypatch, make_asset(direction_id="missing-direction"))

    with pytest.raises(HTTPException) as exc:
        await product_bulk.regenerate_asset(
            "suite-1",
            batch.id,
            "asset-1",
            product_bulk.RegenerateAssetRequest(feedback="try again"),
            BackgroundTasks(),
            make_user(),
            object(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Product template direction is no longer available."


@pytest.mark.asyncio
async def test_create_product_bulk_batch_rejects_excel_over_configured_limit(monkeypatch):
    patch_owned_suite(monkeypatch)
    monkeypatch.setattr(product_bulk, "MAX_EXCEL_BYTES", 3)
    monkeypatch.setattr(product_bulk, "MAX_EXCEL_MB", 0)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.create_product_bulk_batch(
            "suite-1",
            excel=FakeUpload(b"xxxx", "products.xlsx"),
            images_zip=FakeUpload(b"PK", "images.zip"),
            creative_prompt="",
            brand_enabled=True,
            current_user=make_user(),
            db=FakeDb(),
        )

    assert exc.value.status_code == 413
    assert exc.value.detail == "Excel file is too large. Maximum is 0 MB."


@pytest.mark.asyncio
async def test_create_product_bulk_batch_rejects_zip_over_configured_limit(monkeypatch):
    patch_owned_suite(monkeypatch)
    monkeypatch.setattr(product_bulk, "MAX_ZIP_BYTES", 3)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.create_product_bulk_batch(
            "suite-1",
            excel=FakeUpload(b"xlsx", "products.xlsx"),
            images_zip=FakeUpload(b"xxxx", "images.zip"),
            creative_prompt="",
            brand_enabled=True,
            current_user=make_user(),
            db=FakeDb(),
        )

    assert exc.value.status_code == 413
    assert exc.value.detail == "Image ZIP file is too large. Maximum is 250 MB."


@pytest.mark.asyncio
async def test_create_product_bulk_batch_reports_invalid_workbook(monkeypatch):
    patch_owned_suite(monkeypatch)

    def fake_parse_workbook(_excel_bytes):
        raise ValueError("missing product columns")

    monkeypatch.setattr(product_bulk, "parse_workbook", fake_parse_workbook)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.create_product_bulk_batch(
            "suite-1",
            excel=FakeUpload(b"xlsx", "products.xlsx"),
            images_zip=FakeUpload(b"PK", "images.zip"),
            creative_prompt="",
            brand_enabled=True,
            current_user=make_user(),
            db=FakeDb(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid Excel file: missing product columns"


@pytest.mark.asyncio
async def test_generation_status_route_checks_batch_scope_before_loading_job(monkeypatch):
    calls = {"job": 0}

    async def fake_get_batch(_db, _suite_id, _batch_id, _user):
        raise HTTPException(status_code=404, detail="Product bulk batch not found")

    async def fake_get_latest_job_for_input(*_args, **_kwargs):
        calls["job"] += 1

    monkeypatch.setattr(product_bulk, "get_batch", fake_get_batch)
    monkeypatch.setattr(product_bulk, "get_latest_job_for_input", fake_get_latest_job_for_input)

    with pytest.raises(HTTPException) as exc:
        await product_bulk.get_product_bulk_generation_status("suite-1", "batch-1", make_user(), object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "Product bulk batch not found"
    assert calls["job"] == 0
