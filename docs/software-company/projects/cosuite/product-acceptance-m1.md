# Product Acceptance Criteria - Milestone 1

Date: 2026-06-07  
Owner: Product Manager  
Status: ready_for_review  
Milestone: M1 - Production Stabilization  

## Product Decision

Milestone 1 is about making the current co-Suite product stable, understandable, and usable enough for real customer testing.

It is not about adding every future capability.

The user-facing promise for M1:

> A business owner, creator, or agency can sign up, create or open a Suite, complete core business/brand setup, connect platforms where configured, generate and review content, and understand what is working or failing without silent breaks.

Product direction check:

- M1 must stabilize the base for the autonomous software-company workflow, but it must not ship blind automation. Human review, approve/reject, explicit connection states, and visible job states are the M1 product line.
- M1 must support a limited generation path before or outside a full Suite so users can test value without completing business onboarding.
- M1 must expose AI/job/media readiness clearly enough to scale later into durable queues, token controls, provider limits, and product workflows.
- M1 must preserve the web/SEO/mobile-app future by keeping mobile web usable and treating SEO builders, native apps, and automated campaign/calendar loops as later platform products.

## User Roles Covered In M1

| Role | M1 Coverage |
| --- | --- |
| Business / Company / Nonprofit | Must work end to end. This is the primary M1 user. |
| Creator / Influencer | Account type must exist; full creator-specialized workflows can wait. |
| Marketing Agency | Account type must exist; multi-client/roles can wait. |

## Must-Have Flows

### 1. Signup, Login, And Session

Priority: must-have  
Owner: Product Manager + Developers + QA  

Acceptance criteria:

- User can sign up with name, email, and password.
- User can select account type: business/company/nonprofit, creator/influencer, marketing agency.
- User can log in after signup.
- Login redirects to the correct authenticated area, not the homepage.
- Session persists after refresh.
- Logout works.
- Selected light/dark theme does not reset unexpectedly during signup/login.
- Arabic, Hebrew, and English UI strings are native enough for this flow.

Stable enough means:

- No `Request failed`, `Not Found`, or silent redirect in the normal signup/login path.
- If backend/API is unavailable, the user sees an understandable message.
- After login, the user can reach either Suite creation/opening or limited account-level generation without being trapped in onboarding.

### 2. Limited Account-Level Generation Without Suite

Priority: must-have  
Owner: Product Manager + Architecture + Developers + QA  

Acceptance criteria:

- A logged-in user can start a limited generation flow without first completing Suite onboarding.
- Supported M1 non-Suite modes are limited to simple prompt-driven generation where the existing providers/config allow it:
  - Quick Post/Ad.
  - Create Image.
  - Create Video.
  - Carousel or content set only if already backed by the current generation path.
- `Use brand` is off, disabled, or clearly unavailable when no Suite/brand memory exists.
- The flow can use prompt text, selected output language, and uploaded files where already supported.
- Results can be saved at account level or shown as recent output without pretending to have Suite memory.
- The UI explains the upgrade path to create a Suite for brand memory, audience memory, connections, publishing, scheduling, analytics, and long-running product workflows.
- The same job/status/error pattern used by Suite generation is visible for non-Suite generation.

Stable enough means:

- A user can test generation value before creating a Suite.
- The product never implies brand-aware generation, publishing, scheduling, analytics, or campaign readiness without a Suite.
- Provider, credit, queue, or media limitations are visible instead of silent.

### 3. Suite List And Suite Navigation

Priority: must-have  
Owner: Product Manager + Design + Developers + QA  

Acceptance criteria:

- User can see existing Suites.
- User can create a new Suite.
- User can open a Suite.
- Suite sidebar separates account-level navigation from Suite-level navigation.
- Suite-level navigation includes at least:
  - Dashboard.
  - Connections.
  - Brand/Profile.
  - Create & Generate.
  - Analytics.
- Mobile navigation is usable and not permanently covering content.

Stable enough means:

- User can always understand where they are: account area or Suite area.
- User can reach Connections, Create & Generate, and Brand/Profile within a Suite.

### 4. Suite Onboarding And Business Profile

Priority: must-have  
Owner: Product Manager + Architecture + Developers + QA  

