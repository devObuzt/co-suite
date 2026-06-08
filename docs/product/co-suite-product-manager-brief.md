# co-Suite Product Manager Brief

Date: 2026-06-03  
Last updated: 2026-06-06

## One-Liner

co-Suite هو تطبيق AI marketing operating system لكل مصلحة، صانع محتوى، أو وكالة تسويق: يبني بروفايل بزنس ذكي، يفهم البراند والجمهور، يولد محتوى وصور وفيديوهات وحملات، يربط قنوات الإعلان والنشر، ويحوّل التسويق اليومي من شغل متعب ومتقطع إلى نظام قابل للإدارة والأتمتة.

## Product Vision

الهدف ليس “مولد بوستات”. الهدف تطبيق أحلام لكل مصلحة: مكان واحد يعرف البزنس، يعرف كيف يخاطب جمهوره، يعرف قنواته، يعرف براندته، ويقدر يشتغل معه كفريق تسويق مصغر.

المستخدم يدخل روابطه، ملفاته، منتجاته، لغاته، قواعده، وشخصياته. co-Suite يبني “ذاكرة تسويقية” للسوت، ثم يستخدمها في كل شيء:

- توليد أفكار ومحتوى.
- توليد صور وفيديوهات وكاروسيلات.
- بناء جدول محتوى.
- اقتراح منافسين وسوق.
- جلب وتحليل حملات Meta وGoogle.
- نشر وجدولة.
- بناء حملات ممولة.
- لاحقًا إدارة loop تسويقي شبه تلقائي.

المنتج يجب أن يكون جاهزًا لاستخدام كبير بنفس الوقت، وليس فقط demo يعمل لمستخدم واحد. التجربة يجب أن تتحمل عدد كبير من المستخدمين والطلبات المتزامنة بدون انهيار أو انتظار غامض. وفي نفس الوقت يجب أن يكون المنتج قابلًا للتوسع بقدرات ومنتجات جديدة بدون إعادة بناء المنظومة من الصفر.

## Target Users

### 1. Business / עסק / مصلحة / شركة / جمعية

صاحب مصلحة يريد نتائج تسويقية بدون فريق كامل. يحتاج:

- فهم واضح للبراند والجمهور.
- محتوى ثابت بجودة جيدة.
- نشر وجدولة.
- حملات ممولة بسيطة.
- تقارير مفهومة وليست dashboards معقدة.

### 2. Influencer / Creator / صانع محتوى / مؤثر

شخص يبني شخصية أو جمهور. يحتاج:

- لغة وأسلوب مطابق لشخصيته.
- شخصيات وصور مرجعية.
- أفكار محتوى مستمرة.
- فيديوهات وكاروسيلات.
- حفظ قواعد: كلمات يحبها، كلمات لا يريدها، tone، حدود قانونية أو ثقافية.

### 3. Marketing Agency / وكالة تسويق

فريق يدير عدة عملاء. يحتاج:

- Suites متعددة.
- تسريع onboarding لكل عميل.
- bulk generation للمنتجات.
- مراجعة/اعتماد/رفض.
- حملات وجدولة ونشر.
- فصل واضح بين clients, brands, calendars, campaigns.

## Core Object: Suite

السوت هو workspace لكل بزنس أو عميل. كل شيء يدور حوله:

- Business profile.
- Brand profile.
- Audience profile.
- Language profile.
- Content rules.
- Connected platforms.
- Generated content.
- Campaigns.
- Calendar/loops.
- Product bulk jobs.
- Analytics.

السوت لازم يحس مثل “مكتب التسويق الخاص بهذا البزنس”، وليس مجرد صفحة.

## Access Model: Account First, Suite When Needed

ليس كل استخدام داخل co-Suite يجب أن يبدأ بفتح Suite كامل. المستخدم يمكنه التسجيل بإيميل فقط أو تسجيل أساسي، ثم استخدام بعض منتجات التوليد السريعة بدون بناء بروفايل بزنس كامل.

هذا مهم لثلاثة أسباب:

- يقلل الاحتكاك في أول تجربة.
- يسمح للمستخدم بفحص جودة التوليد قبل الالتزام ببناء Suite.
- يفتح باب self-serve acquisition من أدوات بسيطة ومباشرة.

المنتجات التي يمكن أن تكون متاحة بدون Suite:

