# User gating (freeze) + public startbyconnec funnel — design

Date: 2026-07-08
Status: approved-pending-review

Two features, one release train:

1. **User gating** — every user that is not explicitly approved is *frozen*: they can
   log in but see only a "closed launch" screen; all product APIs are blocked for them.
2. **startbyconnec funnel** — a public marketing funnel at `cosuite.app/startbyconnec`:
   register → create suite → marketing plan → work plan (strategy page) → services &
   pricing proposal → service request. The request lands in the admin panel as a lead,
   the suite is owned by the admin account, and the owner is notified on Telegram.

Decisions taken with the owner:

- Funnel visitors become **real users with `approval_status=frozen`**; the suite they
  build is **owned by `w.sholy@gmail.com`** and they join it as a `member`. The suite is
  linked to their lead so it can be handed over later.
- **One suite per funnel user**, and each generation stage runs **once** (no re-generate)
  to cap AI cost.
- Catalog is **Arabic + Hebrew**, prices in **₪**.
- New service requests fire a **Telegram notification** to the company group.
- Frozen screen shows a friendly message **+ CTA to /startbyconnec**.
- Phone: **required** in the funnel registration, **optional** in the regular signup.
- "خطة العمل" = the existing strategy page (social content plan + paid marketing
  content plan), reused as-is inside the funnel.

---

## Part 1 — user gating

### Data model

- `users.approval_status: varchar` — `frozen` | `approved`. Server default `frozen`.
- `users.phone: varchar NULL` — optional on regular signup, shown in admin.
- Migration backfills: everyone → `frozen`, except `w.sholy@gmail.com` and
  `admin@connec.co.il` → `approved`. (Follows the existing lightweight-migration
  mechanism used by `api/main.py` startup.)

### Backend enforcement — one choke point

`get_current_user` (api/core/security.py) gains the freeze gate: if
`user.approval_status != "approved"` and the request path is not allowlisted,
raise `403 {"detail": "account_frozen"}`.

Allowlisted for frozen users:

- `/auth/*` (login, signup, me, logout) — `me` must return `approval_status` + `phone`.
- `/funnel/*` — the whole funnel API (Part 2).
- Public/unauthenticated routes are unaffected (share links, `/health`, legal).

No per-router sweep: everything authenticated already flows through
`get_current_user`, so nothing can be forgotten.

### Frontend

- Auth store keeps `approval_status`.
- Dashboard layout: if the hydrated user is frozen → render a full-screen
  **FrozenScreen** instead of the dashboard: “التطبيق حالياً بمرحلة إطلاق مغلقة
  وغير مفتوح لمستخدمين خارجيين” + primary button **«ابدأ مع Connec»** →
  `/startbyconnec` (+ logout link). Arabic/Hebrew/English via i18n.
- API client: any `403 account_frozen` response routes to the same screen
  (covers stale tokens/tabs).
- Signup keeps working; a fresh signup simply lands on FrozenScreen.

### Admin

- `/admin` users table: new columns `approval_status`, `phone`; filter by status;
  **Approve / Freeze** action per user (extends `PATCH /admin/users/{id}`,
  audit-logged).

---

## Part 2 — startbyconnec funnel

Public pages live in the same Next.js app under `web/src/app/startbyconnec/` with
their own standalone layout (no dashboard sidebar; clean Connec/OneShare branding;
ar/he UI; one progress bar across the whole funnel). Because the group is
self-contained, mapping a future subdomain is a single host-rewrite in
`middleware.ts` — explicitly kept possible, not built now.

### Steps

1. **Landing** `/startbyconnec` — what you get (marketing plan, work plan, tailored
   price proposal), CTA start.
2. **Register** `/startbyconnec/register` — full name, email, **phone (required)**,
   password. Creates the frozen user **and a Lead immediately** (so drop-offs are
   visible in admin as incomplete leads). Then auto-login and continue.
3. **Suite creation** — the existing suite wizard, reused as-is, wrapped in the funnel
   layout. Backend `POST /funnel/suite` creates the suite with **owner = the
   configured admin account** (`settings.admin_lead_owner_email`, default
   `w.sholy@gmail.com`) and adds the funnel user as `SuiteMember(role=member)`;
   links `lead.suite_id`. One suite per funnel user (rejected if the lead already
   has one).
