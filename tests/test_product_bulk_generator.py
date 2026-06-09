import pytest

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
from api.services import product_bulk_generator


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeAsyncSession:
    def __init__(self, suite: Suite, batch: ProductBulkBatch):
        self.suite = suite
        self.batch = batch
        self.added = []
        self.commit_count = 0
        self.flush_count = 0
        self._ids = 0

    async def execute(self, _statement):
        return _ScalarResult(self.suite)

    def add(self, obj):
        self._ids += 1
        if not getattr(obj, "id", None):
            obj.id = f"test-{self._ids}"

        if isinstance(obj, ProductTemplateDirection):
            if obj.status is None:
                obj.status = ProductTemplateDirectionStatus.candidate
            obj.batch = self.batch
            if obj not in self.batch.template_directions:
                self.batch.template_directions.append(obj)

        if isinstance(obj, ProductBulkAsset):
            obj.batch = self.batch
            if obj not in self.batch.assets:
                self.batch.assets.append(obj)
            item = next(item for item in self.batch.items if item.id == obj.item_id)
            obj.item = item
            if obj not in item.assets:
                item.assets.append(obj)

        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1


def make_suite() -> Suite:
    return Suite(id="suite-1", owner_id="user-1", name="Connec", slug="connec", brand={"tone": "clean"})


def make_batch(items: list[ProductBulkItem]) -> ProductBulkBatch:
    batch = ProductBulkBatch(
        id="batch-1",
        suite_id="suite-1",
        created_by="user-1",
        name="Connec product bulk",
        status=ProductBulkBatchStatus.mapped,
        creative_prompt="Keep the product visible and price clear.",
        total_products=len(items),
        brand_enabled=True,
    )
    batch.items = items
    batch.assets = []
    batch.template_directions = []
    for item in items:
        item.batch_id = batch.id
        item.batch = batch
        item.assets = []
    return batch


def make_item(row_index: int = 2, image_url: str | None = "/static/product.png") -> ProductBulkItem:
    return ProductBulkItem(
        id=f"item-{row_index}",
        batch_id="batch-1",
        row_index=row_index,
        product_name=f"Product {row_index}",
        image_ref=f"product-{row_index}.png",
        image_url=image_url,
        slogan="Clean office",
        description="A sturdy office product.",
        price="1290",
        status=ProductBulkItemStatus.pending,
    )


def add_direction(
    batch: ProductBulkBatch,
    direction_id: str = "direction-1",
    status: ProductTemplateDirectionStatus = ProductTemplateDirectionStatus.candidate,
) -> ProductTemplateDirection:
    direction_data = product_bulk_generator.TEMPLATE_DIRECTIONS[0]
    direction = ProductTemplateDirection(
        id=direction_id,
        batch_id=batch.id,
        status=status,
        **direction_data,
    )
    direction.batch = batch
    batch.template_directions.append(direction)
    return direction


def approve_direction(batch: ProductBulkBatch, direction: ProductTemplateDirection) -> None:
    direction.status = ProductTemplateDirectionStatus.approved
    batch.approved_template_id = direction.id
    batch.status = ProductBulkBatchStatus.approved_template


def patch_load_batch(monkeypatch, batch: ProductBulkBatch) -> None:
    async def fake_load_batch(_db, _batch_id):
        return batch

    monkeypatch.setattr(product_bulk_generator, "_load_batch", fake_load_batch)


@pytest.mark.asyncio
async def test_generate_first_templates_rejects_empty_batch(monkeypatch):
    batch = make_batch([])
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    with pytest.raises(ValueError, match="no products"):
        await product_bulk_generator.generate_first_product_templates(db, "suite-1", batch.id)

    assert batch.status == ProductBulkBatchStatus.mapped
    assert batch.template_directions == []
    assert batch.assets == []
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_generate_first_templates_marks_missing_first_image_failed(monkeypatch):
    item = make_item(image_url=None)
    batch = make_batch([item])
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    with pytest.raises(ValueError, match="no stored product image"):
        await product_bulk_generator.generate_first_product_templates(db, "suite-1", batch.id)

    assert batch.status == ProductBulkBatchStatus.failed
    assert item.status == ProductBulkItemStatus.failed
    assert batch.template_directions == []
    assert batch.assets == []
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_generate_first_templates_creates_three_candidates_without_provider_calls(monkeypatch):
    item = make_item()
    batch = make_batch([item])
    db = FakeAsyncSession(make_suite(), batch)
    progress_events = []

    async def fake_generate_asset_image(_db, asset, _item, _prompt, _filename):
        asset.status = ProductBulkAssetStatus.generated
        asset.media_url = f"https://cdn.example/{asset.id}.png"
        return True

    patch_load_batch(monkeypatch, batch)
    monkeypatch.setattr(product_bulk_generator, "_generate_asset_image", fake_generate_asset_image)

    asset_ids = await product_bulk_generator.generate_first_product_templates(
        db,
        "suite-1",
        batch.id,
        progress=progress_events.append,
    )

    assert batch.status == ProductBulkBatchStatus.awaiting_template_approval
    assert item.status == ProductBulkItemStatus.first_sample
    assert len(asset_ids) == 3
    assert len(batch.template_directions) == 3
    assert len(batch.assets) == 3
    assert {direction.status for direction in batch.template_directions} == {ProductTemplateDirectionStatus.candidate}
    assert all(direction.sample_asset_id for direction in batch.template_directions)
    assert all(asset.status == ProductBulkAssetStatus.generated for asset in batch.assets)
    assert all(asset.media_url and asset.media_url.startswith("https://cdn.example/") for asset in batch.assets)
    assert all(asset.ai_metadata["phase"] == "first_product" for asset in batch.assets)
    assert [event["stage"] for event in progress_events] == ["template", "template", "template"]


