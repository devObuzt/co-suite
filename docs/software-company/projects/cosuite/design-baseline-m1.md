# co-Suite M1 UX / Design Baseline Review

Date: 2026-06-07  
Owner: Design Agent  
Status: ready_for_review  
Milestone: M1 - Production Stabilization  

## Review Inputs

- `docs/software-company/projects/cosuite/product-acceptance-m1.md`
- `docs/software-company/projects/cosuite/milestone-01-production-stabilization.md`
- `docs/product/co-suite-product-manager-brief.md`
- Relevant frontend surfaces under `web/src/app`, `web/src/components`, and `web/src/lib/i18n`

## Baseline Position

M1 should stabilize the current product so a real customer can complete the core path without getting lost, blocked, or silently waiting:

1. Sign up or log in.
2. Create or open a Suite.
3. Complete business/brand onboarding with manual fallback.
4. Reach Connections, Brand/Profile, Create & Generate, Content Review, Product Bulk, and Analytics from the Suite.
5. Generate content with visible queued/running/failed/completed states.
6. Review, edit, approve, reject with feedback, regenerate, copy/download, and understand media failures.

This is not the time for a full visual redesign. The M1 design bar is clarity, recoverability, mobile reachability, native language behavior, and theme consistency.

## Must-Fix UX Blockers

### 1. Signup / Login

Current baseline:

- Signup has a two-step flow with account type selection.
- Login redirects to `/suites`; signup redirects to `/suite/new`.
- Auth forms use translated strings for English, Arabic, and Hebrew.
- Theme switching exists outside auth, but auth pages depend on global theme behavior.

M1 blockers:

- Error recovery is too raw when API/backend fails. Users may see backend exception text instead of a human explanation and next action.
- Signup stores account type in local storage, but M1 acceptance should confirm it is visible or useful later. If not used, the selection feels cosmetic.
- Login/signup need explicit QA for theme persistence across refresh and auth redirects.
- Email placeholders remain LTR, which is correct, but form container direction and button icon direction must be verified in Arabic/Hebrew.

M1 quick wins:

- Normalize auth errors into short messages: invalid credentials, email already used, backend unavailable, network unavailable.
- After signup, preserve selected account type through Suite creation or show it in the first Suite setup assumptions.
- Add QA checks for light/dark persistence before login, after login, after logout, and after signup redirect.

Later redesign:

- Add a first-run account home that offers standalone generation before Suite creation. This is product-important, but not required to stabilize the M1 Suite path.

### 2. Suite Navigation

Current baseline:

- Desktop dashboard layout has account-level links and a nested `SuiteNav` when inside `/suite/[id]`.
- Suite-level links include dashboard/home, connections, create, content, analytics, profile, market, calendar, campaigns, and product bulk.
- Mobile header only exposes account-level icons: Suites, New Suite, Settings, Theme, Logout.

M1 blockers:

- Mobile users inside a Suite cannot reach Suite-level screens from the header. This directly violates the M1 requirement that Connections, Create & Generate, and Brand/Profile are reachable within a Suite.
- Suite navigation labels are hard-coded and mixed Arabic/English regardless of selected UI language. This creates a native-language failure for Arabic/Hebrew and an English user clarity issue.
- Account-level and Suite-level navigation are visually separated on desktop, but the labels are not explicit enough. Users need to know whether they are managing their account or the current Suite.
- There are two dashboard concepts: `/suite/[id]` as a simplified command center and `/suite/[id]/dashboard` as the legacy all-in-one dashboard. This can confuse users and QA unless M1 declares the simplified Suite home as primary.

M1 quick wins:

- Add a mobile Suite menu when `activeSuiteId` exists. It must expose: Dashboard/Home, Connections, Brand/Profile, Create & Generate, Content, Analytics, Product Bulk.
- Localize SuiteNav labels through i18n keys or keep them consistently English only for M1 if translation coverage cannot be completed. Do not mix Arabic and English by default.
- Rename navigation groups visually: `Account` and `Current Suite`.
- Make `/suite/[id]` the primary Suite command center. Keep `/dashboard` available only as a deeper/legacy route or redirect it if Developers Manager agrees.

Later redesign:

- Rework Suite navigation into a polished app shell with responsive drawer, breadcrumbs, recent Suite switcher, and account/suite settings separation.

### 3. Suite Onboarding

Current baseline:

- New Suite onboarding includes name, links, research, category, languages, products/services, target audience, USP/ESP, brand assets, personas, strategy, and done states.
- Arabic/Hebrew direction is partially supported via `useLanguage`, `dir`, and `dir="auto"`.
- The flow includes manual skip/confirm paths and AI research fallback states.

M1 blockers:

- Long onboarding on mobile can fail UX even if it works technically. QA must verify sticky/progress behavior, back/skip reachability, upload controls, and that the active step is visible.
- The flow needs explicit failure copy when link research fails or returns weak data: "continue manually" must be obvious.
- Mixed-language placeholder risks exist in Arabic/Hebrew, especially examples and region-specific audience notes.
- Brand/logo upload classification must be visible to users if M1 requires square/horizontal/other classification.

M1 quick wins:

- Ensure every AI/research failure state has one primary action: continue manually.
- Verify all onboarding free-text inputs use `dir="auto"` and do not force RTL into URLs, email-like content, or platform handles.
- Show selected audience languages and primary language summary before strategy generation.
- Show logo upload result labels: square, horizontal, or other.

Later redesign:

- Convert onboarding into a saveable checklist/workspace setup model so users can leave and return without feeling trapped in a wizard.

### 4. Brand / Profile Editor

Current baseline:

- Profile page displays Suite brand data and supports editing content rules learned from feedback.
- There is an "Edit in wizard" link to `/suite/new`, but this does not clearly edit the current Suite.
- Many profile sections are read-only even though M1 acceptance requires editing profile, audience, USP/ESP, products/services, languages, brand assets, and personas after onboarding.

M1 blockers:

- Brand/Profile is currently not a sufficient post-onboarding editor. This is a must-fix because users need to correct AI research and manual setup mistakes without creating a new Suite.
- The "Edit in wizard" link risks sending users to create a new Suite instead of editing the current Suite.
- Profile page uses hard-coded dark styling and English labels, which breaks light theme consistency and native language expectations.

M1 quick wins:

- Remove or replace "Edit in wizard" unless it opens the current Suite's editable profile state.
- Add inline edit sections for the minimum M1 fields: business name, category, audience languages, services/products, audience notes/interests/behaviors/segments, USP/ESP, logos/assets, personas/reference images, content rules.
- Make manual edits visibly saved and never silently overwritten by AI regeneration.

Later redesign:

- Add section history, AI/manual source indicators, and versioned brand memory.

### 5. Create & Generate

Current baseline:

- Create & Generate uses `ContentTab` and `CreateCommandCenter`.
- Default mode is Quick Post/Ad.
- M1 modes are visible: Quick Post/Ad, Create Anything, Create Image, Create Video, Carousel, Product Bulk Studio. Campaign/Content Set are also present.
- Generation has visible loading/progress and failed state.

M1 blockers:

- `Use brand` defaults on without checking whether Suite brand data is actually usable. M1 requires it on only when Suite data exists, otherwise off or clearly limited.
- Prompt language is `dir="auto"`, but there is no obvious selected output language control near generation.
- Create page duplicates content review below the creation surface. This is acceptable for M1 only if hierarchy is clear; otherwise users may not understand whether they are creating or reviewing.
- Empty state says "Click Generate 3 posts" while the current primary button can be "Create post" or other modes. This copy is stale.

M1 quick wins:

- Gate `Use brand` by brand readiness and show a short limited-state label when data is missing.
- Add a language selector or language summary near the prompt, using the Suite audience primary language by default.
- Update empty state copy to match the selected mode and generation button.
- Keep generation status visible after navigation/refresh wherever backend status allows.

Later redesign:

- Split Create and Review into separate primary screens with a shared recent-content strip, not the same large surface.

### 6. Generated Content Review

Current baseline:

- Content is sorted newest first after filtering.
- Filters include status tabs and generation type tabs.
- Cards show date/time, media preview, edit, approve, reject, regenerate with feedback, copy, download, publish/schedule/mark used for approved content.
- Broken media has explicit fallback copy and open media link.

M1 blockers:

- Reject action can reject immediately without asking for a reason. M1 acceptance requires a reason and free text support.
- Regenerate feedback exists, but rejection feedback and regenerate feedback need to align so the user understands rejected content can teach the Suite.
- "All" exists for type filters but not for status filters. M1 acceptance asks status filters include All, Pending, Approved, Rejected, Published.
- Hard-coded dark styling and English copy are heavy in content review.

M1 quick wins:

