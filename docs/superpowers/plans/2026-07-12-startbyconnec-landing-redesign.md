# startbyconnec Landing Redesign + First-Visit Welcome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `/startbyconnec` public landing page into a modern, mobile-first page, and evolve the app-wide first-visit overlay into a two-step welcome (language → theme).

**Architecture:** All changes are in the `web/` Next.js app (client components only, no backend changes). The existing `FirstTimeLanguagePicker` component is rewritten in place to add a theme step; the funnel landing page and layout are restyled using existing semantic tokens (`bg-card`, `text-muted-foreground`, …) plus the brand CSS variables (`--brand-accent: #2f80ff`, `--brand-accent-strong: #1258d6`, `--brand-mint: #18b89d`) defined in `web/src/app/globals.css`.

**Tech Stack:** Next.js (custom build — see constraints), Tailwind v4, lucide-react, existing i18n (`useT`/`useLanguage` from `@/lib/i18n/LanguageContext`), existing `ThemeContext`.

**Spec:** `docs/superpowers/specs/2026-07-12-startbyconnec-landing-redesign-design.md`

## Global Constraints

- `web/` is a **separate git repo** (remote `co-suite-web`). Commit inside `web/`, never `git add -A` there. After all web commits: bump the gitlink in the outer repo and push BOTH repos.
- `web/AGENTS.md`: this is NOT the Next.js you know — before writing code, check the relevant guide in `web/node_modules/next/dist/docs/` if you deviate from patterns already present in the files you're editing. All code below follows existing in-repo patterns (client components, `next/link`, `usePathname`), which are known-good.
- No test framework exists in `web/`. Verification per task = `npx tsc --noEmit` + `npm run lint`, plus browser QA (Task 5).
- localStorage keys are fixed: language flag `co_suite_lang_set` (existing), theme `co_suite_theme` (existing, written by `ThemeContext.setTheme`). Do not invent new keys.
- The welcome overlay must keep skipping `pathname === "/"`.
- All user-facing copy goes through i18n keys. New keys must be added to **all 8 languages** (en, ar, he, ru, fr, es, tr, zh) for parity with existing `sbc.*` keys.
- RTL correctness: use logical utilities (`text-start`, `gap`, `rtl:-scale-x-100` for arrows). Never `ml-*/mr-*` for new code.
- Both themes must look right: use semantic tokens for surfaces/text; brand hex vars only for accents.

---

### Task 1: i18n keys (theme step + landing sections)

**Files:**
- Modify: `web/src/lib/i18n/translations.ts`

**Interfaces:**
- Produces: translation keys `themePicker.title|subtitle|light|dark|confirm`, `sbc.hero.badge|titleMain|titleAccent|trust`, `sbc.how.title`, `sbc.how.step{1..4}.title|body`, `sbc.cta.title|body` — consumed by Tasks 2 and 4 via `t("<key>")`.

- [ ] **Step 1: Add the new keys to every language block**

For each language, find the line `"sbc.hero.title":` (it exists in all 8 blocks — en ~403, ar ~891, he ~1304, fr ~1471, es ~1638, tr ~1805, ru ~1884, zh ~1963) and insert the language's block below, right after the existing `"sbc.hero.cta"` line. Add the `themePicker.*` keys in the same edit (anywhere adjacent within the same language object; next to `langPicker.*` where that exists).

**en:**
```ts
    "themePicker.title": "Choose your look",
    "themePicker.subtitle": "Light or dark — you can change it anytime",
    "themePicker.light": "Light",
    "themePicker.dark": "Dark",
    "themePicker.confirm": "Let's go",
    "sbc.hero.badge": "100% free",
    "sbc.hero.titleMain": "A complete marketing plan for your business —",
    "sbc.hero.titleAccent": "free",
    "sbc.hero.trust": "No credit card · ready in minutes",
    "sbc.how.title": "How it works",
    "sbc.how.step1.title": "Sign up",
    "sbc.how.step1.body": "Full name, phone, and email — that's it.",
    "sbc.how.step2.title": "Build your brand profile",
    "sbc.how.step2.body": "We research your business and build the profile automatically.",
    "sbc.how.step3.title": "Get your plans",
    "sbc.how.step3.body": "A marketing plan and a work plan, ready to execute.",
    "sbc.how.step4.title": "Custom quote",
    "sbc.how.step4.body": "Pick services and get a clear price proposal.",
    "sbc.cta.title": "Ready to grow your business?",
    "sbc.cta.body": "It takes a few minutes and costs nothing.",
```

