# co-Suite M1 QA Smoke Matrix

Date: 2026-06-07  
Owner: QA  
Status: baseline_ready  
Milestone: M1 - Production Stabilization  

## Purpose

This matrix defines the first M1 smoke pass for co-Suite production stabilization. It is based on:

- `docs/software-company/projects/cosuite/product-acceptance-m1.md`
- `docs/software-company/projects/cosuite/milestone-01-production-stabilization.md`
- `docs/product/co-suite-product-manager-brief.md`
- existing QA, risk, release, and re-check registers

M1 QA should prove that a real user can sign up, create or open a Suite, complete core setup, generate and review content, understand integration/readiness states, and use the main workflows on desktop and mobile without silent breaks.

## Severity Definitions

| Severity | Definition | Release Impact |
|---|---|---|
| Critical | Blocks signup/login, Suite access, data save, generation start/result visibility, or publishing/media truthfulness for the primary M1 journey. Includes security/privacy exposure or destructive data loss. | Blocks release unless formally accepted as risk by Product, Project Management, and the accountable owner. |
| High | Breaks a must-have flow for a meaningful user segment, causes misleading success/failure state, hides actionable integration errors, or blocks mobile review of core content. | Blocks release unless closed or formally accepted as risk. |
| Medium | Degrades a must-have flow but has a reasonable workaround, unclear copy, partial state sync issue, or non-blocking UX issue in desktop/mobile/RTL. | Can release only with owner, mitigation, and re-check date. |
| Low | Cosmetic, polish, minor copy, or low-risk consistency issue that does not change user understanding or task completion. | Does not block release. |

Required finding statuses: `open`, `fix_in_progress`, `ready_for_recheck`, `closed`, `deferred`, `accepted_risk`.

## Test Data

QA needs repeatable test data before execution.

| Data Set | Required Values | Purpose |
|---|---|---|
| New business account | Unique name, unique email, password, account type `business/company/nonprofit` | Primary happy path for signup, login, Suite creation, onboarding, generation, review. |
| Creator account | Unique email, account type `creator/influencer` | Confirms account type exists and does not break auth/dashboard routing. |
| Agency account | Unique email, account type `marketing agency` | Confirms account type exists and Suites list supports multi-client direction. |
| Business profile example | Business name, website URL, Instagram/Facebook/LinkedIn URLs where available, phone/location optional | Onboarding source gathering and manual fallback. |
| RTL business example | Arabic business name and prompt, Hebrew business name and prompt, English control prompt | RTL/LTR layout, UI language, AI output language consistency. |
| Audience data | Languages: Arabic, Hebrew, English, one custom language; geography mode `custom`; interests, behaviors, demographics/social segments, free note | Audience onboarding and Brand/Profile persistence. |
| Brand assets | Square logo, horizontal logo, non-standard aspect logo, transparent image if available | Upload, classification, and Brand/Profile edit checks. |
| Persona assets | Persona name plus at least two reference images | Persona creation and multi-image upload. |
| Generation prompts | Quick Post/Ad prompt, Create Anything prompt, image prompt, video prompt, carousel prompt, rejection feedback prompt | Create & Generate, job states, generated content review, regeneration. |
| Product bulk catalog | Small Excel file with required fields, Arabic/Hebrew column variant, invalid catalog with missing required column | Import success, localization, and specific error handling. |
| Product image ZIP | Matching images by SKU/name plus one missing image | Match/missing report and product asset review. |
| Existing generated content | Pending item with text, pending item with image URL, pending item with video URL, item with missing media | Review, approve, reject, copy, download, preview, missing-media state. |

## Credentials Or Human Action Required

These checks cannot be fully completed by QA without real credentials, seeded fixtures, or human confirmation.

