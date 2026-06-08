---
title: "OneShare Brand UI Direction - Owner Review"
date: "2026-06-07 22:52:29"
direction: rtl
---

<div dir="rtl" style="text-align: right; font-family: Arial, 'Noto Sans Arabic', sans-serif; line-height: 1.75;">

# مراجعة المالك - اتجاه تصميم OneShare

## ما تم فحصه من ملف البراند

تم فحص ملف البراند المرفق، وفيه:

- Logos بصيغ SVG / PNG / PDF.
- خط Montserrat للإنجليزي.
- خط Cairo للعربي.
- خط Assistant للعبراني.
- ألوان أساسية من اللوجو: أسود/رمادي مع أصفر واضح.
- روبوت Connec كـ presenter محتمل.
- social/design icons.

## قرار الاسم واللوجو

اسم التطبيق يصبح:

**OneShare**

اللوجو الحالي المقترح:

- نص OneShare فقط.
- بخط Montserrat الثقيل من البراند.
- استخدام النقطة الصفراء كإشارة ذكية مستوحاة من نقطة حرف O في Connec.
- لا نستخدم شعار Connec نفسه داخل التطبيق كاسم، لأن التطبيق تابع للعلامة لكنه منتج مستقل.

## اتجاه التصميم

OneShare يجب أن يرث من Connec:

- الثقة والوضوح.
- الأسود/الأبيض كأساس.
- الأصفر كإشارة brand قوية.
- الزهري لقسم التسويق.
- الأزرق لقسم التطوير.
- واجهة أكثر نظافة وترتيباً من النسخة الحالية.

## الخطوط

نظام الخطوط المقترح:

- English / Latin: Montserrat.
- Arabic: Cairo.
- Hebrew: Assistant.
- fallback عالمي للغات القادمة.

هذا مهم لأن التطبيق لاحقاً سيدعم أكثر من 10 لغات.

## جاهزية اللغات

يجب ألا نبني اللغة كحالات hard-coded داخل الشاشات.

المطلوب:

- language registry واحد.
- لكل لغة: label، direction، font family، locale.
- كل شاشة تستخدم translation keys.
- RTL/LTR من design system وليس من كل component لوحده.
- إمكانية إضافة لغة جديدة بدون إعادة بناء الواجهة.

## دور الروبوت

الروبوت ممتاز كـ presenter، لكن لا يجب استخدامه في كل مكان.

الاستخدام المناسب:

- onboarding.
- empty states.
- assistant/help moments.
- success moments.
- صفحات تعليمية أو تسويقية.

الاستخدام غير المناسب:

- dashboard كثيف.
- جداول وتحليلات.
- أماكن تحتاج تركيز عملي.

## الملفات الناتجة

تم إنشاء visual direction:

`docs/software-company/projects/cosuite/design/2026-06-07_22-52-29_oneshare-brand-ui-direction.*`

وتشمل:

- HTML
- PNG screenshot
- PDF

## القرار التالي

بعد اعتماد الاتجاه، نبدأ UI Quality Pass على:

1. Signup / onboarding
2. Suite dashboard
3. Create & Generate
4. Content Review
5. Brand/Profile

ثم نحول التصميم إلى design system tokens ومكونات فعلية داخل التطبيق.

</div>
