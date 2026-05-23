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
    assert GenerationJobType.product_bulk_import.value == "product_bulk_import"
    assert GenerationJobType.product_bulk_generate_first.value == "product_bulk_generate_first"
    assert GenerationJobType.product_bulk_generate_all.value == "product_bulk_generate_all"
    assert GenerationJobType.product_bulk_regenerate_asset.value == "product_bulk_regenerate_asset"
