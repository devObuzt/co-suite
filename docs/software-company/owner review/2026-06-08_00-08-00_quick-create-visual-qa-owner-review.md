# ملخص للمالك - Quick Create Visual QA

التاريخ: 2026-06-08 00:08  
المسؤول: Lina Saad / Noa Barak / Rami Saleh

## ماذا فحصنا

فحصنا صفحة `/create` الجديدة محليًا على desktop و mobile باستخدام Chrome headless screenshots.

## ماذا وجدنا

- أول لقطة أظهرت شاشة اختيار اللغة، لذلك عرفنا أن QA يحتاج تجاوز `co_suite_lang_set`.
- بعد تجاوزها ظهرت صفحة `/create` بشكل صحيح.
- وجدنا عدم تناسق في الهوية: الصفحة تقول OneShare، لكن القائمة الجانبية كانت تعرض co-Suite.
- وجدنا أن الصفحة ترمي مشكلة dev عندما يكون الـ API غير شغال محليًا.

## ماذا أصلحنا

- غيرنا `BrandMark` ليعرض OneShare بدل co-Suite.
- غيرنا alt text للصورة إلى OneShare logo.
- مسكنا أخطاء تحميل آخر التوليدات داخل صفحة `/create`.
- مسكنا أخطاء زر Generate داخل صفحة `/create`.
- بدل crash أو dev overlay، المستخدم يرى رسالة واضحة أن الـ API غير متصل.

## لقطات التحقق

- Desktop: `docs/software-company/projects/cosuite/design/2026-06-08_0003_create-desktop.png`
- Mobile: `docs/software-company/projects/cosuite/design/2026-06-08_0003_create-mobile.png`

## التحقق

- `npm run build` نجح بعد الإصلاح.

## الخطوة التالية

ننتقل الآن لشاشة Target Audience في onboarding:

- Custom يكون الديفولت في الموقع الجغرافي.
- أزرار Add all للاهتمامات والسلوك والحالة الاجتماعية.
- السلوك والحالة الاجتماعية لازم تكون مبنية على تحليل البزنس، وليس قيم ثابتة فقط.
- تحسين شكل الموبايل للـ chips والحقول.