4. **Marketing plan** — existing marketing-plan generation/pages, one-shot: for
   funnel (frozen) members, generation endpoints refuse re-generation once output
   exists.
5. **Work plan (خطة العمل)** — the existing strategy page (social content plan +
   paid content plan), same one-shot rule.
6. **Services proposal** `/startbyconnec/services` — the catalog grouped by
   category; items matching the suite's brand are pre-highlighted as
   «موصى لعملك» via one small LLM call (brand → recommended service ids). Each
   item: ar/he name + description, price or range (e.g. ‎5,500–8,500 ₪), billing
   badge (لمرة واحدة / شهري / سنوي), quantity stepper for per-unit items. Clear,
   simple, invites selection.
7. **Service request** `/startbyconnec/request` — totals grouped by billing cycle
   (one-time / monthly / yearly; ranges rendered من–إلى), free-text notes, back to
   edit, submit → confirmation screen.

### Funnel API (`api/routers/funnel.py`)

- `POST /funnel/register` — signup (phone required) + lead. Reuses auth signup logic.
- `GET  /funnel/state` — resume point: lead, suite id, which stages are done.
- `POST /funnel/suite` — create suite under admin owner + membership + link lead.
- `GET  /funnel/catalog` — active service items (public, cached).
- `POST /funnel/recommendations` — LLM preselection for the current suite (once).
- `POST /funnel/service-request` — snapshot items + totals + notes; fires Telegram.

All endpoints usable by frozen users (allowlisted); suite-scoped ones verify the
caller is the lead's user.

---

## Part 3 — services catalog (admin-editable)

`service_items` table:

| field | notes |
|---|---|
| `id` | uuid |
| `name` / `description` / `category` | JSON `{"ar": …, "he": …}` |
| `billing_cycle` | `one_time` \| `monthly` \| `yearly` |
| `price_min`, `price_max` | `price_max NULL` → fixed price |
| `unit` | optional JSON label (لكل ساعة / لكل بانر / لكل فيديو…) — per-unit items get a qty stepper |
| `is_active`, `sort_order` | hide instead of delete; ordering |

**Admin tab «الخدمات»**: table CRUD, ar+he fields side by side, activate/deactivate,
reorder.

**Seed** (from the 14 Drive quotes, already read — starting point, admin edits later):
tadmiti website ~3,500 one-time; ecommerce site; ecommerce app (hour-based, large);
hosting from 39 ₪/mo; domain 69–90 ₪/yr; digital setup (pages + ad accounts) ~1,500;
graphics ~1,200 per 20 banners; Google & Meta campaign management ~2,200/mo; SEO+GEO
~1,800/mo; social page management ~800/mo; video day 5,500 (owner speaks) – 8,500
(our presenter); full package option.

---

## Part 4 — leads & requests in admin + notifications

- `leads`: `id, user_id, suite_id NULL (SET NULL on suite delete), full_name, email,
  phone, status (new | in_progress | won | lost), source ("startbyconnec"),
  created_at, updated_at, admin_notes`.
- `service_requests`: `id, lead_id, items JSON (service snapshot: id, names, cycle,
  unit price/range, qty), totals JSON per cycle {min,max}, customer_notes, status
  (new | seen | handled), created_at`.

**Admin tab «الليدات»**: list (name, phone, email, status, has-request badge, created);
detail page: contact info, **link to the suite profile**, selected services with
per-cycle totals, customer notes, status editing.

**Telegram**: on service-request submit, send to the company group (existing bot
config in `api/.env`): lead name + phone, per-cycle totals, deep links to the admin
lead page and the suite. Wrapped in `external_call()` per the logging convention.
Send failure must not fail the request (log + continue).

---

## Testing

- pytest: freeze gate (frozen blocked on product APIs, approved passes, allowlist
  passes, migration backfill correct), funnel endpoints (one-suite rule, one-shot
  generation rule, lead linkage, request snapshot + totals math incl. ranges and
  mixed cycles), admin CRUD for services/leads.
- Manual browser QA of the full funnel (ar + he) before release.

## Out of scope (explicitly later)

- Custom subdomain mapping for the funnel (kept possible via middleware rewrite).
- Suite ownership hand-over flow on approval (manual for now).
- Email notifications/verification.
- Templates/packages builder beyond simple catalog items.
