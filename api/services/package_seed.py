"""Ready-made package ladder for the startbyconnec pricing proposal.

Built from the owner's pricing rules. Every price INCLUDES VAT, and nothing here
is a commitment: the proposal always carries the "prices may change by business
type / needs manual approval" note (financial, political and similar verticals
take more effort and are priced separately).

Derived tiers use the owner's add-on rules on top of a base tier:
  business shoot / month +750 · person on camera / month +400 ·
  social media management (2 posts a week + a story every 2 days) +750 ·
  Google campaigns +900 · SEO+GEO for shops/sites +700 ·
  AI video +150 per 30s · doubling social management repeats its price +10% total

`audience` decides who sees a tier: "very_small" is only surfaced to obviously
tiny businesses, "all" is the general ladder, and the rest target a vertical.
Admins can edit or add packages freely afterwards — this is only the starting set.
"""
from typing import Any

# Reusable bilingual feature bullets.
F_META = {"ar": "إدارة الحملات على ميتا", "he": "ניהול קמפיינים במטא"}
F_META_MSG = {"ar": "حملة رسائل على ميتا", "he": "קמפיין הודעות במטא"}
F_ALL_SOCIAL = {
    "ar": "إدارة الحملات على جميع قنوات السوشيال ميديا شامل التيكتوك",
    "he": "ניהול קמפיינים בכל ערוצי הסושיאל כולל טיקטוק",
}
F_EDIT = {"ar": "تحرير ومونتاج الفيديوهات — غير شامل التصوير", "he": "עריכה ומונטאז' וידאו — לא כולל צילום"}
F_DESIGN = {"ar": "تصاميم وبانرات للسوشيال ميديا", "he": "עיצובים ובאנרים לרשתות"}
F_CAP8 = {"ar": "مجموع التصاميم والفيديوهات حتى 8 شهرياً", "he": "סה\"כ עיצובים וסרטונים עד 8 בחודש"}
F_LANDING = {"ar": "صفحات هبوط عند الحاجة", "he": "דפי נחיתה לפי הצורך"}
F_UGC = {
    "ar": "فيديو UGC — شخص يتحدث للكاميرا (مرة كل شهرين شامل المونتاج)",
    "he": "וידאו UGC — אדם מדבר למצלמה (אחת לחודשיים כולל עריכה)",
}
F_SHOOT_2M = {
    "ar": "تصوير المصلحة مرة كل شهرين — بكاميرا آيفون (كافي ومفضل للسوشيال)",
    "he": "צילום העסק אחת לחודשיים — במצלמת אייפון (מספיק ומועדף לסושיאל)",
}
F_SHOOT_1M = {"ar": "تصوير المصلحة كل شهر", "he": "צילום העסק כל חודש"}
F_SOCIAL_MGMT = {
    "ar": "إدارة السوشيال ميديا — بوستين كل أسبوع + ستوري كل يومين (النشر علينا)",
    "he": "ניהול סושיאל — 2 פוסטים בשבוע + סטורי כל יומיים (הפרסום עלינו)",
}
F_GOOGLE = {"ar": "إدارة الحملات في جوجل", "he": "ניהול קמפיינים בגוגל"}
F_SEO = {"ar": "تحسين محركات البحث SEO و GEO", "he": "אופטימיזציה למנועי חיפוש SEO ו-GEO"}
F_UGC_1M = {"ar": "فيديو UGC — شخص يتحدث للكاميرا كل شهر", "he": "וידאו UGC — אדם מדבר למצלמה כל חודש"}

_SMALL_NOTE_AR = "مناسبة فقط للميزانيات الصغيرة جداً — نقطة بداية للدخول."
_SMALL_NOTE_HE = "מתאימה רק לתקציבים קטנים מאוד — נקודת התחלה."