- Change Reject to open a reason/free-text panel before submitting.
- Add status filter `All`.
- After approve/reject/regenerate/edit, show immediate visible state feedback and keep the user in the expected filter.
- Keep copy/download buttons available where media/text exists and use disabled/explanatory states when not available.

Later redesign:

- Add bulk review, compare/regenerate history, and "save feedback as rule" confirmation.

### 7. Product Bulk Studio

Current baseline:

- Product Bulk has Excel and ZIP upload, creative prompt, brand toggle, batch list, matched/missing stats, import preview, first-template generation, template approval, generate-all, per-asset review.
- Running/waiting/failed states are visible.

M1 blockers:

- The entire page is hard-coded English and dark-styled, so Arabic/Hebrew native-language and light-theme acceptance are not met.
- Product Bulk upload help does not document supported Arabic/Hebrew column names in the UI.
- Reject asset flow does not require feedback before rejection/regeneration.
- Upload error messages depend on backend detail. The UI should distinguish Excel missing/invalid, ZIP missing/invalid, size/limit, missing required columns, and image-name matching problems.

M1 quick wins:

- Add import help text or a compact "Supported columns" disclosure for English, Arabic, and Hebrew.
- Require or strongly prompt feedback for reject/regenerate.
- Keep the existing stats; add examples of why images are missing when available.
- Make file input labels and error states usable on mobile.

Later redesign:

- Add a guided left-to-right or right-to-left stepper based on language, batch comparison, and template preview approval modal.

### 8. Connections

Current baseline:

- Connections panel exists and is collapsed by default.
- Status dots show Meta, Google, and Storage.
- Missing R2 configuration can show missing env var names without secrets.
- Connections page wraps the panel in a dedicated Suite page.

M1 blockers:

- Connections are hidden behind a collapsed panel even on the dedicated Connections page. This is acceptable for a dashboard cleanliness panel, but the dedicated screen should probably open by default.
- Status dots have titles but no text labels explaining `connected`, `not connected`, or `needs attention`. Color alone is not enough.
- Meta status is derived from Facebook only; Instagram/meta_ads details appear inside the expanded card. The summary can understate partial connection states.
- Connection page is hard-coded English/dark-styled inside the panel.

M1 quick wins:

- Open the panel by default on `/connections`, or add a prop for default open.
- Add text status next to each connection: Connected, Not connected, Needs attention.
- Show partial Meta states: Facebook page, Instagram account, Meta Ads account.
- Keep env var messages technical but readable, and never expose values.

Later redesign:

- Add connection diagnostics/admin-only detail view and permission repair flows.

### 9. Analytics

Current baseline:

- Analytics page combines CampaignsHub and AnalyticsTab.
- Suite home links to Analytics and health cards.

M1 blockers:

- Analytics must fail gracefully when provider permissions are missing. The user should see "connect Meta/Google" or "missing permissions", not an empty dashboard.
- Analytics page label is partly Arabic while description is English, regardless of selected language.
- Analytics should not dominate the Suite home before connections and content exist.

M1 quick wins:

- Empty states should name the missing prerequisite: no connection, no permission, no campaigns, provider unavailable.
- Keep high-level summary on Suite home and deeper details on Analytics.
- Ensure mobile analytics cards stack without horizontal clipping.

Later redesign:

- Create a business-owner-friendly analytics summary focused on "what changed" and "what to do next", not a platform metrics dump.

### 10. Mobile

M1 blockers:

- Mobile Suite navigation is the highest design blocker. Users cannot reliably reach required Suite screens from inside a Suite.
- Long cards, tables, filters, and upload controls need explicit QA. Product Bulk import preview uses a horizontally scrollable table, which is acceptable only if the scroll affordance is visible and does not hide actions.
- Content review cards and create controls must fit without text overlap in Arabic/Hebrew and English.

M1 quick wins:

- Add a mobile Suite menu/drawer.
- Make filter bars horizontally scrollable with visible active state and no clipped labels.
- Verify onboarding uploads, Product Bulk uploads, and content card actions at 360px width.

Later redesign:

- Dedicated mobile bottom navigation for the main Suite tasks: Home, Create, Content, Connections, Profile.

## RTL and Native Language Expectations

M1 native-language bar:

- Arabic and Hebrew must set `html dir="rtl"` and use RTL layout for app chrome, major forms, onboarding, and review surfaces.
- User-generated text, URLs, emails, handles, IDs, env var names, and media URLs should use `dir="auto"` or `dir="ltr"` as appropriate.
- Button icon direction must mirror for Back/Next in RTL.
- Mixed-language content must not reorder numbers, dates, prices, campaign IDs, or hashtags incorrectly.
- UI labels should not mix Arabic, Hebrew, and English unless the term is a brand/platform name such as Meta, Google Ads, Instagram, or co-Suite.
- AI-generated Arabic/Hebrew content should remain in the selected output language unless the user explicitly requests mixed-language content.
- Generated image/video text overlays in Arabic/Hebrew are a known quality risk; if the provider cannot render glyphs reliably, M1 should explain the limitation and avoid silently producing broken text.

Observed risks:

- Global i18n supports Arabic/Hebrew and sets document direction, but many Suite screens are hard-coded English.
- `SuiteNav` mixes Arabic and English labels independent of selected language.
- `SuitePageShell` has hard-coded English "Back" and a non-mirrored left arrow.
- Dark legacy panels use `text-white`, `bg-zinc-*`, and English strings, bypassing theme and language systems.

## Dashboard Simplification and Navigation Clarity

M1 should treat `/suite/[id]` as the primary Suite command center:

- Show Suite health: Brand profile, Meta, Google Ads, Media storage.
- Show six primary actions: Create & Generate, Recent Content, Analytics, Connections, Brand/Profile, Product Bulk.
- Keep the dashboard clean. Connections should be summarized, not fully expanded, unless the user opens Connections.
- Do not make users choose between "Home", "Dashboard", and "Suite dashboard" without clear meaning.

Recommended M1 naming:

- Account group: `Account`
- Account links: `Suites`, `New Suite`, `Settings`
- Suite group: `Current Suite`
- Suite links: `Home`, `Connections`, `Brand/Profile`, `Create & Generate`, `Content Review`, `Analytics`, `Product Bulk`

Later redesign items:

- Suite switcher.
- Recent activity feed.
- Setup checklist with progress.
- Role-specific dashboards for creator/agency/business.

## Light / Dark Theme Consistency

M1 acceptance should require the current UI to be legible and coherent in both themes, not pixel-perfect.

Must fix:

- Replace hard-coded dark-only colors in M1 screens or wrap them in theme tokens: Profile, Product Bulk, Connections panel, Content review/Create legacy components, legacy dashboard.
- Verify hover, active, border, muted text, disabled, destructive, warning, and success states in both themes.
- Confirm auth theme does not reset unexpectedly.

Acceptable for M1:

- Some dark surfaces can remain if the product intentionally brands a "studio" area as dark, but then the surrounding page must not look broken in light mode and text contrast must pass visual QA.

Later redesign:

- Define a complete co-Suite visual system for workspace, review cards, generation jobs, analytics, and connection diagnostics.

## Quick Wins for M1

1. Add mobile Suite navigation.
2. Localize or consistently English-normalize SuiteNav and SuitePageShell labels for M1.
3. Make `/suite/[id]` the primary simplified command center.
4. Gate `Use brand` by brand readiness.
5. Add output language control or visible language summary to Create & Generate.
6. Add status filter `All` to content review.
7. Require rejection reason/free text before reject/regenerate.
8. Open Connections by default on the dedicated Connections page and add text status labels.
9. Replace "Edit in wizard" with a real current-Suite edit path or remove it.
10. Add Product Bulk supported column help for Arabic/Hebrew/English.
11. Normalize hard-coded dark panels enough to pass light/dark QA.
12. Add clear manual fallback copy to onboarding research failures.

## Later Redesign Items

- Standalone no-Suite generation home and conversion path into Suite.
- Full responsive app shell with Suite switcher and mobile bottom navigation.
- Editable Brand Memory system with version history and AI/manual provenance.
- Review history, compare/regenerate variants, and feedback-to-rule confirmation.
- Business-owner analytics summary with recommended next actions.
- Agency/client workspace model and permissions.
- Polished Product Bulk stepper and template approval experience.

## Acceptance Checks for QA

### Auth

- Sign up in English, Arabic, and Hebrew with name, email, password, and each account type.
- Confirm login redirects to authenticated area, not homepage.
- Refresh after login and confirm session persists.
- Toggle light/dark before auth and confirm it persists after login, refresh, and logout.
- Simulate API unavailable and confirm user sees a clear message.

### Suite Navigation

- On desktop, confirm account links and Suite links are visually separate.
- On mobile, open a Suite and reach Home, Connections, Brand/Profile, Create & Generate, Content Review, Analytics, and Product Bulk without typing a URL.
- Confirm active Suite name is visible and long names truncate safely.
- Confirm Arabic/Hebrew navigation does not mix languages unexpectedly.