@pytest.mark.asyncio
async def test_generate_all_requires_approved_template(monkeypatch):
    item = make_item()
    batch = make_batch([item])
    add_direction(batch)
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    with pytest.raises(ValueError, match="Approve a template"):
        await product_bulk_generator.generate_all_products(db, "suite-1", batch.id)

    assert batch.status == ProductBulkBatchStatus.mapped
    assert item.status == ProductBulkItemStatus.pending
    assert batch.assets == []


@pytest.mark.asyncio
async def test_generate_all_marks_batch_failed_when_all_images_are_missing(monkeypatch):
    item_a = make_item(row_index=2, image_url=None)
    item_b = make_item(row_index=3, image_url=None)
    batch = make_batch([item_a, item_b])
    direction = add_direction(batch)
    approve_direction(batch, direction)
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    with pytest.raises(ValueError, match="No products have stored product images"):
        await product_bulk_generator.generate_all_products(db, "suite-1", batch.id)

    assert batch.status == ProductBulkBatchStatus.failed
    assert batch.completed_products == 0
    assert batch.failed_products == 2
    assert [item.status for item in batch.items] == [ProductBulkItemStatus.failed, ProductBulkItemStatus.failed]
    assert batch.assets == []


@pytest.mark.asyncio
async def test_generate_all_tracks_generated_and_failed_products(monkeypatch):
    item_a = make_item(row_index=2)
    item_b = make_item(row_index=3)
    batch = make_batch([item_a, item_b])
    direction = add_direction(batch)
    approve_direction(batch, direction)
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    async def fake_generate_asset_image(_db, asset, item, _prompt, _filename):
        if item.id == item_a.id:
            asset.status = ProductBulkAssetStatus.generated
            asset.media_url = f"https://cdn.example/{asset.id}.png"
            return True
        asset.status = ProductBulkAssetStatus.failed
        asset.feedback = "provider failed"
        return False

    monkeypatch.setattr(product_bulk_generator, "_generate_asset_image", fake_generate_asset_image)

    asset_ids = await product_bulk_generator.generate_all_products(db, "suite-1", batch.id)

    assert batch.status == ProductBulkBatchStatus.completed
    assert batch.completed_products == 1
    assert batch.failed_products == 1
    assert item_a.status == ProductBulkItemStatus.generated
    assert item_b.status == ProductBulkItemStatus.failed
    assert len(asset_ids) == 2
    assert len(batch.assets) == 2
    assert [asset.ai_metadata["phase"] for asset in batch.assets] == ["full_batch", "full_batch"]


@pytest.mark.asyncio
async def test_regenerate_product_asset_preserves_original_and_records_feedback(monkeypatch):
    item = make_item()
    batch = make_batch([item])
    direction = add_direction(batch)
    approve_direction(batch, direction)
    original_asset = ProductBulkAsset(
        id="asset-original",
        batch_id=batch.id,
        item_id=item.id,
        template_direction_id=direction.id,
        status=ProductBulkAssetStatus.generated,
        media_type="image",
        media_url="https://cdn.example/original.png",
        ai_metadata={"phase": "full_batch"},
    )
    original_asset.batch = batch
    original_asset.item = item
    batch.assets.append(original_asset)
    item.assets.append(original_asset)
    db = FakeAsyncSession(make_suite(), batch)
    patch_load_batch(monkeypatch, batch)

    async def fake_generate_asset_image(_db, asset, _item, _prompt, _filename):
        asset.status = ProductBulkAssetStatus.generated
        asset.media_url = f"https://cdn.example/{asset.id}.png"
        return True

    monkeypatch.setattr(product_bulk_generator, "_generate_asset_image", fake_generate_asset_image)

    new_asset_id = await product_bulk_generator.regenerate_product_asset(
        db,
        "suite-1",
        batch.id,
        original_asset.id,
        feedback="Make the price larger.",
    )

    assert original_asset.status == ProductBulkAssetStatus.generated
    assert original_asset.media_url == "https://cdn.example/original.png"
    assert item.status == ProductBulkItemStatus.generated
    assert new_asset_id != original_asset.id
    new_asset = next(asset for asset in batch.assets if asset.id == new_asset_id)
    assert new_asset.status == ProductBulkAssetStatus.generated
    assert new_asset.ai_metadata["phase"] == "regenerate_asset"
    assert new_asset.ai_metadata["regenerated_from_asset_id"] == original_asset.id
    assert new_asset.ai_metadata["feedback"] == "Make the price larger."
    assert "Regeneration feedback: Make the price larger." in new_asset.prompt
