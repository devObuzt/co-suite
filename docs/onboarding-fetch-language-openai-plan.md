# خطة تطوير تجربة اللغة والفيتش في Oneshare

تاريخ: 2026-05-20

## الهدف

نريد أن يصبح فتح Suite جديد تجربة مريحة وذكية: المستخدم يختار اللغة التي يريد أن نخاطبه بها، يضع روابط البزنس، والنظام يبني Business Profile دقيق بلغته، مع القدرة لاحقا على توليد محتوى بلغات جمهور البزنس وقواعد لغوية خاصة بكل عميل.

الخطة تحافظ على Claude كمسار شغال، وتضيف OpenAI كمسار تجريبي/اختياري لنقارن جودة النتائج بدون كسر المنتج الحالي.

## الوضع الحالي في الكود

مسار الفيتش الحالي:

1. الواجهة في `web/src/app/(dashboard)/suite/new/page.tsx`.
2. المستخدم يضع روابط في Step 2.
3. الواجهة تستدعي `POST /api/v1/onboarding/extract-brand`.
4. الباك إند في `api/routers/onboarding.py`.
5. الفيتش الفعلي في `api/services/multi_scraper.py`.
6. التحليل وتحويل البيانات إلى Brand Profile في `api/services/brand_ai.py`.
7. Claude المستخدم حاليا:
   - `claude-sonnet-4-6` لاستخراج Brand Profile.
   - `claude-haiku-4-5-20251001` لترجمة USP/ESP/how_they_help وبعض اقتراحات البراند.

نقاط القوة الحالية:

- الفلو بسيط ومباشر.
- يدعم أكثر من رابط.
- يجمع الموقع + Instagram + Facebook + LinkedIn + بحث DuckDuckGo/Google.
- Instagram عندما ينجح يعطي قيمة عالية: bio, captions, hashtags, engagement.
- Claude يحول الخام إلى JSON مفهوم.

نقاط الضعف الحالية:

- اختيار اللغة يظهر كـ popup فوق signup ويسرق أول click، وهذا يربك المستخدم.
- TikTok/Twitter/YouTube تظهر كأنها مدعومة، لكنها فعليا تقرأ كـ website عادي.
- لا يوجد حفظ واضح لـ raw research/debug لكل رابط.
- لا يوجد status لكل رابط مثل: succeeded, partial, failed.
- AI output أحيانا يرجع بالإنجليزي رغم أن المستخدم اختار عربي/عبري.
- لا يوجد abstraction لاختيار provider: Claude أو OpenAI.

## التعديل المقترح 1: فصل لغات المنتج عن لغات الجمهور

نحتاج ثلاث طبقات مختلفة:

### 1. لغة المستخدم داخل التطبيق

هذه اللغة التي نخاطب بها صاحب البزنس داخل الواجهة والـ onboarding والرسائل والاقتراحات.

الحقل المقترح:

```txt
user.preferred_language = ar | he | en | ru | fr | es | tr | zh
```

اللغات الرئيسية للسوق الأول تظهر أولا:

```txt
ar: العربية
he: עברית
en: English
```

لغات إضافية تحت More languages:

```txt
ru: Русский
fr: Français
es: Español
tr: Türkçe
zh: 中文
```

### 2. لغات جمهور البزنس

هذه لا يجب أن تكون نفس لغة صاحب الحساب. مثلا صاحب البزنس يستخدم التطبيق بالعربي، لكن جمهوره عربي + عبري + إنجليزي.

الحقل المقترح داخل `suite.brand`:

```json
{
  "audience_languages": ["ar", "he", "en"],
  "primary_content_language": "ar"
}
```

الترتيب مهم. أول لغة هي اللغة الرئيسية للمحتوى.

### 3. قواعد اللغة الخاصة بالبراند

هذه للمرحلة القادمة، لكنها يجب أن تدخل التصميم الآن حتى لا نعيد البناء لاحقا.

الحقل المقترح:

```json
{
  "language_rules": {
    "ar": {
      "dialect": "Palestinian Arabic",
      "preferred_words": [],
      "forbidden_words": [],
      "replacements": [],
      "required_disclaimers": [],
      "tone_notes": ""
    },
    "he": {
      "dialect": "Modern Hebrew",
      "preferred_words": [],
      "forbidden_words": [],
      "replacements": [],
      "required_disclaimers": [],
      "tone_notes": ""
    }
  }
}
```

أمثلة:

- لا تستخدم كلمة "رخيص"، استخدم "مناسب".
- استبدل "زبائن" بـ "عملاء".
- أضف disclaimer قانوني لمجال التمويل أو الصحة.
- بالعربي استخدم لهجة محلية طبيعية.
- بالعبري استخدم أسلوب مهني ومباشر.

## التعديل المقترح 2: تعديل UX اختيار اللغة

المشكلة ليست وجود اختيار اللغة، بل شكله الحالي. يظهر فوق signup كأنه جزء من الصفحة، وزر Continue قد يلتبس مع Create account.

