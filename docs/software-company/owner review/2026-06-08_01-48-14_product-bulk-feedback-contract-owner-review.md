# تقرير مراجعة المالك - إصلاح عقد Feedback في Product Bulk

التاريخ: 2026-06-08 01:48  
المسؤولون: Daniel Farah / Developers Manager، Rami Saleh / Developers

## ماذا أنجزنا

- فحصنا Product Bulk Studio من الواجهة إلى الباكند.
- وجدنا فجوة مهمة: الواجهة تطلب feedback قبل رفض asset، لكن الباكند لم يكن يستقبله أو يحفظه.
- أضفنا `RejectAssetRequest` في الباكند.
- صار reject asset يحفظ feedback في:
  - `asset.feedback`
  - `asset.ai_metadata.rejection_feedback`
- صار frontend API يرسل feedback عند reject.
- بعد reject أو regenerate، يتم تنظيف feedback input لذلك asset.

## لماذا هذا مهم

Product Bulk يعتمد على الموافقة/الرفض/إعادة التوليد. إذا المستخدم كتب ملاحظة ولم تُحفظ، النظام لا يتعلم من الخطأ، وتجربة "Regenerate with feedback" تصبح ناقصة. هذا الإصلاح يغلق جزءاً أساسياً من حلقة التعلم.

## التحقق

- `pytest -p no:cacheprovider tests/test_product_bulk_models.py tests/test_product_bulk_parser.py -q` مرّ: 8 passed.
- `npm run build` مرّ بنجاح.

## القرار

DEVMGR-03 بدأ فعلياً، وأول gap في Product Bulk stability تم إصلاحه.

## الخطوة التالية

- فحص عرض assets/generated templates في Product Bulk.
- التأكد أن المستخدم يرى حالة كل asset بوضوح وأن الأفعال الفردية تعطي feedback كافياً.