- Quick Post / Ad بسيط.
- Create Image.
- Create Video.
- Carousel أو Content Set محدود.
- بعض أدوات product creative إذا رفع المستخدم الملفات المطلوبة مباشرة.

في هذه الحالة:

- زر `Use brand` يكون مطفي أو غير متاح.
- التوليد يعتمد على prompt المستخدم والملفات المرفوعة فقط.
- لا يوجد Suite Memory عميق.
- يمكن حفظ النتائج على مستوى الحساب.
- التطبيق يقترح لاحقًا: “حوّل هذا إلى Suite لتحصل على براند، جمهور، جدولة، نشر، وتحليلات”.

الـ Suite يصبح مطلوبًا عندما يحتاج المستخدم:

- brand memory.
- audience/language/profile memory.
- connected platforms.
- publishing/scheduling.
- analytics.
- campaign builder.
- social calendar loops.
- product bulk workflows طويلة الأمد.

## Key Product Principles

### 1. Native Language First

إذا المستخدم اختار العربية، التطبيق يخاطبه بالعربية، والـ AI يقترح بالعربية، والمحتوى يطلع عربي عندما الجمهور عربي. نفس الشيء للعبرية والإنجليزية واللغات الأخرى.

اللغات الأساسية للسوق الأول:

- Arabic.
- Hebrew.
- English.

لغات إضافية مطلوبة:

- Russian.
- French.
- Spanish.
- Turkish.
- Chinese.

لاحقًا نحتاج Language Rules لكل عميل:

- كلمات نستخدمها.
- كلمات ممنوعة.
- استبدالات.
- جمل قانونية.
- tone خاص.
- اختلاف لغة التطبيق عن لغة الجمهور.

### 2. Brand Memory Before Generation

التوليد الجيد يعتمد على ذاكرة جيدة. لذلك setup السوت ليس form عادي، بل عملية بناء عقل تسويقي:

- الاسم.
- الفئة/النيش، ويجب أن تكون مبنية على البحث وليس ثابتة.
- لغات الجمهور وترتيب الأولوية.
- المنتجات والخدمات.
- الجمهور المستهدف.
- USP / ESP.
- البراند: logo, colors, fonts, visual rules.
- شخصيات/صور مرجعية.
- content themes.
- marketing message.

### 3. Human-in-the-Loop

المستخدم لا يريد automation عمياء. يريد سيطرة:

- confirm.
- edit.
- add.
- remove.
- approve.
- reject.
- regenerate with feedback.
- save rules from feedback.

كل رفض أو تعديل يجب أن يتحول مع الوقت إلى قاعدة داخل business profile.

### 4. Multi-Channel by Design

المحتوى لا يخرج بصيغة واحدة فقط. نحتاج التفكير من البداية في:

- Instagram.
- Facebook.
- TikTok لاحقًا.
- Google Ads.
- Meta Ads.
- Website/SEO.
- Mobile apps.

الصور، الفيديو، الكاروسيل، والحملات يجب أن تعرف الوجهة والسياق.

### 5. Scale-Ready from the Product Layer

co-Suite يجب أن يتصرف كمنصة جاهزة للنمو من البداية:

- المستخدم يرى حالة واضحة لكل عملية طويلة: queued, running, waiting, failed, completed.
- لا يوجد button يعلق بصمت.
- لا يوجد توليد طويل يوقف تجربة المستخدم.
- يمكن للمستخدم مغادرة الصفحة والرجوع لاحقًا ليرى النتيجة.
- كل منتج توليد له limits/credits/status واضحة.
- النظام يشرح للمستخدم إذا الطلب ينتظر مزود AI، رصيد، أو موافقة.
- تجربة المستخدم يجب أن تبقى مفهومة حتى في أوقات الضغط.

### 6. Expandable Product Platform

المنتج يجب أن يكبر كـ platform وليس feature pile. أي قدرة جديدة يجب أن تدخل ضمن نفس المنطق:

- نوع product/workflow واضح.
- input واضح.
- credits/cost واضح.
- job/status واضح.
- artifacts واضحة.
- review/approve/edit/publish/schedule عندما يكون مناسبًا.
- قابل للحفظ داخل Suite Memory إذا كان مرتبطًا بالبزنس.

أمثلة منتجات يمكن إضافتها لاحقًا:

- SEO content generator.
- landing page builder.
- WhatsApp campaign assistant.
- email campaign builder.
- TikTok content/campaign workflows.
- reputation/reviews assistant.
- CRM/lead follow-up automation.