**ar:**
```ts
    "themePicker.title": "اختر المظهر",
    "themePicker.subtitle": "فاتح أو داكن — يمكنك تغييره في أي وقت",
    "themePicker.light": "فاتح",
    "themePicker.dark": "داكن",
    "themePicker.confirm": "لننطلق",
    "sbc.hero.badge": "مجاني بالكامل",
    "sbc.hero.titleMain": "خطة تسويق كاملة لمصلحتك —",
    "sbc.hero.titleAccent": "مجاناً",
    "sbc.hero.trust": "بدون بطاقة ائتمان · جاهزة خلال دقائق",
    "sbc.how.title": "كيف يعمل؟",
    "sbc.how.step1.title": "سجّل",
    "sbc.how.step1.body": "الاسم، الهاتف والبريد — هذا كل شيء.",
    "sbc.how.step2.title": "أنشئ ملف علامتك",
    "sbc.how.step2.body": "نبحث عن مصلحتك ونبني الملف تلقائياً.",
    "sbc.how.step3.title": "استلم خططك",
    "sbc.how.step3.body": "خطة تسويقية وخطة عمل جاهزتان للتنفيذ.",
    "sbc.how.step4.title": "عرض أسعار مخصص",
    "sbc.how.step4.body": "اختر الخدمات واحصل على عرض سعر واضح.",
    "sbc.cta.title": "جاهز تكبّر مصلحتك؟",
    "sbc.cta.body": "الأمر يستغرق دقائق معدودة ولا يكلّف شيئاً.",
```

**he:**
```ts
    "themePicker.title": "בחרו מראה",
    "themePicker.subtitle": "בהיר או כהה — אפשר לשנות בכל עת",
    "themePicker.light": "בהיר",
    "themePicker.dark": "כהה",
    "themePicker.confirm": "יאללה מתחילים",
    "sbc.hero.badge": "חינם לגמרי",
    "sbc.hero.titleMain": "תוכנית שיווק מלאה לעסק שלך —",
    "sbc.hero.titleAccent": "בחינם",
    "sbc.hero.trust": "בלי כרטיס אשראי · מוכן תוך דקות",
    "sbc.how.title": "איך זה עובד?",
    "sbc.how.step1.title": "הרשמה",
    "sbc.how.step1.body": "שם מלא, טלפון ואימייל — זה הכל.",
    "sbc.how.step2.title": "בניית פרופיל המותג",
    "sbc.how.step2.body": "אנחנו חוקרים את העסק ובונים את הפרופיל אוטומטית.",
    "sbc.how.step3.title": "קבלת התוכניות",
    "sbc.how.step3.body": "תוכנית שיווק ותוכנית עבודה מוכנות לביצוע.",
    "sbc.how.step4.title": "הצעת מחיר מותאמת",
    "sbc.how.step4.body": "בחרו שירותים וקבלו הצעת מחיר ברורה.",
    "sbc.cta.title": "מוכנים להצמיח את העסק?",
    "sbc.cta.body": "זה לוקח כמה דקות ולא עולה כלום.",
```