Acceptance criteria:

- User can provide website/social links.
- System attempts to gather business information from provided sources.
- If fetching fails or returns weak data, user can continue manually.
- Business name step is editable and respects RTL/LTR.
- Business category suggestions are based on gathered data when available, not only fixed generic choices.
- Audience language step supports Arabic, Hebrew, English, and additional languages, plus custom language.
- Audience step includes:
  - default geographic mode: custom.
  - interests.
  - behaviors.
  - demographic/social segments.
  - free audience note.
- User can add custom interests, behaviors, segments, and audience notes.
- USP/ESP step supports adding all suggestions at once.
- Brand step supports multiple logo uploads.
- Logo uploads are classified at least as square, horizontal, or other by aspect ratio.
- User edits override AI suggestions.

Stable enough means:

- A user can finish onboarding even if AI/source gathering is incomplete.
- Saved profile data appears later in Brand/Profile.
- Arabic/Hebrew screens are RTL and do not mix core instructions in English unless the content itself is English.

### 5. Brand/Profile Editor

Priority: must-have  
Owner: Product Manager + Design + Developers + QA  

Acceptance criteria:

- User can edit the business profile after onboarding.
- User can edit target audience, marketing message, USP/ESP, products/services, languages, and brand assets.
- User can upload multiple logos after Suite creation.
- User can add personas/characters with name and multiple reference images.
- AI-regenerated suggestions are possible for sections where available.
- Manually edited values are not overwritten silently by AI.

Stable enough means:

- Business profile is not a one-time wizard trap.
- User can come back and fix business data without creating a new Suite.

### 6. Suite Create & Generate

Priority: must-have  
Owner: Product Manager + Architecture + Developers + QA  

Acceptance criteria:

- Create & Generate is reachable from the Suite navigation.
- Prompt area has enough space for real instructions.
- Default creation mode is `Quick Post/Ad`.
- Available M1 modes:
  - Quick Post/Ad.
  - Create Anything.
  - Create Image.
  - Create Video.
  - Carousel.
  - Product Bulk Studio.
- `Use brand` is on by default only when Suite data is available.
- If no Suite or not enough brand data exists, `Use brand` is off or clearly limited.
- User can choose or request content in their selected language.
- Generated captions and generated image/video text should not switch languages without reason.

Stable enough means:

- Generation starts as a visible job or clear loading state.
- User sees queued/running/failed/completed states.
- No generation button should appear to do nothing.

### 7. Generated Content Review

Priority: must-have  
Owner: Product Manager + Developers + QA  

Acceptance criteria:

- Recent content is sorted newest first.
- Filter tabs include:
  - All.
  - Pending.
  - Approved.
  - Rejected.
  - Published.
  - Product/generation type filters where available.
- Content cards show generation/production date and time.
- User can approve pending content.
- User can reject content.
- Reject flow asks for a reason and supports free text.
- Regenerate uses rejection feedback when available.
- User can edit post text before approve.
- User can copy caption/text.
- User can download generated image/video when media exists.
- Video preview works when a video URL/artifact exists.
- If media is missing or unavailable, the card explains why.

Stable enough means:

- Approve/reject/regenerate state changes are visible immediately or after refresh.
- Broken media is not shown as a silent blank square.

### 8. Product Bulk Studio

Priority: must-have  
Owner: Product Manager + Developers + QA  

Acceptance criteria:

- User can upload Excel catalog up to the current agreed limit.
- User can upload ZIP with product images.
- Supported Hebrew/Arabic column names are documented.
- Image matching explains matched/missing images.
- If product image matching fails, user sees why.
- User can generate first product templates before generating all.
- User can approve one template direction.
- User can generate remaining products after template approval.
- Each generated product asset can be reviewed individually.

Stable enough means:

- Import errors are specific, not generic.
- The user can tell whether the problem is Excel size, missing columns, ZIP images, or name matching.

### 9. Connections

Priority: must-have  
Owner: Product Manager + Developers + DevOps + QA  

Acceptance criteria:

- Connections are shown in their own Suite screen.
- Connections default closed/collapsed if needed for dashboard cleanliness.
- Each connection shows a simple status indicator:
  - configured/connected.
  - not connected.
  - needs attention.