| Area | Required Input | Owner | QA Handling Until Available |
|---|---|---|---|
| Production auth email domain | Disposable or approved test email accounts | Product / DevOps | Use local/staging accounts if available; mark production-only email behavior blocked. |
| AI generation | Valid AI provider keys and agreed provider limits | DevOps / Architecture | Verify UI error state if keys are absent; full generation pass waits for provider readiness. |
| Source gathering | Public website/social URLs that permit access | Product | Use provided examples and one failing URL to verify fallback. |
| Meta connection | Meta app config, test Facebook page, test Instagram account, permissions | DevOps / Product | Verify `not connected` / `needs attention` states until credentials are ready. |
| Google Ads connection | Google OAuth config and test ads account | DevOps / Product | Verify `not connected` / `needs attention` states until credentials are ready. |
| R2/media storage | R2 account, bucket, public URL, access keys | DevOps | Verify publishing limitation message if absent; durable public URL checks wait for readiness. |
| Publishing | Connected platform account and human approval to publish or use sandbox page | Product / DevOps | Do not publish to real brand channels without explicit approval. |
| Product bulk files | Approved sample Excel and ZIP with non-sensitive product data | Product / QA | Use synthetic local samples until product-approved fixtures exist. |
| Mobile device coverage | At least one narrow viewport plus one real mobile device if available | QA / Design | Browser viewport smoke is minimum; real device is preferred before release. |

## Smoke Matrix

Legend: `P0` release-blocking smoke, `P1` must-have regression, `P2` useful if time remains. Result values during execution: `not_run`, `pass`, `fail`, `blocked`, `accepted_risk`.