**ru:**
```ts
    "themePicker.title": "Выберите оформление",
    "themePicker.subtitle": "Светлая или тёмная — можно изменить в любой момент",
    "themePicker.light": "Светлая",
    "themePicker.dark": "Тёмная",
    "themePicker.confirm": "Начать",
    "sbc.hero.badge": "Совершенно бесплатно",
    "sbc.hero.titleMain": "Полный маркетинговый план для вашего бизнеса —",
    "sbc.hero.titleAccent": "бесплатно",
    "sbc.hero.trust": "Без карты · готово за минуты",
    "sbc.how.title": "Как это работает",
    "sbc.how.step1.title": "Регистрация",
    "sbc.how.step1.body": "Имя, телефон и почта — это всё.",
    "sbc.how.step2.title": "Профиль бренда",
    "sbc.how.step2.body": "Мы изучаем ваш бизнес и строим профиль автоматически.",
    "sbc.how.step3.title": "Ваши планы",
    "sbc.how.step3.body": "Маркетинговый и рабочий план, готовые к запуску.",
    "sbc.how.step4.title": "Индивидуальное предложение",
    "sbc.how.step4.body": "Выберите услуги и получите понятную цену.",
    "sbc.cta.title": "Готовы развивать бизнес?",
    "sbc.cta.body": "Это займёт пару минут и ничего не стоит.",
```

**fr:**
```ts
    "themePicker.title": "Choisissez votre thème",
    "themePicker.subtitle": "Clair ou sombre — modifiable à tout moment",
    "themePicker.light": "Clair",
    "themePicker.dark": "Sombre",
    "themePicker.confirm": "C'est parti",
    "sbc.hero.badge": "100 % gratuit",
    "sbc.hero.titleMain": "Un plan marketing complet pour votre entreprise —",
    "sbc.hero.titleAccent": "gratuit",
    "sbc.hero.trust": "Sans carte bancaire · prêt en quelques minutes",
    "sbc.how.title": "Comment ça marche",
    "sbc.how.step1.title": "Inscription",
    "sbc.how.step1.body": "Nom, téléphone et e-mail — c'est tout.",
    "sbc.how.step2.title": "Profil de marque",
    "sbc.how.step2.body": "Nous étudions votre entreprise et créons le profil automatiquement.",
    "sbc.how.step3.title": "Vos plans",
    "sbc.how.step3.body": "Un plan marketing et un plan de travail prêts à exécuter.",
    "sbc.how.step4.title": "Devis personnalisé",
    "sbc.how.step4.body": "Choisissez des services et recevez un prix clair.",
    "sbc.cta.title": "Prêt à développer votre entreprise ?",
    "sbc.cta.body": "Quelques minutes suffisent, sans aucun frais.",
```

**es:**
```ts
    "themePicker.title": "Elige tu tema",
    "themePicker.subtitle": "Claro u oscuro — puedes cambiarlo cuando quieras",
    "themePicker.light": "Claro",
    "themePicker.dark": "Oscuro",
    "themePicker.confirm": "Empezar",
    "sbc.hero.badge": "100 % gratis",
    "sbc.hero.titleMain": "Un plan de marketing completo para tu negocio —",
    "sbc.hero.titleAccent": "gratis",
    "sbc.hero.trust": "Sin tarjeta · listo en minutos",
    "sbc.how.title": "Cómo funciona",
    "sbc.how.step1.title": "Regístrate",
    "sbc.how.step1.body": "Nombre, teléfono y correo — eso es todo.",
    "sbc.how.step2.title": "Perfil de marca",
    "sbc.how.step2.body": "Investigamos tu negocio y creamos el perfil automáticamente.",
    "sbc.how.step3.title": "Tus planes",
    "sbc.how.step3.body": "Un plan de marketing y un plan de trabajo listos para ejecutar.",
    "sbc.how.step4.title": "Cotización personalizada",
    "sbc.how.step4.body": "Elige servicios y recibe un precio claro.",
    "sbc.cta.title": "¿Listo para hacer crecer tu negocio?",
    "sbc.cta.body": "Toma unos minutos y no cuesta nada.",
```

