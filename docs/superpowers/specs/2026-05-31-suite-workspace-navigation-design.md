# Suite Workspace Navigation Design

Date: 2026-05-31

## Goal

تحويل صفحة السوت الحالية من صفحة واحدة مزدحمة إلى workspace واضح لكل سوت. القائمة الجانبية تبقى فيها روابط الحساب العامة، وتحتها يظهر قسم خاص بالسوت الحالي يبدأ باسم السوت ويحتوي على شاشات السوت.

النتيجة المطلوبة: المستخدم يفهم أين هو، يرى حالة الربط بسرعة، ويصل إلى الإنشاء، المحتوى، التحليلات، البروفايل، السوق، والحملات من شاشات منفصلة بدل صفحة طويلة.

## Current Problem

الصفحة الحالية `/suite/[id]` تحتوي تقريبًا كل شيء:

- Header السوت.
- Connections.
- Create & Generate.
- Recent content.
- Competitors & Market.
- Meta ads inspiration.
- Campaigns.
- Analytics.
- Strategy/Profile data.

هذا يجعل الصفحة ثقيلة بصريًا وسلوكيًا، ويصعب تطوير كل جزء لوحده. كما أن القائمة الجانبية الحالية هي قائمة الحساب فقط ولا تعكس سياق السوت.

## Recommended Structure

نستخدم routing داخلي للسوت:

```txt
/suite/[id]                    -> الصفحة الرئيسية الجديدة للسوت
/suite/[id]/dashboard          -> الداشبورد القديمة الحالية
/suite/[id]/connections        -> التشابك مع أطراف خارجية
/suite/[id]/create             -> Create & Generate
/suite/[id]/content            -> Recent content
/suite/[id]/analytics          -> معطيات وتحليل
/suite/[id]/profile            -> العلامة التجارية والبروفايل
/suite/[id]/market             -> المنافسين والسوق
/suite/[id]/calendar           -> Social Calendar Builder
/suite/[id]/campaigns          -> Sponsored Campaign Builder
/suite/[id]/product-bulk       -> Product Bulk Studio
```

## Sidebar Design

القائمة الجانبية تنقسم إلى مستويين.

### Account Links

- لوحة التحكم: `/suites`
- سوت جديد: `/suite/new`
- الإعدادات: `/settings`

### Current Suite Links

تظهر فقط عندما يكون المستخدم داخل route من نوع `/suite/[id]`.

- اسم السوت كعنوان section.
- الرئيسية: `/suite/[id]`
- الداشبورد القديمة: `/suite/[id]/dashboard`
- Connections: `/suite/[id]/connections`
- Create & Generate: `/suite/[id]/create`
- المحتوى: `/suite/[id]/content`
- معطيات وتحليل: `/suite/[id]/analytics`
- العلامة التجارية والبروفايل: `/suite/[id]/profile`
- المنافسين والسوق: `/suite/[id]/market`
- Social Calendar Builder: `/suite/[id]/calendar`
- Sponsored Campaign Builder: `/suite/[id]/campaigns`
- Product Bulk Studio: `/suite/[id]/product-bulk`

Connections link يعرض indicators صغيرة:

- Meta/Facebook/Instagram.
- Google Ads.
- Media Storage/R2.

كل indicator يكون مضوي أو مطفي حسب حالة الربط.

## Page Responsibilities

### `/suite/[id]` New Suite Home

صفحة خفيفة تعرض:

- حالة السوت العامة.
- نقص المعلومات المهمة إن وجد.
- quick health: connections, brand completeness, storage, active jobs.
- CTA واضح إلى Create & Generate.
- آخر 3 محتويات.
- روابط مختصرة للشاشات المهمة.

هذه الصفحة ليست مكان كل التفاصيل.

### `/suite/[id]/dashboard`

تنقل إليها الداشبورد الحالية كما هي تقريبًا حتى لا نخسر أي منطق موجود. بعد النقل يمكن تقليلها تدريجيًا.

### `/suite/[id]/connections`

تعرض ConnectionsPanel الحالي كشاشة مستقلة:

- Facebook/Instagram.
- Google Ads.
- R2 media storage.
- TikTok لاحقًا.

Default: accordion/cards مغلقة، مع لمبات الحالة ظاهرة.

### `/suite/[id]/create`

المكان الأساسي للإنشاء.

الخيارات:

- Quick Post/Ad كـ default.
- Create anything.
- Campaign Builder.
- Product Bulk Studio.
- Content Set.
- Create Image.
- Create Video.
- Carousel.

الـ prompt يكون أكبر وأكثر راحة. خيارات mode تغير الفلاتر والإعدادات فقط، باستثناء Product Bulk Studio الذي يفتح صفحته المتخصصة.