الهدف أن كل منتج جديد يستفيد من Suite Memory، Billing/Credits، Queue، Media Storage، وConnections بدل بناء نظام منفصل لكل منتج.

## Primary User Journey

### Phase 1: Signup

المستخدم ينشئ حساب، ثم يحدد نوعه:

- Business.
- Creator/Influencer.
- Marketing agency.

هذا يؤثر لاحقًا على:

- أنواع المحتوى المقترحة.
- الأسئلة في setup.
- الافتراضات الخاصة بالجمهور.
- طريقة عرض dashboard.

بعد التسجيل، يجب أن يستطيع المستخدم الوصول إلى مساحة استخدام أساسية حتى لو لم يفتح Suite بعد. هذه المساحة تعرض أدوات توليد سريعة مع توضيح الفرق:

- بدون Suite: توليد سريع، prompt-driven، بدون ذاكرة براند.
- مع Suite: توليد مبني على بروفايل بزنس، براند، جمهور، لغات، اتصالات، وجدولة.

### Phase 2: Create Suite

المستخدم يضع:

- اسم السوت/البزنس.
- روابط موقع، Instagram، Facebook، LinkedIn أو غيرها.

النظام يحاول قراءة المصادر:

- website scraping.
- social profile scraping قدر الإمكان.
- search intelligence.
- extraction by AI.

### Phase 3: Business Profile Wizard

كل خطوة تكون screen واضحة:

1. Business name.
2. Category/niche.
3. Audience languages.
4. Products/services.
5. Target audience.
6. USP/ESP: “لماذا يختارك العميل؟”
7. Brand assets.
8. Personas/reference characters.

كل خطوة يجب أن تكون:

- native language.
- editable.
- AI-assisted.
- savable.
- reversible: يمكن الرجوع خطوة.

### Phase 4: Suite Workspace

بعد setup، المستخدم يدخل workspace للسوت.

القائمة الجانبية تنقسم إلى:

- Account links.
- Current Suite links.

الشاشات الأساسية:

- Home.
- Connections.
- Create & Generate.
- Content.
- Analytics.
- Brand/Profile.
- Market.
- Product Bulk Studio.
- Social Calendar Builder.
- Sponsored Campaign Builder.

### Phase 0 / Optional: Basic Generation Without Suite

قبل إنشاء Suite أو بدونها، يمكن للمستخدم استخدام أدوات توليد محدودة من داخل الحساب:

- كتابة prompt حر.
- رفع صورة أو ملف كمرجع عند الحاجة.
- اختيار نوع الناتج: post/ad/image/video/carousel.
- اختيار لغة الناتج الأساسية.
- اختيار format/aspect ratio عندما يكون ذلك مطلوبًا.

هذه التجربة يجب أن تكون مفيدة بحد ذاتها، لكنها تقود طبيعيًا إلى Suite:

- “احفظ هذه القواعد داخل Suite”.
- “اربط Instagram/Facebook/Google Ads للنشر والتحليل”.
- “ارفع اللوجوهات والخطوط لتحسين النتائج”.
- “ابنِ بروفايل بزنس للحصول على اقتراحات أدق”.

## Feature Areas

## 0. Standalone Generation Tools

هذه أدوات acquisition وutility سريعة. لا تعتمد على Suite، لكنها يجب أن تكون قابلة للترقية إلى Suite workflow.

المطلوب:

- تعمل بعد تسجيل أساسي فقط.
- لها limits أو credits واضحة.
- لا تتطلب business onboarding.
- لا تفترض brand/profile data غير موجودة.
- تسمح بحفظ الناتج على مستوى الحساب.
- تعرض CTA واضح لإنشاء Suite عند الحاجة للبراند، النشر، الجدولة، أو التحليلات.

التمييز في الواجهة:

- `Use brand`: مطفي إذا لا يوجد Suite.
- `Save to Suite`: يظهر فقط إذا عند المستخدم Suite أو بعد إنشائه.
- `Create Suite from this`: ينقل prompt/الناتج كبداية لملف السوت.

## 1. Subscription, Tokens, and Marketing Budget

نظام الدفع يجب أن يفصل بين ثلاثة أشياء مختلفة:

1. الانتساب الشهري/السنوي للمنصة.
2. توكنز/credits التوليد واستخدام منتجات AI.
3. رصيد ميزانية التسويق المدفوعة على منصات مثل Meta وGoogle Ads.