**tr:**
```ts
    "themePicker.title": "Görünümünü seç",
    "themePicker.subtitle": "Açık veya koyu — istediğin zaman değiştirebilirsin",
    "themePicker.light": "Açık",
    "themePicker.dark": "Koyu",
    "themePicker.confirm": "Başlayalım",
    "sbc.hero.badge": "Tamamen ücretsiz",
    "sbc.hero.titleMain": "İşletmeniz için eksiksiz bir pazarlama planı —",
    "sbc.hero.titleAccent": "ücretsiz",
    "sbc.hero.trust": "Kart gerekmez · dakikalar içinde hazır",
    "sbc.how.title": "Nasıl çalışır?",
    "sbc.how.step1.title": "Kaydol",
    "sbc.how.step1.body": "Ad, telefon ve e-posta — hepsi bu.",
    "sbc.how.step2.title": "Marka profilini oluştur",
    "sbc.how.step2.body": "İşletmenizi araştırır ve profili otomatik oluştururuz.",
    "sbc.how.step3.title": "Planlarını al",
    "sbc.how.step3.body": "Uygulamaya hazır bir pazarlama planı ve iş planı.",
    "sbc.how.step4.title": "Özel teklif",
    "sbc.how.step4.body": "Hizmetleri seç, net bir fiyat teklifi al.",
    "sbc.cta.title": "İşini büyütmeye hazır mısın?",
    "sbc.cta.body": "Sadece birkaç dakika sürer ve hiçbir ücret ödemezsin.",
```

**zh:**
```ts
    "themePicker.title": "选择外观",
    "themePicker.subtitle": "浅色或深色 — 随时可以更改",
    "themePicker.light": "浅色",
    "themePicker.dark": "深色",
    "themePicker.confirm": "开始",
    "sbc.hero.badge": "完全免费",
    "sbc.hero.titleMain": "为您的业务量身定制的完整营销计划 —",
    "sbc.hero.titleAccent": "免费",
    "sbc.hero.trust": "无需信用卡 · 几分钟即可完成",
    "sbc.how.title": "如何运作",
    "sbc.how.step1.title": "注册",
    "sbc.how.step1.body": "姓名、电话和邮箱 — 仅此而已。",
    "sbc.how.step2.title": "创建品牌资料",
    "sbc.how.step2.body": "我们研究您的业务并自动生成资料。",
    "sbc.how.step3.title": "获取计划",
    "sbc.how.step3.body": "可立即执行的营销计划和工作计划。",
    "sbc.how.step4.title": "定制报价",
    "sbc.how.step4.body": "选择服务，获得清晰的价格方案。",
    "sbc.cta.title": "准备好发展您的业务了吗？",
    "sbc.cta.body": "只需几分钟，完全免费。",
```

- [ ] **Step 2: Verify types and lint**

Run (in `web/`): `npx tsc --noEmit && npm run lint`
Expected: no errors (pre-existing warnings unrelated to translations.ts are acceptable).

- [ ] **Step 3: Commit (inside web/)**

```bash
cd web
git add src/lib/i18n/translations.ts
git commit -m "feat(i18n): keys for theme picker step + startbyconnec landing sections"
```

---

### Task 2: Two-step welcome overlay (language → theme)

**Files:**
- Modify: `web/src/components/FirstTimeLanguagePicker.tsx` (full rewrite, name kept)

**Interfaces:**
- Consumes: `themePicker.*` keys from Task 1; `useTheme()` from `@/lib/theme/ThemeContext` (`theme: "light"|"dark"`, `setTheme(mode)` — applies class on `<html>` AND persists to `co_suite_theme`); `useLanguage()`; `BrandMark`.
- Produces: same exported component name `FirstTimeLanguagePicker` (root layout import unchanged).

Behavior contract:
- Skip when `pathname === "/"`.
- No `co_suite_lang_set` → show step "lang" then step "theme" (2-dot indicator).
- `co_suite_lang_set` present but no `co_suite_theme` in localStorage → show only step "theme" (no indicator).
- Both present → render nothing.
- Clicking a theme card calls `setTheme(mode)` → live preview of the whole page (and persists). The confirm button re-persists the current selection (`setTheme(theme)`) so the overlay never reappears even if the user never clicked a card, then closes.

