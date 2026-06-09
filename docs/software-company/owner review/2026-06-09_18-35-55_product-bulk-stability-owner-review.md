# Product Bulk Stability Owner Review

Date: 2026-06-09 18:35
Project: OneShare / co-Suite
Prepared by: Layla Haddad, Project Management

## الخلاصة

رجعنا من موضوع Google Ads إلى مسار المشروع الأساسي، واشتغلنا على تثبيت Product Bulk Studio من جهة الباكند والـ route guards.

التركيز كان على منع الحالات اللي كانت تضرب تجربة المستخدم: batch بدون منتجات، منتج أول بدون صورة، توليد كل المنتجات بدون template approved، صور ناقصة، وإعادة توليد أصلها يضيع أو feedback ما ينحفظ.

## ما تم إنجازه

- أضفنا اختبارات service-level لمسار أول 3 templates.
- أضفنا اختبارات generate-all:
  - يمنع التوليد بدون template approved.
  - يفشل batch بشكل واضح إذا كل المنتجات بدون صور.
  - يحسب نجاح وفشل المنتجات بشكل صحيح في حالة mixed generation.
- أضفنا اختبار regenerate:
  - الأصل يبقى محفوظ.
  - النسخة الجديدة تحفظ feedback.
  - النسخة الجديدة تربط نفسها بالأصل من خلال `regenerated_from_asset_id`.
- أضفنا route guard tests:
  - generate-first يمنع batch فارغ.
  - generate-all يمنع template missing/stale.
  - approve template يمنع template من خارج batch.
  - regenerate يمنع item/template غير صالحين.
- أكملنا route guard tests الإضافية:
  - Excel أكبر من الحد يرجع 413 واضح.
  - ZIP أكبر من الحد يرجع 413 واضح.
  - Excel غير صالح يرجع 400 مع سبب واضح.
  - generation status يفحص batch scope قبل ما يقرأ job.

## التحقق

- `tests/test_product_bulk_generator.py`: 7 passed.
- `tests/test_product_bulk_routes.py`: 6 passed.
- Product Bulk focused suite:
  - `tests/test_product_bulk_generator.py`
  - `tests/test_product_bulk_routes.py`
  - `tests/test_product_bulk_models.py`
  - `tests/test_product_bulk_parser.py`
  - النتيجة: 25 passed.

## الحالة الآن

- `DEV-I-01`: done.
- `DEV-I-02`: done.
- `DEV-I-03`: done.
- `DEV-I-04`: done.

كل اختبارات transition و route guards المطلوبة لهذه المرحلة صارت موجودة ومارة محلياً.

## الخطوة التالية المقترحة

ننتقل إلى `DEV-I-05`:

- UI lifecycle gates في Product Bulk Studio.
- الأزرار والنصوص لازم تعكس الحالات الحقيقية:
  - mapped
  - failed
  - first_generating
  - awaiting_template_approval
  - approved_template
  - generating_all
  - completed

الهدف: المستخدم لا يشوف زر يسمح له يعمل خطوة غير جاهزة، ولا يشوف رسالة عامة مثل Not Found بدون سبب واضح.