المقترح:

1. أول شاشة قبل التسجيل تكون واضحة:

```txt
كيف تحب نحكي معك؟
איך תרצה שנדבר איתך?
How should we speak with you?
```

2. الخيارات الأولى:

```txt
العربية
עברית
English
```

3. زر More languages يفتح:

```txt
Русский
Français
Español
Türkçe
中文
```

4. بعد الاختيار:
   - تحفظ اللغة في localStorage مؤقتا.
   - بعد signup تحفظ في `user.preferred_language`.
   - كل نصوص signup/onboarding تظهر باللغة المختارة.

## التعديل المقترح 3: جعل AI يتكلم Native من البداية

حاليا بعض النتائج يتم توليدها بالإنجليزي ثم نترجم أجزاء منها. هذا يسبب نتائج غير طبيعية.

المطلوب:

- كل AI call في onboarding يأخذ `user_language`.
- prompt الاستخراج يقول بوضوح:
  - استخرج من المصادر بأي لغة.
  - لكن اكتب الاقتراحات التي ستظهر للمستخدم بلغة `user_language`.
  - إذا `user_language=ar` استخدم عربي طبيعي مناسب للسوق المحلي.
  - إذا `user_language=he` استخدم عبري طبيعي.
  - لا تخلط English إلا إذا الاسم/المصطلح التجاري يتطلب.

تغيير مقترح في endpoint:

```py
class ExtractBrandRequest(BaseModel):
    suite_id: str
    urls: list[str] = []
    business_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    user_language: str = "en"
```

ثم:

```py
brand = await extract_brand_from_sources(
    urls,
    data.business_name,
    user_language=data.user_language,
)
```

## التعديل المقترح 4: تحسين نتيجة الفيتش

بدل أن نرجع فقط `brand`، نرجع أيضا تقرير خفيف للواجهة:

```json
{
  "brand": {},
  "research": {
    "sources": [
      {
        "url": "https://example.com",
        "platform": "website",
        "status": "success",
        "confidence": 0.82,
        "found": ["title", "description", "colors", "services"]
      },
      {
        "url": "https://instagram.com/example",
        "platform": "instagram",
        "status": "partial",
        "confidence": 0.55,
        "found": ["bio", "followers"],
        "missing": ["recent_posts"]
      }
    ],
    "overall_confidence": 0.71,
    "missing_info": ["logo file", "full product list"]
  }
}
```

هذا يفيدنا في:

- إظهار للعميل ماذا قرأنا.
- شرح لماذا صفحة معينة لم تعط بيانات.
- debugging لحالات مثل Instagram يعمل لحساب ولا يعمل لآخر.
- تحسين التوصيات: "ارفع كتالوج المنتجات" أو "أضف رابط الموقع".

## التعديل المقترح 5: حفظ raw research

نضيف داخل `suite.brand_research` أو جدول مستقل لاحقا:

```json
{
  "last_run_at": "2026-05-20T...",
  "sources": [],
  "search_snippets": "",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6"
}
```

للبداية يمكن حفظها في `suite.brand` تحت مفتاح:

```json
"_research_debug": {}
```

لكن الأفضل لاحقا جدول منفصل حتى لا نخلط بيانات المستخدم النهائية مع raw scraping.

## التعديل المقترح 6: إضافة OpenAI بجانب Claude

نريد الاثنين شغالين:

- Claude يبقى default الحالي.
- OpenAI يدخل كـ provider اختياري للتجربة.
- نقدر نقارن نفس المصادر على providerين.

### إعدادات مقترحة

في `api/core/config.py`:

```py
openai_api_key: str = ""
ai_text_provider: str = "anthropic"  # anthropic | openai
openai_text_model: str = "gpt-5.1"
openai_fast_model: str = "gpt-4.1"
openai_image_model: str = "gpt-image-1.5"
```

ملاحظة: حسب توثيق OpenAI الرسمي، `gpt-image-1.5`, `gpt-image-1`, و`gpt-image-1-mini` متاحة لعائلة GPT Image، و`gpt-5.1` موصى به للاستخدام العام المعقد، بينما `gpt-4.1` مناسب كمسار سريع وغير reasoning للـ instruction following والـ structured outputs.

مصادر OpenAI الرسمية:

- Image generation guide: https://platform.openai.com/docs/guides/image-generation
- GPT Image 1.5 / image tool docs: https://platform.openai.com/docs/guides/tools-image-generation
- GPT-5.1 guide: https://platform.openai.com/docs/guides/gpt-5
- GPT-4.1 model docs: https://platform.openai.com/docs/models/gpt-4.1

### ملف جديد مقترح

```txt
api/core/llm_client.py
```

يوفر واجهة واحدة:

```py
async def call_llm_json(
    provider: str,
    model: str,
    messages: list,
    max_tokens: int,
    schema_name: str | None = None,
) -> dict:
    ...
```

أو أبسط للمرحلة الأولى:

```py
async def call_text_ai(provider: str, model: str, messages: list, max_tokens: int) -> str:
    if provider == "openai":
        return await call_openai(...)
    return await call_claude(...)
```

ثم `brand_ai.py` لا يعرف مباشرة Claude أو OpenAI، بل يستخدم:

```py
raw = await call_text_ai(
    provider=settings.ai_text_provider,
    model=settings.openai_text_model if provider == "openai" else "claude-sonnet-4-6",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=2048,
)
```

## التعديل المقترح 7: تجربة مقارنة Claude/OpenAI

نضيف endpoint داخلي أو flag في الطلب:

```py
class ExtractBrandRequest(BaseModel):
    ...
    ai_provider: str | None = None  # anthropic | openai
    compare_providers: bool = False
```

سيناريوهات:

### الوضع العادي

```json
{
  "ai_provider": null,
  "compare_providers": false
}
```

يستخدم default من env.

### تجربة OpenAI فقط

```json
{
  "ai_provider": "openai"
}
```

### مقارنة داخلية

```json
{
  "compare_providers": true
}
```

يرجع:

```json
{
  "brand": {},
  "provider": "anthropic",
  "comparison": {
    "anthropic": {"brand": {}, "latency_ms": 4300},
    "openai": {"brand": {}, "latency_ms": 3900}
  }
}
```

لا نعرض المقارنة للعميل في البداية. نخزنها أو نستخدمها داخليا للتقييم.

## أين نستخدم OpenAI أولا؟

الأولوية ليست استبدال Claude بالكامل. الأفضل نجرب OpenAI في نقاط محددة:

1. `extract_brand_from_sources`
   - هل يعطي JSON أنظف؟
   - هل يحافظ على لغة المستخدم أفضل؟
   - هل يستنتج services/audience بدون اختراع؟

2. `translate_brand_fields`
   - نقارن ترجمة عربي/عبري طبيعية.

3. `generate_strategy`
   - لاحقا، بعد تثبيت extract.

4. `generateBrandAssets`
   - للصور والشعارات لاحقا عبر `gpt-image-1.5` كتجربة مقابل Gemini.

## ملاحظات مهمة للصور والشعارات

حاليا logo generation يستخدم Google image model عبر `_generate_image`.

اقتراحنا:

- لا نستبدله الآن.
- نضيف provider جديد للصور:

```py
image_provider: str = "google"  # google | openai
google_image_model: str = "gemini-3-pro-image-preview"
openai_image_model: str = "gpt-image-1.5"
```

قواعد الشعار:

- إذا `icon_only`: ممنوع أي نص داخل الصورة.
- إذا `with_name` أو `initials`: نولد icon فقط، ثم نركب النص نحن بـ Pillow/fonts.
- هذا مهم للعربي والعبري لأن موديلات الصور لا تضمن نص مضبوط 100%.

## خطة تنفيذ على مراحل

### Phase 1: UX language cleanup

- تحويل language picker من popup مربك إلى شاشة/خطوة واضحة.
- جعل أول 3 لغات: عربي، عبري، إنجليزي.
- إضافة More languages: روسي، فرنسي، إسباني، تركي، صيني.
- حفظ اللغة بعد signup في user profile لاحقا.

### Phase 2: Native AI language

- تمرير `user_language` إلى `/extract-brand`.
- تحديث prompts في `brand_ai.py`.
- إلغاء الاعتماد على ترجمة جزئية فقط.
- كل اقتراح يظهر في wizard يكون بلغة المستخدم.

### Phase 3: Research report

- تعديل `gather_all_sources` حتى يرجع status/confidence/found/missing لكل رابط.
- إرجاع `research` مع `brand`.
- عرض ملخص بسيط في UI:
  - "قرأنا الموقع بنجاح"
  - "Instagram أعطى bio فقط"
  - "لم نستطع قراءة TikTok، يمكنك إضافة وصف يدوي"

### Phase 4: OpenAI provider experiment

- إضافة `OPENAI_API_KEY`.
- إضافة `api/core/llm_client.py`.
- دعم `ai_provider=anthropic|openai`.
- تشغيل مقارنة داخلية على نفس input.
- حفظ provider/model/latency في debug.

### Phase 5: Language rules per brand

- إضافة UI لاحقا داخل Business Profile:
  - preferred words
  - forbidden words
  - replacements
  - required disclaimers
  - tone notes
- تمرير هذه القواعد لكل content generation prompt.

## النتيجة المتوقعة

بعد هذه التعديلات، التجربة تصبح:

1. المستخدم يختار كيف نخاطبه.
2. كل الواجهة والاقتراحات تظهر بلغته.
3. البزنس يحتفظ بلغات جمهور منفصلة عن لغة المستخدم.
4. الفيتش يعطي شفافية: ماذا قرأنا وماذا لم نقرأ.
5. Claude وOpenAI يعملان بالتوازي خلف نفس الواجهة.
6. نقدر نقيس من يعطي أفضل business profile قبل قرار التبديل أو الدمج.