- [ ] **Step 1: Rewrite the component**

Replace the entire file contents with:

```tsx
"use client";
import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Moon, Sun } from "lucide-react";
import { LANGUAGES, LangCode } from "@/lib/i18n/translations";
import { useLanguage } from "@/lib/i18n/LanguageContext";
import { ThemeMode, useTheme } from "@/lib/theme/ThemeContext";
import { BrandMark } from "@/components/BrandMark";

const PRIMARY_LANGUAGE_CODES: LangCode[] = ["en", "he", "ar"];

type Step = "lang" | "theme";

function ThemePreviewCard({
  mode,
  label,
  selected,
  onSelect,
}: {
  mode: ThemeMode;
  label: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const isDark = mode === "dark";
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`rounded-2xl border-2 p-2 text-start transition-all ${
        selected
          ? "border-[var(--brand-accent)] shadow-lg"
          : "border-border hover:border-muted-foreground/40"
      }`}
    >
      <div
        className={`overflow-hidden rounded-xl border ${
          isDark ? "border-zinc-700 bg-zinc-950" : "border-zinc-200 bg-white"
        }`}
      >
        <div
          className={`flex items-center gap-1.5 border-b px-2.5 py-2 ${
            isDark ? "border-zinc-800" : "border-zinc-100"
          }`}
        >
          <span className="h-2 w-2 rounded-full bg-[var(--brand-accent)]" />
          <span className={`h-1.5 w-9 rounded-full ${isDark ? "bg-zinc-700" : "bg-zinc-200"}`} />
        </div>
        <div className="space-y-1.5 p-2.5">
          <span className={`block h-2 w-3/4 rounded-full ${isDark ? "bg-zinc-600" : "bg-zinc-300"}`} />
          <span className={`block h-1.5 w-full rounded-full ${isDark ? "bg-zinc-800" : "bg-zinc-100"}`} />
          <span className={`block h-1.5 w-5/6 rounded-full ${isDark ? "bg-zinc-800" : "bg-zinc-100"}`} />
          <span className="mt-1 block h-3.5 w-1/2 rounded-md bg-[var(--brand-accent)]" />
        </div>
      </div>
      <span className="mt-2 flex items-center justify-center gap-1.5 text-sm font-semibold text-foreground">
        {isDark ? <Moon size={14} /> : <Sun size={14} />}
        {label}
      </span>
    </button>
  );
}

export function FirstTimeLanguagePicker() {
  const [step, setStep] = useState<Step | null>(null);
  const [twoSteps, setTwoSteps] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const { setLang, t } = useLanguage();
  const { theme, setTheme } = useTheme();
  const pathname = usePathname();

  useEffect(() => {
    if (pathname === "/" || step !== null) return;
    const langSet = localStorage.getItem("co_suite_lang_set");
    const themeSet = localStorage.getItem("co_suite_theme");
    if (!langSet) {
      setTwoSteps(true);
      setStep("lang");
    } else if (!themeSet) {
      setStep("theme");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function chooseLanguage(code: LangCode) {
    setLang(code);
    localStorage.setItem("co_suite_lang_set", "1");
    setStep("theme");
  }

  function confirmTheme() {
    setTheme(theme); // persist current selection even if untouched
    setStep(null);
  }

  if (!step) return null;

  const primaryLanguages = PRIMARY_LANGUAGE_CODES.map((code) =>
    LANGUAGES.find((l) => l.code === code)
  ).filter(Boolean) as typeof LANGUAGES;
  const moreLanguages = LANGUAGES.filter(
    (l) => !PRIMARY_LANGUAGE_CODES.includes(l.code as LangCode)
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-background/90 px-5 py-8 backdrop-blur-md">
      <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 shadow-2xl sm:p-8">
        <div className="mb-6 flex flex-col items-center gap-4">
          <BrandMark size="md" />
          {twoSteps && (
            <div className="flex items-center gap-1.5" aria-hidden>
              <span
                className={`h-1.5 rounded-full transition-all ${
                  step === "lang" ? "w-6 bg-[var(--brand-accent)]" : "w-1.5 bg-border"
                }`}
              />
              <span
                className={`h-1.5 rounded-full transition-all ${
                  step === "theme" ? "w-6 bg-[var(--brand-accent)]" : "w-1.5 bg-border"
                }`}
              />
            </div>
          )}
        </div>

        {step === "lang" ? (
          <>
            <div className="mb-6 space-y-1.5 text-center">
              <p className="text-xl font-bold text-foreground">How should we speak with you?</p>
              <p className="text-xl font-bold text-foreground" dir="rtl">
                איך תרצה שנדבר איתך?
              </p>
              <p className="text-xl font-bold text-foreground" dir="rtl">
                كيف تحب نحكي معك؟
              </p>
              <p className="pt-2 text-sm text-muted-foreground">{t("langPicker.subtitle")}</p>
            </div>

            <div className="grid gap-3">
              {primaryLanguages.map((l) => (
                <button
                  key={l.code}
                  onClick={() => chooseLanguage(l.code as LangCode)}
                  dir={l.dir}
                  className="rounded-xl border border-border bg-background px-5 py-4 text-base font-semibold text-foreground transition-colors hover:border-[var(--brand-accent)] hover:bg-accent focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                >
                  {l.label}
                </button>
              ))}
            </div>

            {showMore && (
              <div className="mt-4 grid grid-cols-2 gap-2">
                {moreLanguages.map((l) => (
                  <button
                    key={l.code}
                    onClick={() => chooseLanguage(l.code as LangCode)}
                    dir={l.dir}
                    className="rounded-xl border border-border bg-background px-4 py-3 text-sm font-medium text-muted-foreground transition-colors hover:border-[var(--brand-accent)] hover:bg-accent hover:text-foreground focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            )}

            <button
              type="button"
              onClick={() => setShowMore((v) => !v)}
              className="mx-auto mt-5 block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              {showMore ? t("langPicker.less") : t("langPicker.more")}
            </button>
          </>
        ) : (
          <>
            <div className="mb-6 space-y-1.5 text-center">
              <p className="text-xl font-bold text-foreground">{t("themePicker.title")}</p>
              <p className="text-sm text-muted-foreground">{t("themePicker.subtitle")}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <ThemePreviewCard
                mode="light"
                label={t("themePicker.light")}
                selected={theme === "light"}
                onSelect={() => setTheme("light")}
              />
              <ThemePreviewCard
                mode="dark"
                label={t("themePicker.dark")}
                selected={theme === "dark"}
                onSelect={() => setTheme("dark")}
              />
            </div>

            <button
              type="button"
              onClick={confirmTheme}
              className="mt-6 w-full rounded-xl bg-gradient-to-r from-[var(--brand-accent)] to-[var(--brand-accent-strong)] px-5 py-3.5 text-base font-bold text-white shadow-lg shadow-[#2f80ff]/25 transition-transform hover:scale-[1.01] active:scale-[0.99]"
            >
              {t("themePicker.confirm")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify types and lint**

Run (in `web/`): `npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit (inside web/)**