### Subscription

المستخدم يدفع اشتراك شهري أو سنوي. مثال أولي:

- Basic plan: `14.99$` شهريًا.
- يمكن تقديم خصم للاشتراك السنوي.
- الباقة تعطي رصيد توكنز شهري أو usage allowance.

مثال usage داخل باقة أساسية:

- معدل توليد صورة تقريبًا كل يوم.
- معدل توليد فيديو تقريبًا كل 3 أيام.
- حدود إضافية حسب تكلفة كل model ونوع التوليد.

هذه الأرقام ليست contract نهائي، لكنها تمثل منطق المنتج: الباقة الأساسية تعطي استخدام مستمر وخفيف، وليس استخدام غير محدود.

### Generation Tokens / Credits

كل منتج توليد يستهلك توكنز/credits حسب التكلفة:

- text/caption/idea: تكلفة منخفضة.
- image: تكلفة متوسطة.
- carousel: حسب عدد السلايدات والصيغ.
- video: تكلفة عالية.
- product bulk: حسب عدد المنتجات والقوالب والصيغ.

المستخدم يمكنه:

- استخدام الرصيد الشهري المرفق بالباقة.
- شراء token packs إضافية.
- الترقية إلى باقة أعلى لاستخدام بوتيرة أكبر.

الواجهة يجب أن تعرض:

- رصيد التوكنز الحالي.
- الاستهلاك المتوقع قبل بدء التوليد.
- هل الطلب سيستخدم رصيد الباقة أو رصيد tokens مشتراة.
- تحذير إذا الرصيد لا يكفي.

### Upgrade and Token Packs

طرق زيادة الاستخدام:

- Upgrade to higher plan.
- Buy one-time token pack.
- Agency/Team plan مع رصيد أكبر.
- Add-ons للـ video/product bulk/campaign automation.

القرار المنتج:

- الترقية مناسبة لمن يستخدم المنتج بشكل متكرر.
- token packs مناسبة لاستخدام موسمي أو حملة مؤقتة.

### Marketing Budget Balance

ميزانية الإعلان ليست توكنز AI. يجب أن تكون ledger منفصل.

عندما يطلب المستخدم فتح حملات على Meta, Google Ads أو غيرها:

- يدفع أو يودع رصيد ميزانية تسويق.
- هذا الرصيد مخصص للإنفاق الإعلاني والمنصات.
- لا يخلط مع توكنز التوليد.
- يظهر للمستخدم كـ `Marketing Budget Balance`.

المستخدم يجب أن يرى دائمًا:

- Subscription plan.
- Generation token balance.
- Marketing budget balance.
- الإنفاق الإعلاني الجاري.
- الرصيد المتبقي.
- أي رسوم منصة/إدارة إذا وجدت.

### Product Rule

لا يجوز تشغيل حملة مدفوعة أو استخدام ميزانية تسويق بدون confirmation واضح من المستخدم. AI يمكنه بناء campaign draft، لكن launch/activation يحتاج موافقة صريحة.

## 2. Business Profile and Brand Profile

هذه هي ذاكرة السوت.

يجب أن تشمل:

- معلومات البزنس.
- الجمهور.
- اللغات.
- المنتجات والخدمات.
- USP/ESP.
- marketing message.
- content themes.
- competitors.
- interests/behaviors/social segments.
- Google keywords/audience.
- Meta interests/behaviors/demographics.
- logos متعددة: square, horizontal, transparent, light/dark.
- fonts لكل لغة.
- colors مع hex وRGB.
- personas وصور مرجعية.

كل قسم:

- قابل للتعديل يدويًا.
- قابل لإعادة التوليد بالـ AI.
- يحتفظ بسجل واضح لما تم اختياره.

## 3. Connections

الربط الحالي والمطلوب:

- Facebook/Instagram عبر Meta.
- Meta Ads.
- Google Ads.
- R2 media storage.
- TikTok لاحقًا.
- Website/WordPress لاحقًا.

Connections يجب أن تكون شاشة مستقلة وواضحة، مع status lights:

- connected.
- missing permissions.
- storage ready.
- needs review.

## 4. Create & Generate

هذه ليست مجرد “Generate 3 posts”. هذه command center.

الخيارات المطلوبة:

- Quick Post/Ad.
- Create Anything.
- Campaign Builder.
- Product Bulk Studio.
- Content Set.
- Create Image.
- Create Video.
- Carousel.