- Meta connection can show connected Facebook/Instagram page/account where permissions allow.
- Google Ads connection can show connected account ID and account name/email when available.
- R2/media storage readiness can be surfaced as an internal/admin or diagnostic state.
- Missing configuration messages explain which backend variables are missing without exposing secrets.

Stable enough means:

- User knows whether a platform is connected.
- A failed connection does not look successful.

### 10. Analytics And Campaign Read

Priority: must-have  
Owner: Product Manager + Developers + QA  

Acceptance criteria:

- Analytics screen shows available page/account metrics when permissions allow.
- If Meta/Google permissions are missing, user sees a clear `needs attention` state.
- Active Meta campaigns can be shown if available.
- Active Google campaigns can be shown if available.
- Campaign/ad/adset hierarchy is a Platform V1 item unless already safe and simple.
- Date filters work for supported metrics.

Stable enough means:

- No misleading all-zero dashboard when the real issue is permissions or unsupported metrics.
- Permission/API errors are translated into user/admin friendly state.

### 11. Media Storage And Publishing Basics

Priority: must-have  
Owner: Product Manager + DevOps + Developers + QA  

Acceptance criteria:

- Generated images/videos intended for publishing have durable public URLs.
- If R2/storage is not configured, publishing explains the limitation.
- Text-only publishing path can still work where supported.
- User can mark content as used externally when they do not publish through the app.
- Publishing errors are visible and actionable.

Stable enough means:

- We do not tell the user publishing succeeded if media was not public or platform rejected it.

### 12. Mobile Usability Baseline

Priority: must-have  
Owner: Product Manager + Design + QA  

Acceptance criteria:

- User can use core M1 flows on mobile:
  - login.
  - open Suite.
  - navigate Suite.
  - review content.
  - approve/reject.
  - open Connections status.
  - open Create & Generate.
- Sidebar/menu does not block main content by default.
- Cards fit screen width.
- Buttons and tabs are tappable.
- RTL mobile layout is readable.

Stable enough means:

- Mobile is not perfect, but it is not embarrassing or blocking for review/testing.

## Should-Have In M1

These are valuable if they fit without delaying stabilization:

- Better empty states for every major screen.
- More native Arabic/Hebrew copy polish.
- Basic admin view for failed generation jobs.
- Better dashboard grouping.
- Basic campaign cards under generated content.
- Improved color/theme consistency.
- Download package for carousel assets.

## Later / Not M1

These are intentionally outside Milestone 1:

- Full iOS/Android apps.
- Full automated social media loop builder.
- Full campaign creation and editing in Meta/Google.
- TikTok integration.
- Agency team roles and permissions.
- Full payment provider integration if not already partially implemented.
- Full subscription/token-pack checkout, exact pricing, or marketing-budget ledger.
- Advanced SEO website builder.
- Public marketing website/SEO launch beyond not blocking the future product direction.
- CRM/WhatsApp/email automation.
- Deep enterprise analytics.

## M1 Release Gate

The Product Manager recommends release only when:

- All must-have flows are either passing or explicitly accepted as risk.
- No core flow fails silently.
- QA has tested mobile and desktop.
- Architecture has completed re-check on generation/media/Suite Memory changes.
- DevOps confirms production env/media/queue readiness.
- Project Management updates release readiness.

## Product Risks

| Risk | Product Impact | Required Handling |
| --- | --- | --- |
| AI source gathering sometimes returns weak business data | User loses trust during onboarding. | Allow manual continuation and clear AI confidence/source state. |
| Arabic/Hebrew mixed with English | Product feels foreign and unfinished. | Native language first for UI and AI suggestions. |
| Video/media preview fails | User cannot approve content confidently. | Show artifact state and fix preview path. |
| Analytics all-zero | User thinks platform has no value. | Differentiate no data from no permission/API error. |
| Too many features in dashboard | User feels lost. | Separate Suite navigation and simplify dashboard. |

## Product Manager Handoff

Send this to:

- Architecture for baseline review.
- Design for UX baseline review.
- DevOps / Infra for runtime readiness review.
- QA for smoke test design.
- Developers Manager for implementation slicing after baseline reviews.