```bash
cd web
git add src/components/FirstTimeLanguagePicker.tsx
git commit -m "feat(welcome): two-step first-visit overlay — language then theme with live preview"
```

---

### Task 3: Funnel header — add ThemeSwitcher

**Files:**
- Modify: `web/src/app/startbyconnec/layout.tsx`

**Interfaces:**
- Consumes: `ThemeSwitcher` from `@/components/ThemeSwitcher` (prop `compact?: boolean`).

- [ ] **Step 1: Add the switcher to the header**

Replace the file contents with:

```tsx
"use client";
import { BrandMark } from "@/components/BrandMark";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

export default function StartByConnecLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-background text-foreground flex flex-col">
      <header className="border-b border-border">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <BrandMark size="sm" />
          <div className="flex items-center gap-1.5">
            <ThemeSwitcher compact />
            <LanguageSwitcher placement="bottom" />
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground">
        Connec × OneShare
      </footer>
    </div>
  );
}
```

- [ ] **Step 2: Verify types and lint**

Run (in `web/`): `npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit (inside web/)**

```bash
cd web
git add src/app/startbyconnec/layout.tsx
git commit -m "feat(sbc): theme switcher in funnel header"
```

---

### Task 4: Landing page redesign

**Files:**
- Modify: `web/src/app/startbyconnec/page.tsx` (full rewrite)

**Interfaces:**
- Consumes: i18n keys from Task 1 (`sbc.hero.badge|titleMain|titleAccent|trust`, existing `sbc.hero.subtitle|cta`, existing `sbc.benefit{1..3}.*`, `sbc.how.*`, `sbc.cta.*`); lucide-react icons; brand CSS vars.

- [ ] **Step 1: Rewrite the page**

Replace the file contents with:

```tsx
"use client";
import Link from "next/link";
import {
  ArrowRight,
  BadgePercent,
  CalendarCheck,
  ClipboardList,
  FileSearch,
  Palette,
  Receipt,
  Sparkles,
  UserPlus,
} from "lucide-react";
import { useT } from "@/lib/i18n/LanguageContext";