كل خيار يغير الإعدادات والفلاتر لكنه يستفيد من نفس brand memory.

الإعدادات:

- Use brand: default on إذا السوت جاهز.
- Prompt كبير وواضح.
- Content type.
- Destination.
- Aspect ratio.
- Model/tier لاحقًا.
- Language/audience language.

## 5. Content Review System

كل محتوى يولد يصبح item قابل للإدارة:

- status: pending, approved, rejected, scheduled, published, used externally.
- created_at ظاهر.
- format: image, video, carousel, text, product bulk.
- approve.
- reject.
- regenerate with feedback.
- edit caption/text.
- download media.
- copy caption.
- publish.
- schedule.
- mark as used.

مهم: regenerate لا يجب أن يكون أعمى. يجب أن يسأل: لماذا رفضت؟ ثم يحفظ الملاحظة كتعلم للسوت.

## 6. Product Bulk Studio

للمتاجر والكتالوغات.

المستخدم يرفع:

- Excel فيه المنتجات.
- ZIP فيه صور المنتجات.
- prompt إضافي.

المنطق:

1. نقرأ Excel.
2. نطابق الصور من ZIP حسب اسم/مرجع الصورة.
3. نولد أول منتج بثلاث templates.
4. المستخدم يوافق أو يطلب تعديل.
5. بعد الموافقة نولد الباقي.
6. كل asset له approve/reject/regenerate/download.

مهم:

- لا نغير المنتج نفسه.
- لا نقطع المنتج بشكل سيء.
- السعر والاسم واضحين.
- output مناسب للسوشيال والإعلانات.

## 7. Content Generation Quality

المطلوب أن نغلق الفجوة مع `connec-content-engine`.

لـ images:

- single image should support multiple platform formats.
- carousel should generate native designed text on slides, especially educational carousel.
- product references and brand references should be passed when available.
- Arabic/Hebrew text needs model/support that handles multilingual text well.

لـ videos:

- نحتاج قواعد واضحة للـ text overlay.
- ممكن English overlay للفيديو عند الضرورة إذا العربي/العبراني سيئ في glyphs.
- استخدام Veo tiers أو بدائل حسب التكلفة/الجودة.
- video preview must work reliably.

الفكرة الأساسية: المحتوى يجب أن يكون لغة موحدة. لا صورة بالعربي وكابشن بالإنجليزي إلا إذا المستخدم طلب.

## 8. Social Calendar Builder

الهدف: بناء جدول محتوى قابل للعمل.

الخطوات المتوقعة:

1. اقتراح content pillars وأنواع المحتوى.
2. تحديد نسب كل نوع.
3. تحديد الأقسام/المجموعات المشمولة.
4. تحديد formats.
5. تحديد cadence: أيام وساعات وتكرار.
6. توليد calendar draft.
7. تحويل calendar إلى محتويات pending.
8. approve/schedule/publish.

بعض المحتوى يحتاج تدخل المستخدم، مثل:

- صور حقيقية.
- فيديوهات واقعية.
- assets ناقصة.

هذه تبقى tasks للمستخدم.

## 9. Sponsored Campaign Builder

الهدف: حملة تسويقية كاملة وليس إعلان واحد.

القنوات:

- Meta Ads.
- Google Ads.
- TikTok لاحقًا.

القدرات الحالية/المطلوبة:

- قراءة الحملات الشغالة فقط.
- عرض campaign/ad set/ad مع أرقام.
- filters حسب المصدر.
- إنشاء draft campaign.
- لاحقًا launch/manage/pause/edit.

الـ AI يجب أن يساعد في:

- objective.
- audience.
- creatives.
- copy.
- budget logic.
- landing page/CTA.

## 10. Analytics

التحليلات يجب أن تكون actionable.

نعرض:

- page followers.
- reach.
- impressions/views.
- engagement.
- campaign performance.
- recent media performance.
- warnings عن permissions.

الأهم: لا نعرض أصفار صامتة. إذا Meta permissions ناقصة، نقول ذلك بوضوح.

## 11. Market and Competitors

الهدف:

- البحث عن منافسين.
- قراءة market signals.
- جلب inspiration من Meta Ad Library.
- لاحقًا TikTok/search/SEO.

النتائج يجب أن تكون مرتبطة بالبزنس:

- location.
- niche.
- language.
- audience.
- services/products.