| ID | Priority | Area | Scenario | Steps | Expected Result | Data / Credentials | Result | Finding |
|---|---|---|---|---|---|---|---|---|
| M1-SMOKE-001 | P0 | Auth / Signup | New business user can sign up | Open signup, select business/company/nonprofit, enter name/email/password, submit | Account is created, user lands in authenticated area, not homepage | New business account | not_run | TBD |
| M1-SMOKE-002 | P0 | Auth / Login | Existing user can log in and keep session | Log out, log in, refresh authenticated page | Login succeeds, refresh keeps user authenticated, logout works | Existing account | not_run | TBD |
| M1-SMOKE-003 | P1 | Auth / Account Types | Creator and agency account types are accepted | Repeat signup for creator and agency | Account type selection persists or is visible enough for later workflow assumptions | Creator and agency accounts | not_run | TBD |
| M1-SMOKE-004 | P1 | Auth / Error States | Backend/API unavailable or bad credentials show understandable message | Submit invalid login; if safe, test with API unavailable in controlled env | No raw `Request failed`, `Not Found`, silent redirect, or blank state | Controlled env | not_run | TBD |
| M1-SMOKE-005 | P1 | Theme / Language | Theme does not reset during auth flow | Toggle light/dark, run signup/login, refresh | Selected theme remains stable | Any account | not_run | TBD |
| M1-SMOKE-006 | P1 | Auth / RTL | Arabic/Hebrew auth copy and direction are usable | Switch to Arabic and Hebrew, complete auth smoke | Core strings are native enough and direction is readable | RTL account data | not_run | TBD |
| M1-SMOKE-010 | P0 | Suite List | User can see and create Suites | Open dashboard/Suites list, create a new Suite | Existing Suites show; new Suite can be created | Authenticated account | not_run | TBD |
| M1-SMOKE-011 | P0 | Suite Navigation | User can open Suite and reach core Suite screens | Open Suite, use Suite nav to Dashboard, Connections, Brand/Profile, Create & Generate, Analytics | Navigation separates account-level and Suite-level context; user can tell where they are | Existing Suite | not_run | TBD |
| M1-SMOKE-012 | P1 | Suite Navigation | Mobile nav does not cover content permanently | Narrow viewport, open/close menu, navigate Suite pages | Content remains reachable; menu state is controllable | Mobile viewport | not_run | TBD |
| M1-SMOKE-020 | P0 | Onboarding | Source gathering starts and manual fallback works | Create/open Suite, enter website/social links, continue after source gathering | System attempts gathering; user can continue manually if weak/fails | Business URLs | not_run | TBD |
| M1-SMOKE-021 | P0 | Onboarding | Business profile steps save and are editable | Complete business name, category, languages, services, audience, USP/ESP, brand assets | Data saves, user can go back/edit, AI suggestions do not overwrite user edits silently | Business profile data | not_run | TBD |
| M1-SMOKE-022 | P1 | Onboarding | Audience supports custom details | Add custom language, custom interests, behaviors, segments, and note | Values save and later appear in Brand/Profile | Audience data | not_run | TBD |
| M1-SMOKE-023 | P1 | Onboarding | Logos upload and classify by aspect ratio | Upload square, horizontal, and other logo | Uploads succeed and show square/horizontal/other classification | Brand assets | not_run | TBD |
| M1-SMOKE-024 | P1 | Onboarding | RTL business name and prompts are readable | Complete business name/category/audience in Arabic and Hebrew | RTL screens are readable; English appears only when content is intentionally English | RTL business data | not_run | TBD |
| M1-SMOKE-030 | P0 | Brand/Profile | User can edit saved Suite profile after onboarding | Open Brand/Profile and edit business profile, audience, marketing message, USP/ESP, products/services, languages | Edits save and persist after refresh | Existing Suite | not_run | TBD |
| M1-SMOKE-031 | P1 | Brand/Profile | User can upload additional logos and persona references | Add logos, add persona name and multiple reference images | Assets and persona entries save; failed uploads show actionable errors | Brand/persona assets | not_run | TBD |
| M1-SMOKE-032 | P1 | Brand/Profile | AI regeneration does not overwrite manual edits silently | Manually edit a field, trigger available regenerate action | User-confirmed values remain protected or overwrite is explicit | Suite with AI provider | not_run | TBD |
| M1-SMOKE-040 | P0 | Create & Generate | Create & Generate is reachable and Quick Post/Ad is default | Open Suite Create route | Prompt area is large enough; default mode is Quick Post/Ad | Existing Suite | not_run | TBD |
| M1-SMOKE-041 | P0 | Create & Generate | Generation starts with visible state | Submit Quick Post/Ad prompt | User sees queued/running/failed/completed state; button does not appear to do nothing | AI provider key | not_run | TBD |
| M1-SMOKE-042 | P1 | Create & Generate | M1 modes are visible and selectable | Check Quick Post/Ad, Create Anything, Create Image, Create Video, Carousel, Product Bulk Studio | Modes are present; unavailable provider paths explain limitation | Existing Suite | not_run | TBD |
| M1-SMOKE-043 | P1 | Create & Generate | `Use brand` default respects Suite data | Test with Suite that has profile data and one without enough profile data | `Use brand` is on only when data exists; otherwise off or clearly limited | Two Suites | not_run | TBD |
| M1-SMOKE-044 | P1 | Create & Generate | Language selection is honored | Generate Arabic, Hebrew, and English content | Caption/media text does not switch language without reason | RTL prompts and AI provider | not_run | TBD |
| M1-SMOKE-050 | P0 | Generated Content Review | Recent content list is usable | Open Content or Create recent content list | Newest content appears first; date/time shown on cards | Existing generated content | not_run | TBD |
| M1-SMOKE-051 | P0 | Generated Content Review | Approve/reject lifecycle works | Approve pending item; reject another with free-text reason | Status changes are visible immediately or after refresh; reject asks reason | Pending content | not_run | TBD |
| M1-SMOKE-052 | P1 | Generated Content Review | Regenerate uses rejection feedback | Reject with reason, regenerate item | Regeneration request includes or acknowledges feedback | AI provider and pending content | not_run | TBD |
| M1-SMOKE-053 | P1 | Generated Content Review | Text edit/copy works before approval | Edit caption/text, copy caption | Edited text persists; copied text matches latest value | Text content | not_run | TBD |
| M1-SMOKE-054 | P1 | Generated Content Review | Media preview/download/missing states are explicit | Open image, video, and missing-media cards; download media | Image/video preview when URL exists; missing media is explained; download works where media exists | Media fixtures | not_run | TBD |
| M1-SMOKE-060 | P0 | Product Bulk | Valid Excel and ZIP import reports matches | Upload valid Excel and ZIP | Import succeeds; matched/missing images are explained | Product bulk catalog and ZIP | not_run | TBD |
| M1-SMOKE-061 | P1 | Product Bulk | Invalid catalog errors are specific | Upload missing-column Excel or oversized file if safe | Error identifies Excel size, missing columns, ZIP images, or name matching | Invalid catalog | not_run | TBD |
| M1-SMOKE-062 | P1 | Product Bulk | First product template approval gates bulk generation | Generate first templates, approve one, generate remaining products | User approves one direction before generating all; each product asset is reviewable | AI provider and product fixtures | not_run | TBD |
| M1-SMOKE-063 | P1 | Product Bulk | Arabic/Hebrew column names are supported or documented | Upload localized-column sample or inspect docs shown in UI | User sees supported column names or clear validation guidance | Localized catalog | not_run | TBD |
| M1-SMOKE-070 | P0 | Connections | Connections page shows readiness states | Open Suite Connections | Meta, Google Ads, and storage/readiness states are visible as connected/not connected/needs attention | Existing Suite | not_run | TBD |
| M1-SMOKE-071 | P1 | Connections | Missing config is actionable and does not expose secrets | Test environment without provider config | Message names missing backend variable class without exposing secret values | Controlled env | not_run | TBD |
| M1-SMOKE-072 | P1 | Connections | Connected provider details display where allowed | Connect test Meta/Google account or use approved fixture | Facebook/Instagram page or Google account ID/name/email shows where permissions allow | Real credentials | blocked | Credentials required |
| M1-SMOKE-080 | P0 | Analytics / Campaign Read | Analytics fails gracefully without permissions | Open Analytics with no Meta/Google permissions | Shows `needs attention` or permission state, not misleading all-zero dashboard | Existing Suite without permissions | not_run | TBD |
| M1-SMOKE-081 | P1 | Analytics / Campaign Read | Metrics and date filters work when permissions exist | Open Analytics with connected account, change date filter | Available metrics/campaigns update for supported range | Real credentials | blocked | Credentials required |
| M1-SMOKE-082 | P1 | Analytics / Campaign Read | Active campaigns read without unsafe write actions | View Meta/Google campaigns if available | Active campaigns show as read-only M1 data; no accidental launch/edit path | Real credentials | blocked | Credentials required |
| M1-SMOKE-090 | P0 | Media / Publishing | Generated media intended for publishing uses durable public URL | Generate or inspect publishable image/video item | Public URL is durable; local-only media is not presented as publish-ready | R2/media readiness | blocked | R2 required |
| M1-SMOKE-091 | P1 | Media / Publishing | Storage not configured explains limitation | Test without R2 config | Publishing explains limitation and does not claim success | Controlled env | not_run | TBD |
| M1-SMOKE-092 | P1 | Media / Publishing | Text-only publish or used-externally path works | Mark content as used externally; test text-only publish only with approval | User can mark used externally; publishing errors are visible/actionable | Pending content, publish approval | not_run | TBD |
| M1-SMOKE-100 | P0 | Mobile | Mobile core journey works | On narrow viewport: login, open Suite, navigate Suite, open Create, open Content, approve/reject | Flow is usable; sidebar/menu does not block; cards fit width | Mobile viewport | not_run | TBD |
| M1-SMOKE-101 | P1 | Mobile / RTL | RTL mobile content review is readable | Switch Arabic/Hebrew, open Content, approve/reject | Tabs/buttons/cards fit and direction is readable | RTL content | not_run | TBD |
| M1-SMOKE-102 | P1 | Mobile | Touch targets are usable | Check main nav buttons, tabs, approve/reject, connection cards | Buttons/tabs are tappable and do not overlap | Mobile viewport | not_run | TBD |

## Initial Release Gate Recommendation Format

QA should use this format after each smoke pass.

```txt
QA Gate Recommendation: pass | pass_with_accepted_risk | block
Date:
Scope:
Environment:
Build / commit:

Summary:
- Core flows passing:
- Core flows failing:
- Blocked checks:

Open Critical Findings:
- None / list IDs

Open High Findings:
- None / list IDs

Accepted Risks:
- None / list IDs and approver

Credentials / Human Actions Still Required:
- None / list owners

Recommendation:
- Release / do not release / release only with accepted risks.

Next Re-check:
- Finding IDs and target date.
```

## M1 QA Gate Rule

QA should block the M1 release candidate when any critical or high finding remains open, when a P0 smoke path is not tested and not formally accepted as risk, or when integration/media states are misleading. Release can proceed only when core flows pass, mobile checks pass for affected surfaces, error states are understandable, and any remaining risks have named owners and formal acceptance.