Use brand:

- مفعل افتراضيًا إذا كان للسوت brand/profile كافٍ.
- disabled إذا لا يوجد سوت كامل أو لا توجد معلومات كافية، مع سبب واضح.

### `/suite/[id]/content`

تعرض Recent content لكل ما تولد أو يتولد.

الفلاتر:

- Type: All / Post / Image / Video / Carousel / Content Set / Bulk / Campaign.
- Status: Pending / Approved / Published / Rejected.

الترتيب دائمًا من الجديد إلى القديم. العرض يستعمل نفس منطق الكروت الحالي: approve, reject, regenerate, download, copy, publish/schedule عند توفرها.

### `/suite/[id]/analytics`

تجمع الأرقام:

- Facebook/Instagram page insights.
- Meta campaigns.
- Google Ads campaigns.
- لاحقًا TikTok.

هذه الصفحة لا تعرض إنشاء محتوى ولا profile editing.

### `/suite/[id]/profile`

هذه تصبح ذاكرة السوت القابلة للتعديل:

- business profile.
- audience languages.
- target audience.
- interests, behaviors, demographics.
- products/services.
- marketing message.
- USP/ESP.
- brand logos, colors, fonts.
- personas.
- content themes.
- strategy sections.
- Google Ads keywords/audience suggestions.
- Meta Ads interests/behaviors suggestions.

كل شيء قابل للتعديل يدويًا. أي section مبني بالـ AI يكون لديه زر regenerate واضح.

### `/suite/[id]/market`

تعرض:

- Competitors & Market الحالي.
- نتائج research.
- Meta ads/library inspiration.
- Google/search signals لاحقًا.

### `/suite/[id]/calendar`

Social Calendar Builder.

الهدف النهائي: بناء جدول محتوى كامل حسب وتيرة النشر، أنواع المحتوى، الأيام، الساعات، والقنوات. لاحقًا يمكن أن يشمل التوليد والنشر التلقائي، مع إبقاء المحتويات التي تحتاج تدخل بشري في pending/review.

### `/suite/[id]/campaigns`

Sponsored Campaign Builder.

الهدف النهائي: إنشاء وإدارة حملة تسويقية كاملة عبر Meta Ads وGoogle Ads، ولاحقًا TikTok. في البداية تعرض الحملات الحالية وتبدأ flow لإنشاء حملة draft.

## Component Refactor

قبل بناء الصفحات الجديدة، يجب فصل أجزاء `web/src/app/(dashboard)/suite/[id]/page.tsx` إلى components:

- `SuiteHeader`
- `ConnectionsPanel`
- `CreateCommandCenter`
- `RecentContent`
- `PostCard`
- `AnalyticsPanel`
- `CampaignsHub`
- `CompetitorsSection`
- `StrategyPanel`
- `MetaAdsInspirationSection`

هذا يقلل حجم الصفحة الحالية ويجعل كل شاشة تستعمل نفس المنطق بدون نسخ.

## Data Flow

`SuiteLayout` أو helper مشترك يقرأ suite id من path ويحمل:

- suite name/status/brand.
- connection summary.

كل صفحة فرعية تحمل بياناتها الخاصة عند الحاجة:

- connections page تحمل connections.
- analytics page تحمل insights/campaigns.
- content page تحمل posts/generation status.
- profile page تحمل strategy/brand/profile sections.

## Mobile Behavior

على الموبايل:

- القائمة العامة تبقى مختصرة.
- suite navigation تظهر كـ horizontal tabs أو drawer خفيف.
- لا تظهر كل الروابط دفعة واحدة إذا كانت تزحم الشاشة.

## Phased Implementation

### Phase 1

- إنشاء Suite sidebar section.
- نقل الصفحة الحالية إلى `/suite/[id]/dashboard`.
- جعل `/suite/[id]` صفحة home خفيفة.

### Phase 2

- فصل components من الصفحة الكبيرة.
- إنشاء صفحات connections, create, content, analytics, market.

### Phase 3

- تقوية profile page لتكون مركز تعديل brand/profile/strategy.
- إضافة regenerate لكل section.

### Phase 4

- Calendar Builder.
- Campaign Builder.
- تحسين filters والـ automation states.

## Testing

- `npm run build`.
- فحص navigation على desktop/mobile.
- فحص أن `/suite/[id]` لا يكسر الروابط القديمة.
- فحص approve/reject/regenerate بعد نقل content.
- فحص connections بعد نقل panel.
- فحص product bulk route يبقى يعمل كما هو.

## Approved Decision

تم اعتماد القرار الأساسي: `/suite/[id]` تصبح الصفحة الرئيسية الجديدة، والداشبورد الحالية تنتقل إلى `/suite/[id]/dashboard`.
