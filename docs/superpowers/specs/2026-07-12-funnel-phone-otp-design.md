# startbyconnec phone-only OTP auth + funnel UX round — design

Date: 2026-07-12
Status: approved

Owner-approved scope (this round, funnel `/startbyconnec` only):

1. **Phone-only registration/login** with OTP; capture the lead the moment the
   phone number is submitted, even if the visitor never finishes.
2. **Step persistence** — every funnel step is stored so a returning visitor
   resumes exactly where they left.
3. **Sticky confirm button** — the primary action of every funnel step is
   fixed to the bottom of the screen.
4. **No brand-assets step** (step-g العلامة التجارية) in the funnel wizard.
5. **Personas step redesigned from scratch** — ask whether there are central
   characters / a presenter whose photos or videos we may use.

Approved decisions: approach = lead-first, user-at-verify; phone normalization
= Israeli default (`05X…` → `+9725X…`, international kept as-is); OTP code
fixed at `123456` for now (WhatsApp/SMS integration later); wrong code shows
the reason; after verify the only field asked is the **name** (no email).

---

## Part 1 — data model (lightweight startup migrations in `api/main.py`)

- `leads.user_id` → nullable (`ALTER TABLE leads ALTER COLUMN user_id DROP NOT NULL`).
- `leads.full_name`, `leads.email` → nullable (same mechanism).
- `leads.phone` gets an index (`CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads (phone)`).
- `leads.progress` JSON gains `"step"`: one of
  `"phone" | "name" | "suite" | "plans" | "services" | "done"`.
- New table `phone_otps` (via SQLAlchemy metadata):
  `id (uuid pk), phone (indexed), code, attempts (int default 0),
  expires_at, verified_at NULL, created_at`.
- New setting `funnel_otp_code` (default `"123456"`). Sending is a stub
  (`services/otp_sender.py`, logs the send; later WhatsApp/SMS via
  `external_call()`).
- Models: `User.email` stays NOT NULL — phone-only users get a synthesized
  unique email `p<digits>@lead.cosuite.app` and a random password.

Phone normalization util `normalize_phone(raw)` (in `api/routers/funnel.py` or
`api/core/phone.py`): strip spaces/dashes/parens; `05X…` → `+9725X…`;
`9725…`/`009725…` → `+9725…`; other `+…` internationals kept; returns None if
fewer than 9 digits.

## Part 2 — backend endpoints (`api/routers/funnel.py`, all public/allowlisted)

- `POST /funnel/otp/request {phone}` →
  normalize; 400 `invalid_phone` if unparseable.
  **Upsert Lead by normalized phone** (source startbyconnec, status new,
  progress.step ??= "phone") — this is the "lead captured at first touch".
  Throttle: if an unexpired unverified OTP for this phone was created <60s ago
  → 429 `resend_too_soon` (with `retry_after_seconds`). Else create
  `phone_otps` row (code = settings.funnel_otp_code, expires 10 min), call the
  send stub. Response: `{ok: true}` (never reveals whether the phone is known).
- `POST /funnel/otp/verify {phone, code}` →
  latest unverified OTP for phone; errors as 400 with `detail`:
  `code_expired` (past expires_at), `too_many_attempts` (attempts ≥ 5),
  `invalid_code` (mismatch; increments attempts), `otp_not_found` (no request).
  On success: mark verified; find user — lead.user_id, else `User.phone ==
  normalized`, else create (synth email, random password,
  `approval_status="funnel"`, phone); link `lead.user_id`; set
  `lead.progress.step` to at least `"name"` (or keep further step).
  Response: `{access_token, user, lead, resume_step}` where `resume_step` is
  `progress.step` with fallback derivation (suite_id → "plans"; full_name →
  "suite"; else "name").
- `POST /funnel/profile {full_name}` (auth) → sets `lead.full_name` +
  `user.full_name`; bumps `progress.step` to `"suite"` if it was behind.
- `POST /funnel/progress {step}` (auth) → validates the step value, stores it
  in `lead.progress.step` (monotonic: never moves backwards).
- `GET /funnel/state` → also return `resume_step` (same derivation).
- Existing `/funnel/register` (email) stays but the funnel UI no longer uses it.

## Part 3 — frontend funnel auth (`web/src/app/startbyconnec/register/page.tsx` rewrite)

Three internal screens, funnel look, sticky bottom CTA:

1. **Phone** — single `type="tel"` field (`autocomplete="tel"`, numeric
   keyboard), CTA «أرسل الكود». On 429 show the cooldown message.
2. **Code** — 6-digit one-time-code input (`autocomplete="one-time-code"`,
   inputMode numeric), resend link with 60s countdown, error messages mapped
   from `detail` (invalid_code / code_expired / too_many_attempts /
   otp_not_found) in ar/he/en. On success → store token (auth store), route by
   `resume_step`.
3. **Name** — single name field, CTA «متابعة» → `POST /funnel/profile` →
   `/suite/new`.

Resume routing map (used after verify and by funnel pages):
`name` → register name screen; `suite` → `/suite/new`;
`plans` → `/suite/{id}/marketing-plan`; `services` → `/startbyconnec/services`;
`done` → `/startbyconnec/done`.

Progress posts from the frontend: after suite wizard completes (funnel) →
`plans`; opening `/startbyconnec/services` → `services`; request submit →
`done` (backend already records `request_submitted`).

## Part 4 — funnel wizard UX (`web/src/app/(dashboard)/suite/new/page.tsx`)

- **Skip step-g (brand assets)** for `isFunnelUser`: step-f advances straight
  to step-h; step-g removed from the `STEPS` indicator list; step-h back
  targets step-f.
- **Sticky confirm bar** for `isFunnelUser` (and funnel pages): a
  `StickyActions` wrapper — `sticky bottom-0 z-30 border-t border-border
  bg-background/95 px-4 py-3 backdrop-blur` — hosting each step's primary CTA
  (secondary skip/back links stay above it). Every wizard step's primary
  button renders inside it for funnel users; register/services/request pages
  use the same wrapper.

## Part 5 — personas step (step-h) redesigned (all users)

Question-first flow:

- Big title: «هل عندك شخصيات محورية أو برزنتور؟» subtitle: «أشخاص يظهرون
  بالمحتوى — صاحب المصلحة، موظفين، مقدّم/برزنتور — بنقدر نستخدم صورهم
  وفيديوهاتهم بالمحتوى والإعلانات.»
- Two choice cards: **نعم، في أشخاص** / **لا، بدون أشخاص** (i18n ar/he/en).
- «لا» → primary CTA continues (saves empty personas).
- «نعم» → the persona list UI (name + role optional + image upload as today,
  restyled to the boxed section pattern used in the audience steps).
- Selection stored with the step save (`brand_personas` as today; a "no"
  answer saves `[]`).

## Testing

- pytest: normalization (052→+97252, dedupe), lead created on otp/request,
  throttle 429, verify errors (invalid/expired/attempts), user create+link on
  verify, resume_step derivation, profile/progress endpoints, one-suite rule
  still holds.
- Browser: full funnel walk on dev; after deploy, a **live walk on
  cosuite.app** as a visitor (test phone, code 123456, name, into the wizard)
  — owner asked for a live user review.

## Out of scope

- Real WhatsApp/SMS sending (stub only, wired later).
- Changing the main app login (stays email+password).
- Handover/merge of phone-only users with email accounts.