const BENEFITS = [
  { key: "benefit1", icon: Palette, chip: "bg-[#2f80ff]/10 text-[#2f80ff]" },
  { key: "benefit2", icon: CalendarCheck, chip: "bg-[#18b89d]/10 text-[#18b89d]" },
  { key: "benefit3", icon: Receipt, chip: "bg-amber-500/10 text-amber-600 dark:text-amber-400" },
] as const;

const STEPS = [
  { key: "step1", icon: UserPlus },
  { key: "step2", icon: FileSearch },
  { key: "step3", icon: ClipboardList },
  { key: "step4", icon: BadgePercent },
] as const;

function BigCta({ label }: { label: string }) {
  return (
    <Link
      href="/startbyconnec/register"
      className="inline-flex h-14 w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[var(--brand-accent)] to-[var(--brand-accent-strong)] px-8 text-lg font-bold text-white shadow-lg shadow-[#2f80ff]/25 transition-transform hover:scale-[1.02] active:scale-[0.98] sm:w-auto"
    >
      {label}
      <ArrowRight size={20} className="rtl:-scale-x-100" />
    </Link>
  );
}

export default function StartByConnecLanding() {
  const t = useT();
  return (
    <div className="mx-auto max-w-5xl space-y-16 px-4 py-12 md:space-y-24 md:py-20">
      <section className="space-y-6 text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#2f80ff]/20 bg-[#2f80ff]/10 px-3.5 py-1.5 text-sm font-semibold text-[var(--brand-accent)]">
          <Sparkles size={14} />
          {t("sbc.hero.badge")}
        </span>
        <h1 className="text-4xl font-extrabold leading-tight tracking-tight md:text-6xl">
          {t("sbc.hero.titleMain")}{" "}
          <span className="bg-gradient-to-r from-[var(--brand-accent)] to-[var(--brand-mint)] bg-clip-text text-transparent">
            {t("sbc.hero.titleAccent")}
          </span>
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-muted-foreground">{t("sbc.hero.subtitle")}</p>
        <div className="space-y-3 pt-2">
          <BigCta label={t("sbc.hero.cta")} />
          <p className="text-sm text-muted-foreground">{t("sbc.hero.trust")}</p>
        </div>
      </section>

      <section className="grid gap-4 text-start md:grid-cols-3">
        {BENEFITS.map(({ key, icon: Icon, chip }) => (
          <div
            key={key}
            className="rounded-2xl border border-border bg-card p-6 transition-all hover:-translate-y-0.5 hover:shadow-md"
          >
            <span className={`mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl ${chip}`}>
              <Icon size={22} />
            </span>
            <h3 className="mb-1.5 font-bold">{t(`sbc.${key}.title`)}</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">{t(`sbc.${key}.body`)}</p>
          </div>
        ))}
      </section>

      <section className="space-y-8">
        <h2 className="text-center text-2xl font-extrabold tracking-tight md:text-3xl">
          {t("sbc.how.title")}
        </h2>
        <ol className="grid gap-6 md:grid-cols-4">
          {STEPS.map(({ key, icon: Icon }, i) => (
            <li key={key} className="flex gap-4 text-start md:flex-col md:gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-accent)] to-[var(--brand-mint)] font-bold text-white shadow-md">
                {i + 1}
              </span>
              <div>
                <h3 className="mb-1 flex items-center gap-1.5 font-bold">
                  <Icon size={15} className="text-[var(--brand-accent)]" />
                  {t(`sbc.how.${key}.title`)}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t(`sbc.how.${key}.body`)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-3xl border border-border bg-gradient-to-br from-[#2f80ff]/10 via-transparent to-[#18b89d]/10 px-6 py-12 text-center md:py-16">
        <h2 className="mb-2 text-2xl font-extrabold tracking-tight md:text-3xl">{t("sbc.cta.title")}</h2>
        <p className="mb-6 text-muted-foreground">{t("sbc.cta.body")}</p>
        <BigCta label={t("sbc.hero.cta")} />
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Verify types and lint**

Run (in `web/`): `npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit (inside web/)**

```bash
cd web
git add src/app/startbyconnec/page.tsx
git commit -m "feat(sbc): modern landing — gradient hero, icon benefits, how-it-works, closing CTA"
```

---

### Task 5: Browser QA (mobile-first, both themes, RTL)

**Files:**
- Modify: whatever the QA findings require (visual fixes in the files above).

- [ ] **Step 1: Start the dev server and open `/startbyconnec`**

Use the Browser pane (`preview_start` with the web dev server from `.claude/launch.json`; add a `web` entry `{"runtimeExecutable": "npm", "runtimeArgs": ["run", "dev"], "port": 3000}` if missing). Navigate to `http://localhost:3000/startbyconnec`.

- [ ] **Step 2: Welcome overlay matrix**

In the browser console (`javascript_tool`), clear state and reload for each case:
1. `localStorage.removeItem("co_suite_lang_set"); localStorage.removeItem("co_suite_theme"); location.reload()` → both steps appear (2-dot indicator); pick العربية → theme step appears; click داكن → whole page flips dark live; confirm → overlay closes and never returns on reload.
2. `localStorage.setItem("co_suite_lang_set","1"); localStorage.removeItem("co_suite_theme"); location.reload()` → only theme step, no indicator; confirm without clicking a card → overlay closes AND `localStorage.getItem("co_suite_theme")` is set → no overlay on reload.
3. Both set → no overlay.

- [ ] **Step 3: Landing visual matrix**

- Viewports: mobile (375×812) and desktop (1280×800) via `resize_window`.
- Themes: light + dark (use the new header ThemeSwitcher).
- Languages: ar (RTL), he (RTL), en (LTR) via the header LanguageSwitcher — check the CTA arrow flips in RTL, `text-start` alignment, no horizontal overflow on mobile.
- Check console for errors (`read_console_messages`).

- [ ] **Step 4: Fix what QA finds, re-check, commit fixes (inside web/)**

```bash
cd web
git add <changed files>
git commit -m "fix(sbc): QA polish — <what was fixed>"
```

- [ ] **Step 5: Screenshot proof**

Take mobile + desktop screenshots (light ar, dark ar at minimum) and share them with the user.

---

### Task 6: Ship — gitlink bump + push both repos

- [ ] **Step 1: Push the web repo**

```bash
cd web
git push
```

- [ ] **Step 2: Bump the gitlink in the outer repo and push**

```bash
cd ..
git add web
git commit -m "chore(web): bump gitlink — startbyconnec landing redesign + two-step welcome"
git push
```

Expected: both pushes succeed; Railway picks up the deploy.
