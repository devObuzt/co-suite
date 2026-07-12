# startbyconnec landing redesign + first-visit welcome (language + theme) — design

Date: 2026-07-12
Status: approved

Two pieces, one release:

1. **First-visit welcome overlay (app-wide)** — evolve the existing
   `FirstTimeLanguagePicker` into a two-step welcome: pick language, then pick
   theme (light/dark) with live preview.
2. **`/startbyconnec` landing redesign** — a full modern landing page:
   gradient hero with a big clear CTA, icon benefit cards, "how it works"
   steps, closing CTA. Mobile-first, both themes, ar/he/en.

Decisions taken with the owner:

- The welcome overlay is **app-wide** (extends the existing picker), not
  funnel-specific — avoids two competing overlays.
- Landing gets the **full modern treatment** (not a light touch-up).
- Other funnel pages (register/services/request) are a later round.

---

## Part 1 — welcome overlay (`FirstTimeLanguagePicker` → two steps)

File: `web/src/components/FirstTimeLanguagePicker.tsx` (name kept; it stays
mounted where it is today, and keeps skipping `pathname === "/"`).

### Step 1 — language

- Same logic as today: primary en/he/ar + "more languages" expander.
- New look: centered card, OneShare `BrandMark` on top, 2-dot step
  indicator, large touch-friendly language buttons (native labels, correct
  `dir` per row).

### Step 2 — theme

- Two preview cards side by side: **فاتح ☀️ / داكن 🌙**, each rendering a
  mini UI preview in that theme's colors.
- Clicking a card applies the theme **live immediately** (via
  `useTheme().setTheme`) so the whole screen previews it; a confirm button
  closes the overlay.

### Show/skip logic

- No `co_suite_lang_set` in localStorage → show both steps.
- `co_suite_lang_set` present but no `co_suite_theme` → show only the theme
  step, once. (Existing users get to pick a theme without re-picking a
  language.)
- Both present → never shows.
- Language choice writes `co_suite_lang_set` (existing key); theme choice is
  persisted by `ThemeContext` under `co_suite_theme` (existing key).

---

## Part 2 — `/startbyconnec` landing redesign

Files: `web/src/app/startbyconnec/page.tsx`, `layout.tsx`; new i18n keys in
`web/src/lib/i18n/translations.ts` (ar/he/en).

### Header (funnel layout)

- Add `ThemeSwitcher` (compact) next to the existing `LanguageSwitcher`.

### Hero

- Small colored pill badge ("مجاناً بالكامل ✨").
- Large headline with one gradient word (brand blue `#2f80ff` → mint
  `#18b89d`), subtitle.
- **Big, obvious "ابدأ الآن" CTA** — full-width on mobile, arrow icon
  (RTL-aware), links to `/startbyconnec/register`.
- Trust line under the button ("بدون بطاقة ائتمان · خلال دقائق").

### Benefit cards (3)

- Existing three benefits, each with a lucide icon inside a colored chip
  (blue / mint / amber), soft border + hover lift.

### How it works (4 steps)

- Numbered steps matching the real funnel: سجّل ← ملف علامتك ← الخطط
  التسويقية ← عرض الأسعار.
- Vertical list on mobile, horizontal row with a connector line on desktop.

### Closing CTA

- Section with a subtle gradient background and a second "ابدأ الآن" button.

### Cross-cutting

- All copy via new i18n keys (ar/he/en), RTL-aware (`text-start`,
  logical margins, flipped arrow).
- Works in both light and dark themes (semantic tokens + brand accents).
- Mobile-first: `min-h-dvh`, large touch targets, grids collapse to one
  column.

---

## Testing

- Browser QA on the dev server: mobile (375px) + desktop viewports, light +
  dark themes, ar + he (RTL) + en (LTR).
- Verify welcome overlay: fresh visitor (both steps), lang-set-only visitor
  (theme step only), returning visitor (nothing).
- No backend changes; no pytest impact.

## Delivery

- `web/` is a separate git repo — commit inside `web/`, then bump the
  gitlink in the outer repo; push both.

## Out of scope

- Redesign of the other funnel pages (register/services/request/done) —
  next round after the landing look is approved.
- Root `/` page behavior (overlay keeps skipping it).