### Onboarding

- Create Suite with website/social links and with no successful research result.
- Confirm manual continuation is obvious after fetch/search/AI failure.
- Enter Arabic, Hebrew, English, and mixed-language business names and audience notes.
- Upload multiple logos and verify square/horizontal/other labels.
- Add custom language, interests, behaviors, segments, audience note, USP, ESP, services, and personas.
- Refresh or navigate back where supported and confirm saved data is not lost unexpectedly.

### Brand/Profile

- Edit core fields after onboarding and confirm they save.
- Confirm manual edits survive AI regeneration.
- Upload additional logos and persona images after Suite creation.
- Confirm Profile is legible in light and dark themes.

### Create & Generate

- Open Create & Generate from Suite nav on desktop and mobile.
- Confirm default mode is Quick Post/Ad.
- Confirm `Use brand` is on only when brand data exists or clearly explains limited state.
- Generate Quick Post/Ad, Create Anything, Image, Video, Carousel, and Product Bulk entry path.
- Confirm queued/running/failed/completed states are visible.
- Confirm output language does not switch without user intent.

### Content Review

- Confirm status filters include All, Pending, Approved, Rejected, Published.
- Confirm type filters include relevant generation types.
- Confirm newest content appears first with date/time.
- Approve pending content and see state update.
- Reject content only after entering/selecting a reason.
- Regenerate with feedback and confirm feedback is submitted.
- Edit caption/text before approve.
- Copy caption/text.
- Download image/video where media exists.
- Confirm missing media explains the problem instead of showing a blank square.

### Product Bulk

- Upload valid Excel and ZIP.
- Try missing Excel, missing ZIP, invalid columns, oversized files, and unmatched image names.
- Confirm Arabic/Hebrew supported column names are documented in the UI or linked help.
- Generate first templates, approve one, generate all, then review individual assets.
- Reject/regenerate individual assets with feedback.
- Verify mobile upload and table preview usability.

### Connections

- Open Connections page and see connection details without needing to guess behind color dots.
- Confirm Meta, Google Ads, and Storage each show connected/not connected/needs attention.
- Confirm missing backend variables are named without exposing secret values.
- Confirm partial Meta state is understandable: Facebook, Instagram, Meta Ads.

### Analytics

- View Analytics with no connections, missing permissions, no campaigns, and provider error states.
- Confirm each state explains the prerequisite or issue.
- Verify mobile layout does not clip cards or tables.

## Recommended First Implementation Slices

1. Navigation and IA slice
   - Add mobile Suite menu/drawer.
   - Rename groups to Account and Current Suite.
   - Make `/suite/[id]` the primary M1 command center.
   - Normalize SuiteNav labels.

2. Language and RTL slice
   - Add i18n keys for M1 Suite shell labels.
   - Fix `SuitePageShell` Back label and arrow mirroring.
   - Audit hard-coded English on M1 pages.
   - Verify `dir="auto"`/`dir="ltr"` for mixed-language fields.

3. Theme consistency slice
   - Convert Profile, Product Bulk, Connections, Content Review, and Create surfaces from hard-coded dark colors to theme tokens where practical.
   - Run light/dark visual QA on auth, Suite home, onboarding, create, content, connections, profile, product bulk.

4. Brand/Profile editability slice
   - Replace the current read-mostly profile page with editable M1 sections.
   - Remove misleading "Edit in wizard" path.
   - Ensure manual edits override AI suggestions.

5. Create and content lifecycle slice
   - Gate `Use brand`.
   - Add output language control/summary.
   - Add status filter `All`.
   - Require rejection reason and route it into regenerate/feedback behavior.
   - Fix stale empty-state copy.

6. Connections and analytics clarity slice
   - Open dedicated Connections details by default.
   - Add text status labels and partial connection states.
   - Add analytics empty/error states for missing connection, permissions, no data, and provider unavailable.

7. Product Bulk usability slice
   - Add supported column help for English/Arabic/Hebrew.
   - Improve import error categories.
   - Require feedback for reject/regenerate.
   - Verify mobile upload and review flows.

## Design Gate Recommendation

Design should not block engineering from starting M1, but engineering should start with navigation/mobile, language/RTL, and profile editability before deeper polish. Those are release-blocking UX issues because they affect whether users can reach required screens, understand the product in their selected language, and correct the business memory that powers generation.
