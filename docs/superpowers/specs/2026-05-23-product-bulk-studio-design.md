# Product Bulk Studio Design

Date: 2026-05-23

## Goal

Add a product bulk generation workflow for suites. A user uploads an Excel file with products and a ZIP file with the original product images. Co-Suite imports the products, generates three template directions for the first product, waits for approval or edits, then applies the approved direction to the rest of the catalog. Every generated product asset remains individually reviewable.

This feature is a separate batch studio, not a direct dump into the normal pending content feed.

## First Version Scope

The first version supports:

- Uploading one Excel file and one ZIP file per batch.
- Flexible column mapping with automatic detection for common Hebrew product sheets.
- A user prompt field for extra creative direction.
- Previewing imported products before generation.
- Generating three template directions for the first product only.
- Approving one template direction before generating the rest of the batch.
- Generating remaining products with the approved template direction.
- Per-product review states: pending, approved, rejected, regenerating, failed.
- Per-product actions: approve, reject, regenerate with feedback, download.

The first version does not need full scheduling or campaign publishing. It should keep an integration path so approved product assets can later be sent to the content system, exported as a ZIP, or used in ad campaigns.

## User Flow

1. The user opens a new `Product Bulk Studio` page inside a suite.
2. The user uploads:
   - Excel file.
   - ZIP file containing original product images.
   - Optional creative prompt.
3. The app parses the Excel and ZIP.
4. The app shows a mapping screen.
5. The app auto-detects Hebrew columns when possible:
   - `שם` -> product name.
   - `תמונה` -> image file reference.
   - `סלוגן` -> slogan.
   - `תיאור המוצר` -> product description.
   - `מחיר לסט שלם + מע"מ` -> price.
   - `תוספת בכל העיצובים` -> global design addition.
   - `הערות` -> notes.
6. The user confirms or adjusts mapping.
7. The app shows an import preview with product count, missing images, and first product details.
8. The user clicks `Generate first product`.
9. The backend generates three template directions for the first product.
10. The user approves one direction or asks for a regeneration with feedback.
11. After approval, the user clicks `Generate all`.
12. The backend creates jobs for the rest of the products.
13. The user reviews each generated product asset independently.

## UX Shape

The page should be a focused studio, not part of the crowded dashboard feed.

Primary sections:

- `Upload`: Excel, ZIP, extra prompt, brand toggle.
- `Map columns`: source columns on the left, target fields on the right.
- `Preview`: product table with image match status.
- `Template approval`: first product with three generated template cards.
- `Batch generation`: progress and product result grid.
- `Review`: each generated product result with approve, reject, regenerate, download.

Important UX rules:

- The user should not be allowed to generate all products before approving a template direction.
- Missing images should be visible before generation starts.
- Regeneration must accept free-text feedback and attach it to the product result.
- The chosen template direction should be named and saved so the user understands what will be applied to the rest of the batch.
- The app should show queue/waiting states clearly because AI and image APIs can hit provider limits.

## Data Model

Add dedicated batch entities instead of overloading `content_posts`.

### ProductBulkBatch

Fields:

- `id`
- `suite_id`
- `name`
- `status`: uploaded, mapped, first_generating, awaiting_template_approval, approved_template, generating_all, completed, failed, cancelled
- `source_excel_url`
- `source_zip_url`
- `creative_prompt`
- `column_mapping`
- `approved_template_id`
- `brand_enabled`
- `total_products`
- `completed_products`
- `failed_products`
- `created_at`
- `updated_at`

### ProductBulkItem

Fields:

- `id`
- `batch_id`
- `row_index`
- `product_name`
- `image_ref`
- `image_url`
- `slogan`
- `description`
- `price`
- `global_addition`
- `notes`
- `raw_row`
- `status`: pending, first_sample, generating, generated, approved, rejected, failed
- `created_at`
- `updated_at`

### ProductBulkAsset

Fields:

- `id`
- `batch_id`
- `item_id`
- `template_direction_id`
- `status`: pending, generating, generated, approved, rejected, failed
- `media_url`
- `media_type`
- `prompt`
- `feedback`
- `ai_metadata`
- `created_at`
- `updated_at`

### ProductTemplateDirection

Fields:

- `id`
- `batch_id`
- `name`
- `description`
- `visual_rules`
- `prompt_rules`
- `sample_asset_id`
- `status`: candidate, approved, rejected
- `created_at`
- `updated_at`

## Backend API

Add a new router, likely `api/routers/product_bulk.py`.

Endpoints:

- `POST /api/v1/suites/{suite_id}/product-bulk`
  - Upload Excel, ZIP, creative prompt, brand toggle.
  - Store files using existing media storage.
  - Create batch and parse products.

- `GET /api/v1/suites/{suite_id}/product-bulk`
  - List batches for the suite.

- `GET /api/v1/suites/{suite_id}/product-bulk/{batch_id}`
  - Return batch, items, template directions, assets, and progress.

- `PATCH /api/v1/suites/{suite_id}/product-bulk/{batch_id}/mapping`
  - Save mapping and re-parse rows.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/generate-first`
  - Queue generation for first product and three template directions.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/templates/{template_id}/approve`
  - Approve selected template direction.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/generate-all`
  - Queue generation for remaining products.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/assets/{asset_id}/approve`
  - Approve one generated product asset.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/assets/{asset_id}/reject`
  - Reject one generated product asset.

- `POST /api/v1/suites/{suite_id}/product-bulk/{batch_id}/assets/{asset_id}/regenerate`
  - Regenerate one asset with free-text feedback.

## Generation Rules

The generation prompt should include:

- Business profile and brand data when `brand_enabled` is true.
- Product data from the mapped row.
- Original product image as a reference.
- User creative prompt.
- Approved template direction rules when generating the full batch.
- Platform-safe design requirements.

The first product generation creates three different directions:

1. Sales-forward product ad.
2. Clean catalog/product showcase.
3. Brand-led premium/social design.

The advanced prompt can override or influence these directions, but the system should keep the result usable as a product marketing asset.

For the full batch, the approved template direction should drive consistency. Each product should still use its own product name, image, price, slogan, description, and notes.

## File Parsing

Excel:

- Support `.xlsx` first.
- Read first worksheet by default.
- Keep raw row data.
- Detect header row from the first non-empty row.

ZIP:

- Extract in memory or temporary storage.
- Store matched images via existing media storage.
- Match `תמונה` values to ZIP filenames.
- Normalize filename matching by trimming whitespace and ignoring simple path prefixes.
- Show unmatched products before generation.

## Job Handling

Use the existing durable generation job pattern rather than synchronous long requests.

Needed job types:

- `product_bulk_import`
- `product_bulk_generate_first`
- `product_bulk_generate_all`
- `product_bulk_regenerate_asset`

The UI should poll batch status and job status. Provider limit states should be visible as waiting, not as silent failure.

## Error Handling

Handle:

- Invalid Excel file.
- Missing image ZIP.
- No matching image for a product row.
- Empty required product name.
- AI provider timeout or rate limit.
- R2/media upload failure.
- Partial batch failures.

Partial failure should not fail the whole batch. Failed items should remain visible and individually regeneratable.

## Future Extensions

Future versions can add:

- Export approved assets as ZIP.
- Send approved assets to normal content posts.
- Create Meta or Google ad drafts from approved assets.
- Support multiple output aspect ratios per product.
- Support CSV.
- Support saved reusable template presets per suite.
- Support user-uploaded background/style references.

## Acceptance Criteria

- A user can upload an Excel sheet with Hebrew headers and a ZIP of product images.
- The app auto-maps the provided Hebrew columns or lets the user correct mapping.
- The app detects image matches from the ZIP.
- The app generates three templates for the first product.
- The user can approve one template direction.
- The app generates assets for the rest of the products using the approved direction.
- Each generated product asset can be approved, rejected, regenerated with feedback, and downloaded.
- Batch generation survives page refresh and shows durable progress.
