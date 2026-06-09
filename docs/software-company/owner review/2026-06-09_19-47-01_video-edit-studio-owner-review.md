# Video Edit Studio Owner Review

Date: 2026-06-09 19:47
Project: OneShare / co-Suite
Prepared by: Layla Haddad, Project Management

## شو دخلنا على المشروع

وثقنا ميزة جديدة باسم مؤقت:

**Video Edit Studio / Montage**

الفكرة: المستخدم يضغط من `Create & Generate` على خيار مونتاج/تحرير فيديو، ويدخل لسيرورة واضحة بدل ما تكون مجرد توليد فيديو عادي.

## السيرورة المقترحة

1. يختار نوع الفيديو:
   - شخص أو أشخاص يتحدثون للكاميرا.
   - منتجات أو مقاطع متعددة نركبها مع بعض.
2. يرفع فيديو أو عدة فيديوهات، أو يعطي رابط Google Drive قابل للوصول.
3. إذا في أكثر من فيديو، التطبيق يرتبهم حسب الاسم، والمستخدم يقدر يغير الترتيب.
4. كل فيديو يظهر معه thumbnail واسم وpreview.
5. المستخدم يختار خيارات المونتاج:
   - إزالة الخلفية.
   - مؤثرات صوتية.
   - transitions.
   - حذف المساحات الميتة.
   - 3D titles بين الشخص والخلفية.
   - captions أو text overlays.
   - موسيقى.
   - رفع موسيقى أو مؤثرات من عنده.
   - ملاحظات عامة.
6. بعدها يدخل الطلب queue مثل توليد AI.
7. المستخدم يشوف progress حسب مراحل المعالجة.
8. في النهاية يظهر الفيديو مع preview/download/approve/reject/regenerate مثل باقي المحتويات.

## شو الأقسام لازم تعمل

- Product Manager: يثبت الوعد وحدود V1.
- Design: يصمم wizard مريح للرفع، الترتيب، الاختيارات، والنتيجة.
- Architecture: يحدد job model, states, storage, providers, retries, cancellation.
- DevOps: يفحص Remotion/ffmpeg worker، limits، storage cleanup، alerts.
- Developers Manager: يحولها slices تنفيذية.
- Developers: backend APIs, worker, frontend wizard.
- QA: يبني fixtures وsmoke tests للفيديوهات الناجحة والفاشلة.

## الملفات التي انضافت

- `docs/software-company/projects/cosuite/video-edit-studio-feature-brief-m2.md`
- `docs/software-company/projects/cosuite/implementation-slice-05-video-edit-studio-m2.md`

## القرار

هذه الميزة صارت موثقة كـ M2 feature.

لا نبدأ كودها الآن قبل:

- إنهاء Product Bulk UI lifecycle gates.
- تصميم الواجهة.
- قرار architecture بخصوص worker/render pipeline.
- قرار max duration / max file size / credit cost.

## الخطوة التالية

بعد Product Bulk UI، نطلب من Design وArchitecture يبدؤوا `DESIGN-02` و`ARCH-03` للميزة.