def _pkg(
    sort: int,
    price: float,
    ar: str,
    he: str,
    desc_ar: str,
    desc_he: str,
    features: list[dict[str, str]],
    audience: str = "all",
) -> dict[str, Any]:
    return {
        "name": {"ar": ar, "he": he},
        "description": {"ar": desc_ar, "he": desc_he},
        "billing_cycle": "monthly",
        "price_min": price,
        "price_max": None,
        "features": features,
        "audience": audience,
        "sort_order": sort,
        "is_active": True,
    }


# The ladder, cheapest → highest. Each business is shown 3-7 of these.
PACKAGE_SEED: list[dict[str, Any]] = [
    _pkg(
        10, 900,
        "البداية — حملة رسائل", "התחלה — קמפיין הודעות",
        f"إدارة حملة ميتا أساسية (حملة رسائل) لجلب استفسارات مباشرة. {_SMALL_NOTE_AR}",
        f"ניהול קמפיין מטא בסיסי (קמפיין הודעות) להבאת פניות ישירות. {_SMALL_NOTE_HE}",
        [F_META_MSG],
        audience="very_small",
    ),
    _pkg(
        20, 1700,
        "الأساسية", "בסיסית",
        "إدارة حملات ميتا مع مونتاج وتصاميم شهرية — بداية عملية لأي مصلحة.",
        "ניהול קמפיינים במטא עם עריכה ועיצובים חודשיים — התחלה מעשית לכל עסק.",
        [F_META, F_EDIT, F_DESIGN, F_CAP8],
    ),
    _pkg(
        30, 2200,
        "النمو", "צמיחה",
        "كل ما في الأساسية، مع صفحات هبوط عند الحاجة وفيديو UGC كل شهرين.",
        "כל מה שבבסיסית, בתוספת דפי נחיתה לפי הצורך ווידאו UGC אחת לחודשיים.",
        [F_META, F_EDIT, F_DESIGN, F_LANDING, F_UGC],
    ),
    _pkg(
        # Shops that live on search demand, not social (e.g. أبناء الشريف):
        # the site + Google Ads carry the whole funnel.
        35, 2350,
        "المتجر بدون سوشيال", "החנות ללא סושיאל",
        "إدارة الموقع مع SEO و GEO، وإدارة حملات شوبينج وغيرها على جوجل أدز — بدون سوشيال ميديا.",
        "ניהול האתר עם SEO ו-GEO, וניהול קמפייני שופינג ואחרים בגוגל אדס — ללא סושיאל.",
        [
            {"ar": "إدارة الموقع مع تحسين محركات البحث SEO و GEO", "he": "ניהול האתר עם SEO ו-GEO"},
            {"ar": "إدارة حملات شوبينج وغيرها على جوجل أدز", "he": "ניהול קמפייני שופינג ואחרים בגוגל אדס"},
        ],
        audience="retail_web",
    ),
    _pkg(
        40, 2700,
        "النمو + تصوير", "צמיחה + צילום",
        "باقة النمو مع تصوير المصلحة مرة كل شهرين — محتوى حقيقي من مكانك.",
        "חבילת הצמיחה עם צילום העסק אחת לחודשיים — תוכן אמיתי מהמקום שלך.",
        [F_META, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M],
        audience="local_service",
    ),
    _pkg(
        50, 2700,
        "متعددة القنوات", "רב-ערוצית",
        "إدارة الحملات على جميع قنوات السوشيال شامل التيكتوك، مع صفحات هبوط و UGC.",
        "ניהול קמפיינים בכל ערוצי הסושיאל כולל טיקטוק, עם דפי נחיתה ו-UGC.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC],
    ),
    _pkg(
        60, 3000,
        "متعددة القنوات + تصوير", "רב-ערוצית + צילום",
        "كل القنوات شامل التيكتوك، مع تصوير المصلحة كل شهرين وفيديو UGC.",
        "כל הערוצים כולל טיקטוק, עם צילום העסק אחת לחודשיים ווידאו UGC.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M],
    ),
    # ── derived from the add-on rules ────────────────────────────────────────
    _pkg(
        70, 3700,
        "المتاجر والمواقع", "חנויות ואתרים",
        "لكل القنوات مع SEO و GEO — للمتاجر والمواقع التي تبيع أونلاين وتحتاج ظهور بالبحث.",
        "כל הערוצים עם SEO ו-GEO — לחנויות ואתרים שמוכרים אונליין וזקוקים לנראות בחיפוש.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M, F_SEO],
        audience="retail_web",
    ),
    _pkg(
        80, 3750,
        "الحضور الكامل", "נוכחות מלאה",
        "كل القنوات مع إدارة السوشيال ميديا — بوستين أسبوعياً وستوري كل يومين، النشر علينا.",
        "כל הערוצים עם ניהול סושיאל — 2 פוסטים בשבוע וסטורי כל יומיים, הפרסום עלינו.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M, F_SOCIAL_MGMT],
    ),
    _pkg(
        90, 3900,
        "ميتا + جوجل", "מטא + גוגל",
        "كل قنوات السوشيال مع إدارة حملات جوجل — للمصالح التي تعتمد على الطلب بالبحث.",
        "כל ערוצי הסושיאל עם ניהול קמפיינים בגוגל — לעסקים שנשענים על ביקוש בחיפוש.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M, F_GOOGLE],
    ),
    _pkg(
        100, 4500,
        "الحضور الكامل + تصوير شهري", "נוכחות מלאה + צילום חודשי",
        "إدارة سوشيال كاملة مع تصوير المصلحة كل شهر — لمصلحة تنتج محتوى باستمرار.",
        "ניהול סושיאל מלא עם צילום העסק כל חודש — לעסק שמייצר תוכן באופן שוטף.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_1M, F_SOCIAL_MGMT],
    ),
    _pkg(
        110, 5350,
        "الأداء الشامل", "ביצועים מלאים",
        "كل القنوات مع جوجل و SEO/GEO وإدارة سوشيال كاملة — أقصى تغطية للطلب والظهور.",
        "כל הערוצים עם גוגל, SEO/GEO וניהול סושיאל מלא — הכיסוי המקסימלי לביקוש ולנראות.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC, F_SHOOT_2M, F_SOCIAL_MGMT, F_GOOGLE, F_SEO],
        audience="retail_web",
    ),
    _pkg(
        120, 6050,
        "المتقدمة", "מתקדמת",
        "التغطية الكاملة مع تصوير شهري وشخص أمام الكاميرا كل شهر — لمصلحة تبني علامة قوية.",
        "כיסוי מלא עם צילום חודשי ואדם מול המצלמה כל חודש — לעסק שבונה מותג חזק.",
        [F_ALL_SOCIAL, F_EDIT, F_DESIGN, F_LANDING, F_UGC_1M, F_SHOOT_1M, F_SOCIAL_MGMT, F_GOOGLE, F_SEO],
    ),
]


async def seed_packages(db, *, overwrite: bool = False) -> dict[str, int]:
    """Insert the ready-made ladder. Existing packages are matched by Arabic name.

    Idempotent: re-running updates prices/features of seeded rows (when
    ``overwrite``) and never duplicates them. Admin-created packages are
    untouched.
    """
    from sqlalchemy import select

    from ..models.services_catalog import Package

    existing = (await db.execute(select(Package))).scalars().all()
    by_name = {str((p.name or {}).get("ar") or "").strip(): p for p in existing}
    created = updated = 0
    for spec in PACKAGE_SEED:
        current = by_name.get(spec["name"]["ar"])
        if current is None:
            db.add(Package(**spec))
            created += 1
        elif overwrite:
            for key, value in spec.items():
                setattr(current, key, value)
            updated += 1
    await db.commit()
    return {"created": created, "updated": updated, "total": len(PACKAGE_SEED)}