## Web, SEO, and Apps

### Website/SEO

co-Suite يحتاج موقع تسويقي واضح وقانوني:

- homepage قوية.
- privacy policy.
- terms.
- accessibility statement.
- billing/payment terms.
- AI usage disclosure.
- data and platform connection explanation.

SEO مهم لأنه المنتج نفسه موجه لأصحاب مصالح يبحثون عن حلول تسويق.

### Mobile

الموبايل ليس رفاهية. المستخدمين يفحصون من الهاتف كثيرًا.

مطلوب:

- واجهات أقل ازدحامًا.
- accordions.
- bottom-friendly actions.
- content preview جيد.
- video preview يعمل.
- no horizontal overflow.

### iOS/Android

لاحقًا نحتاج تطبيقات:

- review/approve من الهاتف.
- notifications.
- schedule approvals.
- content tasks.
- campaign alerts.

## Current Product Risks

1. Onboarding screens مزدحمة على الموبايل.
2. بعض التعديلات لا تظهر أونلاين إذا لم يتم push/deploy.
3. AI suggestions للبيانات القديمة لا تتجدد تلقائيًا.
4. Content generation يحتاج queue/limits handling دائمًا.
5. Media storage يجب أن يكون مضبوطًا، وإلا الصور/الفيديو لا تنشر بشكل موثوق.
6. Meta/Google permissions ممكن تعطي أصفار أو errors إذا لم تكن الصلاحيات كاملة.
7. بدون فصل واضح بين “brand memory” و“generation”, الجودة ستبقى متذبذبة.
8. بدون readiness لاستخدام متزامن كبير، أول حملة تسويقية ناجحة ممكن تكشف bottlenecks في AI providers, queues, DB, storage, أو واجهة status.
9. بدون product platform contract، كل منتج جديد سيزيد التعقيد بدل أن يضيف قيمة مركبة.

## Near-Term Priorities

### Priority 1: Stabilize Onboarding UX

- تنظيف Step E: audience.
- جعل location default Custom واضحًا وموجودًا أولًا.
- add all buttons واضحة.
- AI regenerate audience suggestions.
- mobile layout نظيف.
- logo multi-upload واضح ومصنف.

### Priority 2: Make Suite Workspace Clean

- كل شاشة لها هدف.
- Connections منفصلة.
- Create منفصلة.
- Content منفصل.
- Analytics منفصلة.
- Brand/Profile editable.

### Priority 3: Improve Generation Reliability

- consistent language.
- better media previews.
- queue status واضح.
- provider limit waiting state.
- regenerate feedback memory.

### Priority 4: Match Content Engine Quality

- image formats per platform.
- carousel text rendered by model.
- video model/tier support.
- references: logo, product, persona, brand.

### Priority 5: Campaign and Calendar Builders

- social calendar builder.
- sponsored campaign builder.
- campaign drafts before launch.

## Open Questions for You

1. هل co-Suite في المرحلة الأولى لازم يخدم أصحاب مصالح مباشرة، أم وكالات التسويق أولًا؟
2. ما السعر النهائي لكل باقة، وكم token allowance دقيق لكل نوع توليد؟
3. هل نريد المستخدم العادي يقدر يعمل campaign launch فعليًا، أم بالبداية campaign draft فقط؟
4. هل Product Bulk Studio جزء من الخطة الأساسية لكل مستخدم، أم feature مخصص للمتاجر/وكالات؟
5. هل نريد content approval mandatory قبل النشر، أم يمكن تفعيل auto-publish بعد ثقة معينة؟
6. ما هو تعريف “تجربة جاهزة للبيع” بالنسبة لك؟ onboarding فقط؟ generation؟ publishing؟ campaigns؟
7. هل أول سوق رسمي هو عرب الداخل/إسرائيل، أم نفتح عالميًا من البداية؟

## Product Manager Recommendation

ابدأوا بتثبيت ثلاث ركائز قبل توسيع المنتج:

1. Onboarding قوي يبني brand memory صحيحة.
2. Create/Content workflow مستقر وسلس.
3. Connections/Analytics موثوقة ولا تعرض أرقام مضللة.

بعدها ندخل بقوة إلى:

- Calendar automation.
- Campaign builder.
- Product bulk.
- Mobile apps.

بدون هذه الركائز، كل feature جديدة ستزيد الضجيج. معها، كل feature جديدة ستجلس فوق نظام واضح.
