---
title: "co-Suite Owner Review - Screen Design Before Code"
date: "2026-06-07 19:13:07"
direction: rtl
---

<div dir="rtl" style="text-align: right; font-family: Arial, 'Noto Sans Arabic', sans-serif; line-height: 1.75;">

# هل نصمم الشاشات قبل الكود؟

**الجواب المختصر:** نعم، للشاشات المهمة لازم نصمم قبل الكود.  
لكن مش لازم نعمل تصميم ثقيل لكل زر صغير. بنفرق بين شاشة استراتيجية وشاشة تنفيذية بسيطة.

## كيف راح نشتغل؟

### 1. Product Brief

قبل أي شاشة نحدد:

- مين المستخدم؟
- شو بده يعمل؟
- شو أول شيء لازم يفهمه؟
- شو القرار أو الفعل المطلوب منه؟
- شو البيانات المطلوبة من backend؟
- شو الأخطاء والحالات الفارغة والانتظار؟

### 2. UX Flow

نرسم مسار المستخدم:

- من أين يدخل؟
- ماذا يرى أولاً؟
- ماذا يحدث عند الضغط؟
- كيف يرجع خطوة؟
- كيف تظهر الحالات: loading, empty, failed, success؟

### 3. Wireframe سريع

نصمم توزيع الشاشة بدون تفاصيل كثيرة:

- أماكن الأقسام.
- ترتيب الأولويات.
- أزرار أساسية وثانوية.
- mobile وdesktop.
- RTL/LTR من البداية.

### 4. Visual Direction

نطبق هوية co-Suite / Connec:

- أبيض وأسود كأساس.
- أصفر للـ branding.
- زهري للتسويق.
- أزرق للتطوير.
- دعم dark/light.
- لغة المستخدم واتجاهها.

### 5. Component Contract

قبل الكود نحدد:

- ما هي المكونات؟
- ما هي props/data المطلوبة؟
- من أين تأتي البيانات؟
- ماذا يحدث إذا البيانات ناقصة؟
- ما الذي يحتاج API جديد؟

### 6. Build Slice

بعد الموافقة، نكود الشاشة كـ slice صغير:

- component
- API integration
- states
- tests أو type checks
- QA smoke

## متى نصمم ومتى نكود مباشرة؟

نصمم قبل الكود عندما تكون الشاشة:

- جزء من onboarding.
- dashboard أو navigation.
- create/generate flow.
- content review.
- billing/tokens.
- campaign builder.
- social calendar loop.
- أي شاشة موبايل/RTL حساسة.

نكود مباشرة فقط عندما تكون:

- إصلاح backend صغير.
- validation بسيط.
- API field.
- copy أو status واضح.
- bug fix محدود لا يغير تجربة المستخدم.

## الأدوات العملية

راح نوثق كل شاشة مهمة في:

`docs/software-company/projects/cosuite/design/`

ولكل شاشة ممكن يكون عندها:

- brief
- wireframe notes
- UX states
- component contract
- QA checklist

إذا احتجنا visual mockup، بنعمل HTML أو screenshot محلي قبل الكود، وبعد موافقتك نبدأ التنفيذ.

## القرار المقترح

للخطوة القادمة `DEV-D-01`، وهي التوليد المحدود بدون Suite، لازم نعمل تصميم مختصر قبل الكود.

التصميم يجب أن يحدد:

- أين تظهر التجربة بعد التسجيل.
- ما الذي يستطيع المستخدم توليده بدون Suite.
- كيف نوضح أن `Use brand` غير متاح.
- كيف ندفعه لإكمال Suite بدون إزعاج.
- كيف تظهر حالات job/media/error.

## الخلاصة

نعم، سنصمم الشاشات قبل الكود عندما تكون مؤثرة على تجربة المستخدم أو المنتج.  
هذا يمنعنا من بناء واجهات عشوائية ويجعل التطوير أسرع لأن المطور يعرف ماذا يبني، وQA يعرف ماذا يفحص، والمالك يعرف ماذا يراجع.

</div>
