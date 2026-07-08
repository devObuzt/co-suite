"""Initial startbyconnec catalog, consolidated from Connec's 14 price-quote sheets.

Prices in ₪ before VAT. Admin edits the live rows afterwards; this seed only
runs when service_items is empty.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.services_catalog import ServiceItem

log = logging.getLogger(__name__)

_WEB = {"ar": "مواقع وتطبيقات", "he": "אתרים ואפליקציות"}
_HOSTING = {"ar": "استضافة ودومينات", "he": "אחסון ודומיינים"}
_MARKETING = {"ar": "تسويق وإعلانات", "he": "שיווק ופרסום"}
_CONTENT = {"ar": "محتوى وإنتاج", "he": "תוכן והפקה"}
_BUNDLES = {"ar": "باقات", "he": "חבילות"}

SEED_ITEMS: list[dict] = [
    {
        "name": {"ar": "موقع تعريفي", "he": "אתר תדמיתי"},
        "description": {
            "ar": "تطوير موقع تعريفي مخصّص للظهور العضوي في جوجل ومحركات الذكاء الاصطناعي.",
            "he": "פיתוח אתר תדמיתי מותאם לקידום אורגני בגוגל ובמנועי ה-AI.",
        },
        "category": _WEB, "billing_cycle": "one_time",
        "price_min": 3500, "price_max": None, "unit": None, "sort_order": 10,
    },
    {
        "name": {"ar": "متجر إلكتروني (موقع)", "he": "אתר איקומרס"},
        "description": {
            "ar": "متجر كامل: كتالوج، سلة، كوبونات، سليكة، شحن واستلام ذاتي ولوحة إدارة.",
            "he": "חנות מלאה: קטלוג, עגלה, קופונים, סליקה, משלוחים ואיסוף עצמי ודשבורד ניהול.",
        },
        "category": _WEB, "billing_cycle": "one_time",
        "price_min": 4900, "price_max": 11700, "unit": None, "sort_order": 20,
    },
    {
        "name": {"ar": "تطبيق إيكومرس (متجر + توصيل)", "he": "אפליקציית איקומרס"},
        "description": {
            "ar": "تطبيق متجر كامل مع تطبيق سائقين، إشعارات، مبيعات وعروض، ونشر بالمتاجر.",
            "he": "אפליקציית חנות מלאה כולל אפליקציית שליחים, התראות, מבצעים והפצה בחנויות.",
        },
        "category": _WEB, "billing_cycle": "one_time",
        "price_min": 87000, "price_max": 109000, "unit": None, "sort_order": 30,
    },
    {
        "name": {"ar": "استضافة الموقع", "he": "אחסון אתר"},
        "description": {
            "ar": "استضافة عبرنا — حسب حجم الموقع وعدد الزوّار.",
            "he": "אחסון דרכנו — לפי גודל האתר וכמות המבקרים.",
        },
        "category": _HOSTING, "billing_cycle": "monthly",
        "price_min": 39, "price_max": 299, "unit": None, "sort_order": 40,
    },
    {
        "name": {"ar": "دومين", "he": "דומיין"},
        "description": {
            "ar": "شراء دومين باسم العميل (مثلاً your-business.co.il).",
            "he": "רכישת דומיין על שם הלקוח (למשל your-business.co.il).",
        },
        "category": _HOSTING, "billing_cycle": "yearly",
        "price_min": 69, "price_max": 90, "unit": None, "sort_order": 50,
    },
    {
        "name": {"ar": "إنشاء المنظومة الرقمية", "he": "הקמת מערך דיגיטלי"},
        "description": {
            "ar": "صفحات فيسبوك، انستغرام وتيك توك + حساب أعمال ومدير إعلانات، بروفايل جوجل وحساب Google Ads — كله مربوط تحت حساب العميل.",
            "he": "דפי פייסבוק, אינסטגרם וטיקטוק + חשבון עסקי ומנהל מודעות, פרופיל גוגל וחשבון Google Ads — הכל קשור תחת חשבון הלקוח.",
        },
        "category": _MARKETING, "billing_cycle": "one_time",
        "price_min": 1500, "price_max": None, "unit": None, "sort_order": 60,
    },
    {
        "name": {"ar": "جرافيكس — حزمة بانرات", "he": "גרפיקות — חבילת באנרים"},
        "description": {
            "ar": "20 بانر لتعبئة الصفحات الجديدة: الخدمات، آراء الزبائن، وقصة المصلحة.",
            "he": "20 באנרים למילוי הדפים החדשים: השירותים, פידבקים מלקוחות וסיפור העסק.",
        },
        "category": _CONTENT, "billing_cycle": "one_time",
        "price_min": 1200, "price_max": None,
        "unit": {"ar": "حزمة 20 بانر", "he": "חבילת 20 באנרים"}, "sort_order": 70,
    },
    {
        "name": {"ar": "إنشاء وإدارة حملات Google & Meta", "he": "הקמה וניהול קמפיינים Google & Meta"},
        "description": {
            "ar": "إنشاء، إدارة وتحسين الحملات في ميتا، جوجل وتيك توك حسب الحاجة.",
            "he": "הקמה, ניהול ואופטימיזציה של קמפיינים במטא, גוגל וטיקטוק לפי הצורך.",
        },
        "category": _MARKETING, "billing_cycle": "monthly",
        "price_min": 2100, "price_max": 2200, "unit": None, "sort_order": 80,
    },
    {
        "name": {"ar": "ترويج عضوي SEO + GEO", "he": "קידום אורגני SEO + GEO"},
        "description": {
            "ar": "ترويج عضوي في محركات بحث جوجل ومحركات الذكاء الاصطناعي.",
            "he": "קידום אורגני במנועי החיפוש של גוגל ובמנועי ה-AI.",
        },
        "category": _MARKETING, "billing_cycle": "monthly",
        "price_min": 1800, "price_max": None, "unit": None, "sort_order": 90,
    },
    {
        "name": {"ar": "إدارة صفحات السوشيال ميديا", "he": "ניהול דפי הסושיאל מדיה"},
        "description": {
            "ar": "4–5 بوستات شهرياً للحفاظ على صفحات حيّة بعد الإطلاق.",
            "he": "4–5 פוסטים חודשיים לשמירה על דפים חיים אחרי ההשקה.",
        },
        "category": _MARKETING, "billing_cycle": "monthly",
        "price_min": 800, "price_max": None, "unit": None, "sort_order": 100,
    },
    {
        "name": {"ar": "يوم تصوير — صاحب المصلحة يتحدث", "he": "יום צילום — בעל העסק מדבר"},
        "description": {
            "ar": "يوم تصوير لإنتاج حتى 10 فيديوهات تتكلم عن الخدمات بأسلوب حاجة وحل، مع مونتاج احترافي.",
            "he": "יום צילום להפקת עד 10 סרטונים על השירותים בשיטת צורך ופתרון, כולל עריכה מקצועית.",
        },
        "category": _CONTENT, "billing_cycle": "one_time",
        "price_min": 5500, "price_max": None,
        "unit": {"ar": "يوم تصوير (حتى 10 فيديوهات)", "he": "יום צילום (עד 10 סרטונים)"}, "sort_order": 110,
    },
    {
        "name": {"ar": "يوم تصوير — مع مقدّم من طرفنا", "he": "יום צילום — עם פרזנטור מטעמנו"},
        "description": {
            "ar": "نفس يوم التصوير مع مقدّم محترف من طرفنا يتحدث باسم العلامة.",
            "he": "אותו יום צילום עם פרזנטור מקצועי מטעמנו שמדבר בשם המותג.",
        },
        "category": _CONTENT, "billing_cycle": "one_time",
        "price_min": 8500, "price_max": None,
        "unit": {"ar": "يوم تصوير (حتى 10 فيديوهات)", "he": "יום צילום (עד 10 סרטונים)"}, "sort_order": 120,
    },
    {
        "name": {"ar": "باقة شهرية شاملة", "he": "חבילה חודשית כוללת"},
        "description": {
            "ar": "إدارة السوشيال + ترويج عضوي SEO/GEO + إدارة الحملات + جرافيكس ومونتاج فيديو — بسعر باقة.",
            "he": "ניהול סושיאל + קידום אורגני SEO/GEO + ניהול קמפיינים + גרפיקות ועריכת סרטונים — במחיר חבילה.",
        },
        "category": _BUNDLES, "billing_cycle": "monthly",
        "price_min": 4000, "price_max": None, "unit": None, "sort_order": 130,
    },
]


async def seed_service_items(db: AsyncSession) -> int:
    existing = await db.scalar(select(func.count(ServiceItem.id)))
    if existing:
        return 0
    for payload in SEED_ITEMS:
        db.add(ServiceItem(is_active=True, **payload))
    await db.commit()
    log.info("Seeded %d service catalog items", len(SEED_ITEMS))
    return len(SEED_ITEMS)
