# User Gating (Freeze) + startbyconnec Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block all non-approved users from the product (frozen screen + CTA), and launch a public lead funnel at `/startbyconnec` (register → suite wizard → marketing plan → work plan → services & pricing proposal → service request that lands as a lead in admin + Telegram).

**Architecture:** One new `approval_status` on `users` (`approved` / `frozen` / `funnel`) enforced at the single auth choke point (`get_current_user`) with a per-status path allowlist. Funnel users are real users with status `funnel`; their suite is owned by the lead-owner admin account (`w.sholy@gmail.com`) and they access it via a new owner-or-member access helper. Catalog/lead/request are three new tables; admin gets services + leads pages; Telegram notification on request submit.

**Tech Stack:** FastAPI + SQLAlchemy async + lightweight SQL migrations in `api/main.py` startup; Next.js 15 App Router + zustand + existing i18n; pytest (unit-style, `FakeDb` + `monkeypatch`, no DB); httpx for Telegram.

## Global Constraints

- Approved-at-migration emails, verbatim: `w.sholy@gmail.com`, `admin@connec.co.il`.
- Frozen 403 body is exactly `{"detail": "account_frozen"}`.
- Funnel one-shot 403 body is exactly `{"detail": "funnel_regeneration_blocked"}`.
- Catalog languages: Arabic + Hebrew only (JSON `{"ar": ..., "he": ...}` fields). Prices in ₪ (numbers, no currency in DB).
- Billing cycles enum strings: `one_time` | `monthly` | `yearly`.
- Lead statuses: `new` | `in_progress` | `won` | `lost`. Request statuses: `new` | `seen` | `handled`.
- One suite per funnel user; regeneration of already-generated funnel outputs must 403.
- Telegram send failures must never fail the API request (log and continue). All outbound calls wrapped in `external_call(...)` (`api/core/external_calls.py`).
- Web work: this Next.js version differs from training data — read the relevant guide under `web/node_modules/next/dist/docs/` before writing app-router code (per `web/AGENTS.md`).
- `cd web && npx tsc --noEmit` has 2 pre-existing errors from iCloud-duplicated files (`.next/types/*2.ts`) — ignore those two only.
- Python tests run from repo root: `python3 -m pytest tests/<file> -v`.
- The `web/` directory is its own git repo — commit frontend changes inside `web/`, backend/doc changes at repo root.

---

### Task 1: User model — `approval_status` + `phone` + migration + serialization

**Files:**
- Modify: `api/models/user.py`
- Modify: `api/main.py` (startup migration list, after line 100 inside the existing statements tuple)
- Modify: `api/services/admin_audit.py:25-35` (`serialize_user_public`)
- Modify: `api/routers/auth.py` (SignupRequest + signup handler)
- Test: `tests/test_user_gating.py`

**Interfaces:**
- Produces: `User.approval_status: str` (default `"frozen"`), `User.phone: str | None`; `serialize_user_public()` now includes `approval_status` and `phone`; `POST /auth/signup` accepts optional `phone`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_user_gating.py
import pytest

from api.models.user import User
from api.services import admin_audit


def test_new_user_defaults_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    # Column default applies on INSERT; the model-level default must also be frozen
    assert User.approval_status.default.arg == "frozen"


def test_serialize_user_public_includes_approval_and_phone():
    user = User(
        id="u1", email="a@b.com", full_name="A", hashed_password="h",
        approval_status="approved", phone="0501234567",
    )
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "approved"
    assert payload["phone"] == "0501234567"


def test_serialize_user_public_defaults_missing_status_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "frozen"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_user_gating.py -v`
Expected: FAIL (`approval_status` attribute missing).

- [ ] **Step 3: Implement**

In `api/models/user.py`, add after `is_super_admin` (line 17):

```python
    # approved | frozen | funnel — anything but "approved" is blocked from the
    # product API (see core.security.frozen_path_allowed)
    approval_status: Mapped[str] = mapped_column(String, default="frozen", server_default="frozen", nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
```

Add `from typing import Optional` at the top of the file.

In `api/main.py`, append to the existing migration statements tuple (inside the `for statement in (...)` block that ends at line 101):

```python
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status VARCHAR DEFAULT 'frozen' NOT NULL",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR",
                    "UPDATE users SET approval_status = 'approved' WHERE lower(email) IN ('w.sholy@gmail.com', 'admin@connec.co.il') OR is_super_admin = TRUE",
```

(The `ALTER ... DEFAULT 'frozen'` backfills every existing row to frozen; the `UPDATE` re-approves the two owner accounts and any super admin. Idempotent on every restart.)

In `api/services/admin_audit.py`, extend `serialize_user_public`:

```python
def serialize_user_public(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": bool(user.is_active),
        "is_verified": bool(user.is_verified),
        "is_super_admin": bool(user.is_super_admin),
        "approval_status": user.approval_status or "frozen",
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }
```

In `api/routers/auth.py`, extend `SignupRequest` and the `signup` handler:

```python
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str | None = None
```

and in `signup`, pass phone when constructing the user:

```python
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        phone=(data.phone or "").strip() or None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_user_gating.py tests/test_admin_routes.py -v`
Expected: PASS (including the pre-existing admin serializer tests).

- [ ] **Step 5: Commit**

```bash
git add api/models/user.py api/main.py api/services/admin_audit.py api/routers/auth.py tests/test_user_gating.py
git commit -m "feat: user approval_status + phone with frozen default and owner backfill"
```

---

### Task 2: Freeze gate at the auth choke point

**Files:**
- Modify: `api/core/security.py`
- Test: `tests/test_user_gating.py` (append)

**Interfaces:**
- Produces: `frozen_path_allowed(approval_status: str, method: str, path: str) -> bool` in `api/core/security.py`; `get_current_user` now takes FastAPI's `Request` and raises `403 account_frozen`.
- Consumes: `User.approval_status` from Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_gating.py`:

```python
from api.core.security import frozen_path_allowed


def test_approved_user_passes_everywhere():
    assert frozen_path_allowed("approved", "POST", "/api/v1/suites/")
    assert frozen_path_allowed("approved", "GET", "/api/v1/billing/x")


def test_frozen_user_only_reaches_auth_and_funnel():
    assert frozen_path_allowed("frozen", "GET", "/api/v1/auth/me")
    assert frozen_path_allowed("frozen", "POST", "/api/v1/funnel/enroll")
    assert not frozen_path_allowed("frozen", "GET", "/api/v1/suites/")
    assert not frozen_path_allowed("frozen", "POST", "/api/v1/onboarding/extract-brand")
    assert not frozen_path_allowed("frozen", "GET", "/api/v1/billing/x")


def test_funnel_user_reaches_wizard_paths_but_not_billing():
    assert frozen_path_allowed("funnel", "POST", "/api/v1/onboarding/extract-brand")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/abc")
    assert frozen_path_allowed("funnel", "POST", "/api/v1/suites/abc/marketing-plan/generate")
    assert frozen_path_allowed("funnel", "GET", "/api/v1/auth/me")
    assert not frozen_path_allowed("funnel", "GET", "/api/v1/billing/x")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/connections/meta/connect")


def test_funnel_user_cannot_create_suites_directly_or_generate_more():
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites/")
    assert not frozen_path_allowed("funnel", "POST", "/api/v1/suites")
    assert not frozen_path_allowed(
        "funnel", "POST", "/api/v1/suites/abc/marketing-plan/competitors/generate-more"
    )
    # GET on the suites collection stays allowed
    assert frozen_path_allowed("funnel", "GET", "/api/v1/suites/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_user_gating.py -v`
Expected: FAIL with `ImportError: cannot import name 'frozen_path_allowed'`.

- [ ] **Step 3: Implement in `api/core/security.py`**

Add `Request` to the fastapi import, then add above `get_current_user`:

```python
FROZEN_ALLOWED_PREFIXES = ("/api/v1/auth", "/api/v1/funnel")
FUNNEL_ALLOWED_PREFIXES = FROZEN_ALLOWED_PREFIXES + ("/api/v1/onboarding", "/api/v1/suites")


def frozen_path_allowed(approval_status: str, method: str, path: str) -> bool:
    """Per-status API gate. Anything not approved sees only its allowlist."""
    if approval_status == "approved":
        return True
    if approval_status == "funnel":
        # Funnel suites are created via /funnel/suite (owned by the lead owner)
        if method.upper() == "POST" and path.rstrip("/") == "/api/v1/suites":
            return False
        # The small "generate-more" refinement endpoints are not part of the funnel
        if path.rstrip("/").endswith("generate-more"):
            return False
        return path.startswith(FUNNEL_ALLOWED_PREFIXES)
    return path.startswith(FROZEN_ALLOWED_PREFIXES)
```

Change `get_current_user` to accept the request and enforce the gate (super admins always pass):

```python
async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_super_admin and not frozen_path_allowed(
        user.approval_status or "frozen", request.method, request.url.path
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_frozen")
    return user
```

(FastAPI injects `Request` into dependencies automatically; every existing `Depends(get_current_user)` keeps working unchanged.)

- [ ] **Step 4: Run tests + the whole suite to catch dependency breakage**

Run: `python3 -m pytest tests/ -x -q`
Expected: PASS (pre-existing failures, if any, must be unrelated — note them).

- [ ] **Step 5: Commit**

```bash
git add api/core/security.py tests/test_user_gating.py
git commit -m "feat: freeze gate — frozen/funnel path allowlists in get_current_user"
```

---

### Task 3: Admin approval controls

**Files:**
- Modify: `api/routers/admin.py` (`AdminUserUpdate` model near the top; `update_user` at ~line 341; `users` list at ~line 280)
- Test: `tests/test_user_gating.py` (append)

**Interfaces:**
- Produces: `PATCH /admin/users/{id}` accepts `approval_status`; `GET /admin/users?approval=frozen|approved|funnel` filters.
- Consumes: Task 1 fields.

- [ ] **Step 1: Write the failing test**

```python
def test_admin_user_update_accepts_approval_status():
    from api.routers.admin import AdminUserUpdate
    payload = AdminUserUpdate(approval_status="approved")
    assert payload.approval_status == "approved"
    with pytest.raises(Exception):
        AdminUserUpdate(approval_status="nonsense")
```

- [ ] **Step 2: Run it — expect FAIL** (`approval_status` not a field).

Run: `python3 -m pytest tests/test_user_gating.py -v -k approval_status`

- [ ] **Step 3: Implement**

In `api/routers/admin.py` find `class AdminUserUpdate(BaseModel)` and add:

```python
    approval_status: Literal["approved", "frozen", "funnel"] | None = None
```

(add `from typing import Literal` to imports if missing). In `update_user` extend the field loop:

```python
    for field in ("email", "full_name", "is_active", "is_verified", "is_super_admin", "approval_status"):
```

In the `users` list endpoint add a filter param `approval: str | None = None` and:

```python
    if approval in ("approved", "frozen", "funnel"):
        query = query.where(User.approval_status == approval)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_user_gating.py tests/test_admin_routes.py -v` — PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/admin.py tests/test_user_gating.py
git commit -m "feat: admin approve/freeze controls and approval filter on users list"
```

---

### Task 4: Catalog, lead, and request models + migrations

**Files:**
- Create: `api/models/services_catalog.py`
- Modify: `api/models/__init__.py` (import the new module so `Base.metadata` sees it — follow how other models are imported there)
- Modify: `api/main.py` (migration tuple — three CREATE TABLE statements)
- Test: `tests/test_services_catalog.py`

**Interfaces:**
- Produces:
  - `ServiceItem(id, name: dict, description: dict, category: dict, billing_cycle: str, price_min: float, price_max: float|None, unit: dict|None, is_active: bool, sort_order: int, created_at, updated_at)`
  - `Lead(id, user_id, suite_id|None, full_name, email, phone, status="new", source="startbyconnec", admin_notes|None, recommendations: dict|None, progress: dict|None, created_at, updated_at)`
  - `ServiceRequest(id, lead_id, items: list[dict], totals: dict, customer_notes|None, status="new", created_at)`
  - `serialize_service_item(item) -> dict`, `serialize_lead(lead) -> dict`, `serialize_service_request(req) -> dict` (module-level functions in the same file)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services_catalog.py
from api.models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)


def test_service_item_serialization_roundtrip():
    item = ServiceItem(
        id="s1",
        name={"ar": "موقع تعريفي", "he": "אתר תדמיתי"},
        description={"ar": "وصف", "he": "תיאור"},
        category={"ar": "مواقع وتطبيقات", "he": "אתרים ואפליקציות"},
        billing_cycle="one_time",
        price_min=3500,
        price_max=None,
        unit=None,
        is_active=True,
        sort_order=1,
    )
    out = serialize_service_item(item)
    assert out["name"]["he"] == "אתר תדמיתי"
    assert out["billing_cycle"] == "one_time"
    assert out["price_max"] is None


def test_lead_defaults():
    lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.com", phone="050")
    out = serialize_lead(lead)
    assert out["status"] == "new"
    assert out["source"] == "startbyconnec"
    assert out["suite_id"] is None


def test_service_request_serialization():
    req = ServiceRequest(
        id="r1", lead_id="l1",
        items=[{"service_id": "s1", "qty": 2}],
        totals={"monthly": {"min": 800.0, "max": 800.0}},
        customer_notes="ملاحظات",
    )
    out = serialize_service_request(req)
    assert out["status"] == "new"
    assert out["totals"]["monthly"]["min"] == 800.0
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

Run: `python3 -m pytest tests/test_services_catalog.py -v`

- [ ] **Step 3: Implement `api/models/services_catalog.py`**

```python
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ServiceItem(Base):
    """One sellable service in the public startbyconnec catalog (admin-editable)."""

    __tablename__ = "service_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[dict] = mapped_column(JSON, nullable=False)          # {"ar": ..., "he": ...}
    description: Mapped[dict] = mapped_column(JSON, nullable=False)   # {"ar": ..., "he": ...}
    category: Mapped[dict] = mapped_column(JSON, nullable=False)      # {"ar": ..., "he": ...}
    billing_cycle: Mapped[str] = mapped_column(String, nullable=False, default="one_time")
    price_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # NULL → fixed price
    unit: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # qty stepper shown when set
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Lead(Base):
    """A startbyconnec visitor: created at funnel registration, enriched later."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    suite_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("suites.id", ondelete="SET NULL"), nullable=True
    )
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    source: Mapped[str] = mapped_column(String, nullable=False, default="startbyconnec")
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendations: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    progress: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ServiceRequest(Base):
    """Submitted service selection: immutable snapshot of items + totals."""

    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"), nullable=False, index=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def serialize_service_item(item: ServiceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name or {},
        "description": item.description or {},
        "category": item.category or {},
        "billing_cycle": item.billing_cycle,
        "price_min": item.price_min,
        "price_max": item.price_max,
        "unit": item.unit,
        "is_active": bool(item.is_active if item.is_active is not None else True),
        "sort_order": int(item.sort_order or 0),
    }


def serialize_lead(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "user_id": lead.user_id,
        "suite_id": lead.suite_id,
        "full_name": lead.full_name,
        "email": lead.email,
        "phone": lead.phone,
        "status": lead.status or "new",
        "source": lead.source or "startbyconnec",
        "admin_notes": lead.admin_notes,
        "recommendations": lead.recommendations,
        "progress": lead.progress or {},
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
    }


def serialize_service_request(req: ServiceRequest) -> dict[str, Any]:
    return {
        "id": req.id,
        "lead_id": req.lead_id,
        "items": req.items or [],
        "totals": req.totals or {},
        "customer_notes": req.customer_notes,
        "status": req.status or "new",
        "created_at": req.created_at,
    }
```

Note the Python-level defaults (`default="new"` etc.) make `serialize_*` correct only after flush; for unit tests, SQLAlchemy applies column defaults at INSERT — so set the serializers to fall back as written (`lead.status or "new"`), which the tests above rely on.

Add the import to `api/models/__init__.py` following the existing pattern (e.g. `from .services_catalog import ServiceItem, Lead, ServiceRequest  # noqa`).

In `api/main.py` append to the migration tuple:

```python
                    "CREATE TABLE IF NOT EXISTS service_items (id VARCHAR PRIMARY KEY, name JSON NOT NULL, description JSON NOT NULL, category JSON NOT NULL, billing_cycle VARCHAR DEFAULT 'one_time' NOT NULL, price_min DOUBLE PRECISION DEFAULT 0 NOT NULL, price_max DOUBLE PRECISION, unit JSON, is_active BOOLEAN DEFAULT TRUE NOT NULL, sort_order INTEGER DEFAULT 0 NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE TABLE IF NOT EXISTS leads (id VARCHAR PRIMARY KEY, user_id VARCHAR REFERENCES users(id) NOT NULL, suite_id VARCHAR REFERENCES suites(id) ON DELETE SET NULL, full_name VARCHAR NOT NULL, email VARCHAR NOT NULL, phone VARCHAR NOT NULL, status VARCHAR DEFAULT 'new' NOT NULL, source VARCHAR DEFAULT 'startbyconnec' NOT NULL, admin_notes TEXT, recommendations JSON, progress JSON, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_leads_user_id ON leads (user_id)",
                    "CREATE TABLE IF NOT EXISTS service_requests (id VARCHAR PRIMARY KEY, lead_id VARCHAR REFERENCES leads(id) NOT NULL, items JSON NOT NULL, totals JSON NOT NULL, customer_notes TEXT, status VARCHAR DEFAULT 'new' NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_service_requests_lead_id ON service_requests (lead_id)",
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_services_catalog.py -v` — PASS.

- [ ] **Step 5: Commit**

```bash
git add api/models/services_catalog.py api/models/__init__.py api/main.py tests/test_services_catalog.py
git commit -m "feat: service catalog, lead, and service request models + migrations"
```

---

### Task 5: Pricing totals helper

**Files:**
- Create: `api/services/service_pricing.py`
- Test: `tests/test_services_catalog.py` (append)

**Interfaces:**
- Produces: `compute_totals(selections: list[dict]) -> dict[str, dict[str, float]]` where each selection is `{"billing_cycle": str, "price_min": float, "price_max": float|None, "qty": int}` and the result maps cycle → `{"min": x, "max": y}`.

- [ ] **Step 1: Write the failing tests**

```python
from api.services.service_pricing import compute_totals


def test_compute_totals_mixed_cycles_and_ranges():
    totals = compute_totals([
        {"billing_cycle": "one_time", "price_min": 3500, "price_max": None, "qty": 1},
        {"billing_cycle": "one_time", "price_min": 5500, "price_max": 8500, "qty": 1},
        {"billing_cycle": "monthly", "price_min": 800, "price_max": None, "qty": 1},
        {"billing_cycle": "monthly", "price_min": 2200, "price_max": None, "qty": 1},
        {"billing_cycle": "yearly", "price_min": 69, "price_max": 90, "qty": 1},
    ])
    assert totals["one_time"] == {"min": 9000.0, "max": 12000.0}
    assert totals["monthly"] == {"min": 3000.0, "max": 3000.0}
    assert totals["yearly"] == {"min": 69.0, "max": 90.0}


def test_compute_totals_quantity_and_bad_input():
    # unknown cycle is coerced to one_time, qty floors at 1
    totals = compute_totals([
        {"billing_cycle": "one_time", "price_min": 1200, "price_max": None, "qty": 3},
        {"billing_cycle": "bogus-cycle", "price_min": 10, "price_max": None, "qty": 0},
    ])
    assert totals["one_time"] == {"min": 3610.0, "max": 3610.0}
    assert "bogus-cycle" not in totals


def test_compute_totals_empty():
    assert compute_totals([]) == {}
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_services_catalog.py -v -k totals`

- [ ] **Step 3: Implement `api/services/service_pricing.py`**

```python
"""Totals for a startbyconnec service selection, grouped by billing cycle."""
from typing import Any

VALID_CYCLES = ("one_time", "monthly", "yearly")


def compute_totals(selections: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    for sel in selections or []:
        cycle = sel.get("billing_cycle")
        if cycle not in VALID_CYCLES:
            cycle = "one_time"
        qty = max(1, int(sel.get("qty") or 1))
        price_min = float(sel.get("price_min") or 0.0)
        price_max_raw = sel.get("price_max")
        price_max = float(price_max_raw) if price_max_raw not in (None, "", 0) else price_min
        bucket = totals.setdefault(cycle, {"min": 0.0, "max": 0.0})
        bucket["min"] += price_min * qty
        bucket["max"] += max(price_min, price_max) * qty
    return totals
```

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/test_services_catalog.py -v`

- [ ] **Step 5: Commit**

```bash
git add api/services/service_pricing.py tests/test_services_catalog.py
git commit -m "feat: per-cycle totals with ranges and quantities for service selections"
```

---

### Task 6: Catalog seed (from the Connec price quotes)

**Files:**
- Create: `api/services/service_catalog_seed.py`
- Modify: `api/main.py` startup (call seed after `seed_builtin_creative_assets` block)
- Test: `tests/test_services_catalog.py` (append)

**Interfaces:**
- Produces: `SEED_ITEMS: list[dict]` and `async seed_service_items(db) -> int` (inserts only when the table is empty; returns inserted count).

- [ ] **Step 1: Write the failing tests**

```python
from api.services.service_catalog_seed import SEED_ITEMS


def test_seed_items_are_complete_and_bilingual():
    assert len(SEED_ITEMS) >= 12
    for item in SEED_ITEMS:
        assert item["name"]["ar"] and item["name"]["he"]
        assert item["description"]["ar"] and item["description"]["he"]
        assert item["category"]["ar"] and item["category"]["he"]
        assert item["billing_cycle"] in ("one_time", "monthly", "yearly")
        assert item["price_min"] > 0
        if item["price_max"] is not None:
            assert item["price_max"] >= item["price_min"]
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_services_catalog.py -v -k seed`

- [ ] **Step 3: Implement `api/services/service_catalog_seed.py`**

```python
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
```

In `api/main.py` startup, after the creative-assets seed block (around line 122), add:

```python
        try:
            async with AsyncSessionLocal() as session:
                await seed_service_items(session)
        except Exception as e:
            log.warning("service catalog seed skipped: %s", e)
```

with the import at the top: `from .services.service_catalog_seed import seed_service_items`.

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/test_services_catalog.py -v`

- [ ] **Step 5: Commit**

```bash
git add api/services/service_catalog_seed.py api/main.py tests/test_services_catalog.py
git commit -m "feat: bilingual service catalog seed from Connec price quotes"
```

---

### Task 7: Telegram company notifier + settings

**Files:**
- Modify: `api/core/config.py` (near existing `telegram_bot_token`, line ~100)
- Create: `api/services/telegram_notify.py`
- Test: `tests/test_services_catalog.py` (append)

**Interfaces:**
- Produces: `async send_company_message(text: str) -> bool` — HTML parse mode, topic-aware, never raises.
- New settings: `telegram_company_chat_id: str = ""`, `telegram_topic_leads: str = ""` (env `TELEGRAM_COMPANY_CHAT_ID`, `TELEGRAM_TOPIC_LEADS` — the first already exists in `api/.env`).

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from api.services import telegram_notify


@pytest.mark.asyncio
async def test_send_company_message_skips_without_config(monkeypatch):
    monkeypatch.setattr(telegram_notify.settings, "telegram_bot_token", "")
    monkeypatch.setattr(telegram_notify.settings, "telegram_company_chat_id", "")
    assert await telegram_notify.send_company_message("hi") is False


@pytest.mark.asyncio
async def test_send_company_message_survives_network_errors(monkeypatch):
    monkeypatch.setattr(telegram_notify.settings, "telegram_bot_token", "t")
    monkeypatch.setattr(telegram_notify.settings, "telegram_company_chat_id", "c")

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("network down")

    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", BoomClient)
    assert await telegram_notify.send_company_message("hi") is False
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_services_catalog.py -v -k telegram`

- [ ] **Step 3: Implement**

In `api/core/config.py` next to the other telegram fields add:

```python
    telegram_company_chat_id: str = ""
    telegram_topic_leads: str = ""
```

Create `api/services/telegram_notify.py`:

```python
"""Fire-and-forget Telegram notifications to the company group."""
import logging

import httpx

from ..core.config import settings
from ..core.external_calls import external_call

log = logging.getLogger(__name__)


async def send_company_message(text: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_company_chat_id or "").strip()
    if not token or not chat_id:
        log.info("Telegram notify skipped: bot token or company chat id not configured")
        return False
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    topic = (settings.telegram_topic_leads or "").strip()
    if topic:
        payload["message_thread_id"] = int(topic)
    try:
        async with external_call("telegram", "send_company_message") as call:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage", json=payload
                )
                call.note(status_code=resp.status_code)
                if resp.status_code != 200:
                    call.fail(f"telegram returned {resp.status_code}")
                    return False
                return True
    except Exception:
        log.warning("Telegram notify failed", exc_info=True)
        return False
```

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/test_services_catalog.py -v`

- [ ] **Step 5: Commit**

```bash
git add api/core/config.py api/services/telegram_notify.py tests/test_services_catalog.py
git commit -m "feat: company Telegram notifier for lead events"
```

---

### Task 8: Owner-or-member suite access helper + sweep

**Files:**
- Create: `api/services/suite_access.py`
- Modify: `api/routers/onboarding.py` (6 owner-check sites — `grep -n "owner_id != current_user.id" api/routers/onboarding.py`)
- Modify: `api/routers/marketing_plans.py:145-150` (`get_owned_suite`)
- Modify: `api/routers/suites.py` (only the `GET /{suite_id}` detail handler's owner check — find with `grep -n "owner_id != current_user.id" api/routers/suites.py` and change only the read-only detail endpoint; leave update/delete/settings owner-only)
- Test: `tests/test_user_gating.py` (append)

**Interfaces:**
- Produces: `async require_suite_access(db, suite_id: str, user: User) -> Suite` — 404 when the suite is missing or the user is neither owner nor member; 403 `account_frozen` when a `funnel` user targets a suite that is not their lead's suite.
- Consumes: `Lead` from Task 4.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import AsyncMock

from fastapi import HTTPException

from api.services.suite_access import require_suite_access


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class AccessDb:
    """Feeds require_suite_access's three sequential queries: suite, member, lead."""

    def __init__(self, suite=None, member=None, lead=None):
        self._answers = [suite, member, lead]
        self._i = 0

    async def execute(self, _query):
        value = self._answers[min(self._i, len(self._answers) - 1)]
        self._i += 1
        return _Result(value)


def _user(uid="u1", status="approved"):
    from api.models.user import User
    return User(id=uid, email=f"{uid}@x.com", full_name=uid, hashed_password="h", approval_status=status)


def _suite(owner="owner-1", sid="s1"):
    from api.models.suite import Suite
    return Suite(id=sid, owner_id=owner, name="S", slug="s")


@pytest.mark.asyncio
async def test_member_gets_access_when_not_owner():
    from api.models.suite import SuiteMember
    db = AccessDb(suite=_suite(), member=SuiteMember(id="m1", suite_id="s1", user_id="u1"))
    suite = await require_suite_access(db, "s1", _user())
    assert suite.id == "s1"


@pytest.mark.asyncio
async def test_stranger_gets_404():
    db = AccessDb(suite=_suite(), member=None)
    with pytest.raises(HTTPException) as exc:
        await require_suite_access(db, "s1", _user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_funnel_user_restricted_to_lead_suite():
    from api.models.suite import SuiteMember
    from api.models.services_catalog import Lead
    member = SuiteMember(id="m1", suite_id="s1", user_id="u1")
    other_lead = Lead(id="l1", user_id="u1", full_name="A", email="a@b.c", phone="0", suite_id="different-suite")
    db = AccessDb(suite=_suite(), member=member, lead=other_lead)
    with pytest.raises(HTTPException) as exc:
        await require_suite_access(db, "s1", _user(status="funnel"))
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_user_gating.py -v -k access`

- [ ] **Step 3: Implement `api/services/suite_access.py`**

```python
"""Owner-or-member access to a suite, with funnel users pinned to their lead suite."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.services_catalog import Lead
from ..models.suite import Suite, SuiteMember
from ..models.user import User


async def require_suite_access(db: AsyncSession, suite_id: str, user: User) -> Suite:
    suite = (await db.execute(select(Suite).where(Suite.id == suite_id))).scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if suite.owner_id != user.id:
        member = (
            await db.execute(
                select(SuiteMember).where(
                    SuiteMember.suite_id == suite_id, SuiteMember.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Suite not found")
    if (user.approval_status or "frozen") == "funnel":
        lead = (
            await db.execute(select(Lead).where(Lead.user_id == user.id))
        ).scalar_one_or_none()
        if not lead or lead.suite_id != suite_id:
            raise HTTPException(status_code=403, detail="account_frozen")
    return suite
```

Sweep — in `api/routers/onboarding.py`, each of the 6 sites currently reads:

```python
    result = await db.execute(select(Suite).where(Suite.id == data.suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
```

Replace each with (adjusting `data.suite_id` vs `suite_id` per handler):

```python
    suite = await require_suite_access(db, data.suite_id, current_user)
```

and add the import `from ..services.suite_access import require_suite_access`.

In `api/routers/marketing_plans.py`, rewrite `get_owned_suite` (line 145) to delegate — every call site keeps working:

```python
async def get_owned_suite(db: AsyncSession, suite_id: str, user: User) -> Suite:
    return await require_suite_access(db, suite_id, user)
```

In `api/routers/suites.py`, change only the read-only `GET /{suite_id}` detail handler to use the helper the same way.

- [ ] **Step 4: Run the whole suite.** `python3 -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/suite_access.py api/routers/onboarding.py api/routers/marketing_plans.py api/routers/suites.py tests/test_user_gating.py
git commit -m "feat: owner-or-member suite access with funnel users pinned to their lead suite"
```

---

### Task 9: One-shot generation guard for funnel users

**Files:**
- Create: `api/services/funnel_guard.py`
- Modify: `api/routers/onboarding.py` (`generate_strategy_endpoint`, line ~178)
- Modify: `api/routers/marketing_plans.py` (handlers for `POST .../marketing-plan/generate` at ~2168, `POST .../social-content-plan/generate` at ~2754, `POST .../paid-content-plan/generate` at ~3023)
- Test: `tests/test_user_gating.py` (append)

**Interfaces:**
- Produces: `block_funnel_regeneration(user, already_generated: bool) -> None` — raises `403 funnel_regeneration_blocked` when `user.approval_status == "funnel"` and output exists.

- [ ] **Step 1: Write the failing tests**

```python
from api.services.funnel_guard import block_funnel_regeneration


def test_funnel_user_blocked_when_output_exists():
    with pytest.raises(HTTPException) as exc:
        block_funnel_regeneration(_user(status="funnel"), already_generated=True)
    assert exc.value.status_code == 403
    assert exc.value.detail == "funnel_regeneration_blocked"


def test_funnel_user_allowed_first_time_and_approved_always():
    block_funnel_regeneration(_user(status="funnel"), already_generated=False)
    block_funnel_regeneration(_user(status="approved"), already_generated=True)
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_user_gating.py -v -k regeneration`

- [ ] **Step 3: Implement**

`api/services/funnel_guard.py`:

```python
"""Cost cap for startbyconnec: funnel users generate each stage exactly once."""
from fastapi import HTTPException

from ..models.user import User


def block_funnel_regeneration(user: User, *, already_generated: bool) -> None:
    if (user.approval_status or "frozen") == "funnel" and already_generated:
        raise HTTPException(status_code=403, detail="funnel_regeneration_blocked")
```

Call sites (add import `from ..services.funnel_guard import block_funnel_regeneration` in both routers):

- `onboarding.generate_strategy_endpoint` — right after the suite is loaded:

```python
    block_funnel_regeneration(current_user, already_generated=bool(suite.strategy))
```

- `marketing_plans` `POST .../marketing-plan/generate` handler — after `get_owned_suite`:

```python
    block_funnel_regeneration(user, already_generated=bool(_deck(suite)))
```

- `POST .../social-content-plan/generate` and `POST .../paid-content-plan/generate` — after the suite loads, guard on that plan's existing key in `suite.strategy` (each handler already reads its plan dict to merge; pass `already_generated=bool(<that dict>)` using the same expression the handler reads).

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add api/services/funnel_guard.py api/routers/onboarding.py api/routers/marketing_plans.py tests/test_user_gating.py
git commit -m "feat: one-shot generation guard for funnel users"
```

---

### Task 10: Funnel API router

**Files:**
- Create: `api/routers/funnel.py`
- Modify: `api/core/config.py` (add `lead_owner_email: str = "w.sholy@gmail.com"`)
- Modify: `api/main.py` (import + `app.include_router(funnel.router, prefix="/api/v1")`)
- Test: `tests/test_funnel_routes.py`

**Interfaces:**
- Produces endpoints (all under `/funnel`):
  - `POST /funnel/register` `{email, password, full_name, phone}` (phone required) → `{access_token, user, lead_id}`; creates user with `approval_status="funnel"` + Lead.
  - `POST /funnel/enroll` (auth) → converts a frozen user to `funnel` + creates their Lead if missing.
  - `GET /funnel/state` (auth) → `{lead, suite_id, steps: {suite_created, request_submitted}}`.
  - `POST /funnel/suite` `{name}` (auth) → creates suite owned by `settings.lead_owner_email` user, adds caller as member, links `lead.suite_id`; 409 when the lead already has a suite.
  - `GET /funnel/catalog` (auth) → active items sorted by `sort_order`.
  - `POST /funnel/recommendations` (auth) → `{recommended_service_ids: [...]}` via one `call_text_ai` pass over the lead suite's brand; cached on `lead.recommendations`.
  - `POST /funnel/service-request` `{items: [{service_id, qty}], customer_notes}` (auth) → snapshots catalog rows, computes totals, stores `ServiceRequest`, marks `lead.progress.request_submitted`, sends Telegram. Returns the serialized request.
- Consumes: Tasks 4, 5, 7 interfaces + `slugify` from `api/routers/suites.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_funnel_routes.py
import pytest
from fastapi import HTTPException

from api.models.services_catalog import Lead, ServiceItem
from api.routers import funnel


def test_register_requires_phone():
    with pytest.raises(Exception):
        funnel.FunnelRegisterRequest(email="a@b.com", password="x12345", full_name="A", phone="")


def test_snapshot_items_validates_and_prices():
    catalog = {
        "s1": ServiceItem(
            id="s1", name={"ar": "أ", "he": "א"}, description={"ar": "-", "he": "-"},
            category={"ar": "ت", "he": "ש"}, billing_cycle="monthly",
            price_min=800, price_max=None, unit=None, is_active=True, sort_order=1,
        )
    }
    items, totals = funnel.snapshot_selection(
        [{"service_id": "s1", "qty": 2}], catalog
    )
    assert items[0]["name"]["ar"] == "أ"
    assert items[0]["qty"] == 2
    assert totals["monthly"] == {"min": 1600.0, "max": 1600.0}


def test_snapshot_selection_rejects_unknown_ids():
    with pytest.raises(HTTPException) as exc:
        funnel.snapshot_selection([{"service_id": "ghost", "qty": 1}], {})
    assert exc.value.status_code == 400


def test_lead_telegram_message_contains_links_and_totals():
    lead = Lead(id="l1", user_id="u1", full_name="Test Person", email="t@p.com", phone="0501112222", suite_id="s9")
    text = funnel.lead_notification_text(
        lead,
        {"one_time": {"min": 9000.0, "max": 12000.0}, "monthly": {"min": 800.0, "max": 800.0}},
        frontend_url="https://cosuite.app",
    )
    assert "Test Person" in text
    assert "0501112222" in text
    assert "https://cosuite.app/admin/leads" in text
    assert "9,000" in text and "12,000" in text
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_funnel_routes.py -v`

- [ ] **Step 3: Implement `api/routers/funnel.py`**

```python
"""Public startbyconnec funnel: register → suite → plans → services → request."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.llm_client import call_text_ai
from ..core.security import create_access_token, get_current_user, hash_password
from ..models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import MemberRole, Suite, SuiteMember, SuiteStatus
from ..models.user import User
from ..services.admin_audit import record_audit_log, serialize_user_public
from ..services.service_pricing import compute_totals
from ..services.telegram_notify import send_company_message
from .suites import slugify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/funnel", tags=["funnel"])


class FunnelRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1)
    phone: str = Field(min_length=6)

    @field_validator("phone")
    @classmethod
    def phone_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("phone required")
        return v.strip()


class FunnelEnrollRequest(BaseModel):
    phone: str | None = None


class FunnelSuiteRequest(BaseModel):
    name: str = Field(min_length=1)


class SelectionItem(BaseModel):
    service_id: str
    qty: int = Field(default=1, ge=1, le=99)


class FunnelServiceRequestIn(BaseModel):
    items: list[SelectionItem] = Field(min_length=1)
    customer_notes: str | None = Field(default=None, max_length=4000)


async def _lead_for(db: AsyncSession, user: User) -> Lead | None:
    return (await db.execute(select(Lead).where(Lead.user_id == user.id))).scalar_one_or_none()


async def _require_lead(db: AsyncSession, user: User) -> Lead:
    lead = await _lead_for(db, user)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found — register via the funnel first")
    return lead


def snapshot_selection(
    selections: list[dict], catalog: dict[str, ServiceItem]
) -> tuple[list[dict], dict]:
    """Validate ids against the active catalog and snapshot names + prices."""
    items: list[dict] = []
    for sel in selections:
        service_id = sel["service_id"] if isinstance(sel, dict) else sel.service_id
        qty = int(sel.get("qty", 1) if isinstance(sel, dict) else sel.qty)
        item = catalog.get(service_id)
        if not item or not item.is_active:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service_id}")
        snapshot = serialize_service_item(item)
        snapshot["qty"] = max(1, qty)
        items.append(snapshot)
    totals = compute_totals(items)
    return items, totals


def _fmt(amount: float) -> str:
    return f"{amount:,.0f}"


def lead_notification_text(lead: Lead, totals: dict, *, frontend_url: str) -> str:
    base = (frontend_url.split(",")[0] or "").strip().rstrip("/")
    cycle_labels = {"one_time": "لمرة واحدة", "monthly": "شهري", "yearly": "سنوي"}
    lines = [
        "🟢 <b>طلب خدمة جديد — startbyconnec</b>",
        f"👤 {lead.full_name}",
        f"📞 {lead.phone}",
        f"✉️ {lead.email}",
        "",
    ]
    for cycle, bucket in totals.items():
        label = cycle_labels.get(cycle, cycle)
        if bucket["min"] == bucket["max"]:
            lines.append(f"💰 {label}: ₪{_fmt(bucket['min'])}")
        else:
            lines.append(f"💰 {label}: ₪{_fmt(bucket['min'])}–{_fmt(bucket['max'])}")
    lines += [
        "",
        f"🔗 {base}/admin/leads?lead={lead.id}",
    ]
    if lead.suite_id:
        lines.append(f"🏠 {base}/suite/{lead.suite_id}/profile")
    return "\n".join(lines)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: FunnelRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        approval_status="funnel",
    )
    db.add(user)
    await db.flush()
    lead = Lead(
        user_id=user.id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        progress={"registered": True},
    )
    db.add(lead)
    await record_audit_log(
        db, action="funnel.register", resource_type="lead", resource_id=lead.id,
        target_user_id=user.id, actor=user, request=request, metadata={"email": user.email},
    )
    await db.commit()
    await db.refresh(user)
    await db.refresh(lead)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": serialize_user_public(user),
        "lead_id": lead.id,
    }


@router.post("/enroll")
async def enroll(
    data: FunnelEnrollRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (current_user.approval_status or "frozen") == "approved":
        raise HTTPException(status_code=400, detail="Account already approved")
    if data.phone and data.phone.strip():
        current_user.phone = data.phone.strip()
    if not current_user.phone:
        raise HTTPException(status_code=400, detail="phone_required")
    current_user.approval_status = "funnel"
    lead = await _lead_for(db, current_user)
    if not lead:
        lead = Lead(
            user_id=current_user.id,
            full_name=current_user.full_name,
            email=current_user.email,
            phone=current_user.phone,
            progress={"registered": True},
        )
        db.add(lead)
    await record_audit_log(
        db, action="funnel.enroll", resource_type="lead", resource_id=lead.id,
        target_user_id=current_user.id, actor=current_user, request=request,
    )
    await db.commit()
    await db.refresh(lead)
    return {"user": serialize_user_public(current_user), "lead_id": lead.id}


@router.get("/state")
async def state(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await _lead_for(db, current_user)
    if not lead:
        return {"lead": None, "suite_id": None, "steps": {}}
    progress = dict(lead.progress or {})
    return {
        "lead": serialize_lead(lead),
        "suite_id": lead.suite_id,
        "steps": {
            "suite_created": bool(lead.suite_id),
            "request_submitted": bool(progress.get("request_submitted")),
        },
    }


@router.post("/suite", status_code=status.HTTP_201_CREATED)
async def create_funnel_suite(
    data: FunnelSuiteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lead = await _require_lead(db, current_user)
    if lead.suite_id:
        raise HTTPException(status_code=409, detail="funnel_suite_exists")
    owner_email = settings.lead_owner_email.strip().lower()
    owner = (
        await db.execute(select(User).where(User.email.ilike(owner_email)))
    ).scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=500, detail=f"Lead owner account missing: {owner_email}")

    base_slug = slugify(data.name) or "suite"
    slug = base_slug
    counter = 1
    while (await db.execute(select(Suite).where(Suite.slug == slug))).scalar_one_or_none():
        slug = f"{base_slug}-{counter}"
        counter += 1

    suite = Suite(owner_id=owner.id, name=data.name, slug=slug, status=SuiteStatus.onboarding)
    db.add(suite)
    await db.flush()
    db.add(SuiteMember(suite_id=suite.id, user_id=current_user.id, role=MemberRole.member, can_chat_ai=True))
    lead.suite_id = suite.id
    lead.progress = {**(lead.progress or {}), "suite_created": True}
    await record_audit_log(
        db, action="funnel.suite_created", resource_type="suite", resource_id=suite.id,
        suite_id=suite.id, target_user_id=current_user.id, actor=current_user, request=request,
    )
    await db.commit()
    await db.refresh(suite)
    return {"id": suite.id, "name": suite.name, "slug": suite.slug, "status": suite.status.value}


@router.get("/catalog")
async def catalog(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ServiceItem).where(ServiceItem.is_active.is_(True)).order_by(ServiceItem.sort_order)
        )
    ).scalars().all()
    return [serialize_service_item(item) for item in rows]


@router.post("/recommendations")
async def recommendations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await _require_lead(db, current_user)
    if lead.recommendations:
        return lead.recommendations
    if not lead.suite_id:
        raise HTTPException(status_code=400, detail="Create the suite first")
    suite = (await db.execute(select(Suite).where(Suite.id == lead.suite_id))).scalar_one_or_none()
    brand = dict(suite.brand or {}) if suite else {}
    rows = (
        await db.execute(select(ServiceItem).where(ServiceItem.is_active.is_(True)))
    ).scalars().all()
    catalog_lines = [
        f"- id={item.id} | {item.name.get('ar', '')} | {item.billing_cycle}"
        for item in rows
    ]
    raw = await call_text_ai(
        max_tokens=400,
        system=(
            "You match marketing/web services to a business. Return ONLY a JSON object: "
            '{"recommended_service_ids": ["..."]} with 3-6 ids from the provided catalog.'
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Business brand JSON:\n{json.dumps(brand, ensure_ascii=False)[:4000]}\n\n"
                f"Catalog:\n" + "\n".join(catalog_lines)
            ),
        }],
    )
    try:
        parsed = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        ids = [i for i in parsed.get("recommended_service_ids", []) if any(r.id == i for r in rows)]
    except Exception:
        log.warning("recommendations parse failed; storing empty list")
        ids = []
    lead.recommendations = {"recommended_service_ids": ids}
    await db.commit()
    return lead.recommendations


@router.post("/service-request", status_code=status.HTTP_201_CREATED)
async def submit_service_request(
    data: FunnelServiceRequestIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lead = await _require_lead(db, current_user)
    rows = (
        await db.execute(select(ServiceItem).where(ServiceItem.is_active.is_(True)))
    ).scalars().all()
    items, totals = snapshot_selection([s.model_dump() for s in data.items], {r.id: r for r in rows})
    req = ServiceRequest(
        lead_id=lead.id,
        items=items,
        totals=totals,
        customer_notes=(data.customer_notes or "").strip() or None,
    )
    db.add(req)
    lead.progress = {**(lead.progress or {}), "request_submitted": True}
    if lead.status == "new":
        lead.status = "in_progress"
    await record_audit_log(
        db, action="funnel.service_request", resource_type="service_request",
        resource_id=req.id, suite_id=lead.suite_id, target_user_id=current_user.id,
        actor=current_user, request=request, metadata={"totals": totals},
    )
    await db.commit()
    await db.refresh(req)
    await send_company_message(lead_notification_text(lead, totals, frontend_url=settings.frontend_url))
    return serialize_service_request(req)
```

In `api/core/config.py` add near `admin_email`:

```python
    lead_owner_email: str = "w.sholy@gmail.com"
```

In `api/main.py`: add `funnel` to the router imports and `app.include_router(funnel.router, prefix="/api/v1")` next to the others.

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/test_funnel_routes.py tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add api/routers/funnel.py api/core/config.py api/main.py tests/test_funnel_routes.py
git commit -m "feat: startbyconnec funnel API — register, suite, catalog, recommendations, service request"
```

---

### Task 11: Admin services + leads endpoints

**Files:**
- Create: `api/routers/admin_catalog.py`
- Modify: `api/main.py` (import + include router)
- Test: `tests/test_admin_catalog.py`

**Interfaces:**
- Produces (all admin-gated via the same `_admin_user` pattern):
  - `GET /admin/services` (all items incl. inactive), `POST /admin/services`, `PATCH /admin/services/{id}`, `DELETE /admin/services/{id}` (soft: sets `is_active=false`).
  - `GET /admin/leads?status=` → list with `has_request` flag; `GET /admin/leads/{id}` → `{lead, user, suite: {id,name,slug}|None, requests: [...]}`; `PATCH /admin/leads/{id}` `{status?, admin_notes?}`; `PATCH /admin/service-requests/{id}` `{status}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_catalog.py
import pytest

from api.routers import admin_catalog


def test_service_item_create_model_requires_bilingual_fields():
    with pytest.raises(Exception):
        admin_catalog.ServiceItemIn(
            name={"ar": "فقط عربي"}, description={"ar": "-", "he": "-"},
            category={"ar": "-", "he": "-"}, billing_cycle="monthly", price_min=10,
        )
    ok = admin_catalog.ServiceItemIn(
        name={"ar": "أ", "he": "א"}, description={"ar": "-", "he": "-"},
        category={"ar": "-", "he": "-"}, billing_cycle="monthly", price_min=10,
    )
    assert ok.price_max is None


def test_lead_patch_model_limits_status():
    with pytest.raises(Exception):
        admin_catalog.LeadPatch(status="everything-is-fine")
    assert admin_catalog.LeadPatch(status="won").status == "won"
```

- [ ] **Step 2: Run — expect FAIL.** `python3 -m pytest tests/test_admin_catalog.py -v`

- [ ] **Step 3: Implement `api/routers/admin_catalog.py`**

```python
"""Admin CRUD for the startbyconnec service catalog + leads inbox."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.services_catalog import (
    Lead,
    ServiceItem,
    ServiceRequest,
    serialize_lead,
    serialize_service_item,
    serialize_service_request,
)
from ..models.suite import Suite
from ..models.user import User
from ..services.admin_audit import record_audit_log, require_super_admin, serialize_user_public

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


async def _admin_user(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    return await require_super_admin(current_user, db)


def _bilingual(value: dict) -> dict:
    if not isinstance(value, dict) or not str(value.get("ar", "")).strip() or not str(value.get("he", "")).strip():
        raise ValueError("both 'ar' and 'he' are required")
    return {"ar": str(value["ar"]).strip(), "he": str(value["he"]).strip()}


class ServiceItemIn(BaseModel):
    name: dict
    description: dict
    category: dict
    billing_cycle: Literal["one_time", "monthly", "yearly"]
    price_min: float = Field(gt=0)
    price_max: float | None = Field(default=None, gt=0)
    unit: dict | None = None
    is_active: bool = True
    sort_order: int = 0

    @field_validator("name", "description", "category")
    @classmethod
    def check_bilingual(cls, v: dict) -> dict:
        return _bilingual(v)


class ServiceItemPatch(BaseModel):
    name: dict | None = None
    description: dict | None = None
    category: dict | None = None
    billing_cycle: Literal["one_time", "monthly", "yearly"] | None = None
    price_min: float | None = Field(default=None, gt=0)
    price_max: float | None = Field(default=None, gt=0)
    unit: dict | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class LeadPatch(BaseModel):
    status: Literal["new", "in_progress", "won", "lost"] | None = None
    admin_notes: str | None = Field(default=None, max_length=8000)


class RequestPatch(BaseModel):
    status: Literal["new", "seen", "handled"]


@router.get("/services")
async def list_services(admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ServiceItem).order_by(ServiceItem.sort_order))).scalars().all()
    return [serialize_service_item(item) for item in rows]


@router.post("/services", status_code=201)
async def create_service(
    payload: ServiceItemIn, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = ServiceItem(**payload.model_dump())
    db.add(item)
    await record_audit_log(
        db, action="admin.service.create", resource_type="service_item",
        actor=admin, request=request, metadata={"name": payload.name},
    )
    await db.commit()
    await db.refresh(item)
    return serialize_service_item(item)


@router.patch("/services/{service_id}")
async def update_service(
    service_id: str, payload: ServiceItemPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = await db.get(ServiceItem, service_id)
    if not item:
        raise HTTPException(status_code=404, detail="Service not found")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("name", "description", "category"):
        if key in updates and updates[key] is not None:
            updates[key] = _bilingual(updates[key])
    for key, value in updates.items():
        setattr(item, key, value)
    await record_audit_log(
        db, action="admin.service.update", resource_type="service_item",
        resource_id=item.id, actor=admin, request=request, metadata=updates,
    )
    await db.commit()
    await db.refresh(item)
    return serialize_service_item(item)


@router.delete("/services/{service_id}")
async def deactivate_service(
    service_id: str, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    item = await db.get(ServiceItem, service_id)
    if not item:
        raise HTTPException(status_code=404, detail="Service not found")
    item.is_active = False
    await record_audit_log(
        db, action="admin.service.deactivate", resource_type="service_item",
        resource_id=item.id, actor=admin, request=request,
    )
    await db.commit()
    return {"ok": True}


@router.get("/leads")
async def list_leads(
    status: str | None = None,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    query = select(Lead).order_by(Lead.created_at.desc())
    if status in ("new", "in_progress", "won", "lost"):
        query = query.where(Lead.status == status)
    leads = (await db.execute(query)).scalars().all()
    request_lead_ids = {
        row for row in (await db.execute(select(ServiceRequest.lead_id))).scalars().all()
    }
    return [
        {**serialize_lead(lead), "has_request": lead.id in request_lead_ids}
        for lead in leads
    ]


@router.get("/leads/{lead_id}")
async def lead_detail(lead_id: str, admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    user = await db.get(User, lead.user_id)
    suite = await db.get(Suite, lead.suite_id) if lead.suite_id else None
    requests = (
        await db.execute(
            select(ServiceRequest).where(ServiceRequest.lead_id == lead.id).order_by(ServiceRequest.created_at.desc())
        )
    ).scalars().all()
    return {
        "lead": serialize_lead(lead),
        "user": serialize_user_public(user) if user else None,
        "suite": {"id": suite.id, "name": suite.name, "slug": suite.slug} if suite else None,
        "requests": [serialize_service_request(r) for r in requests],
    }


@router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: str, payload: LeadPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(lead, key, value)
    await record_audit_log(
        db, action="admin.lead.update", resource_type="lead",
        resource_id=lead.id, actor=admin, request=request, metadata=updates,
    )
    await db.commit()
    await db.refresh(lead)
    return serialize_lead(lead)


@router.patch("/service-requests/{request_id}")
async def update_service_request(
    request_id: str, payload: RequestPatch, request: Request,
    admin: User = Depends(_admin_user), db: AsyncSession = Depends(get_db),
):
    req = await db.get(ServiceRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = payload.status
    await record_audit_log(
        db, action="admin.service_request.update", resource_type="service_request",
        resource_id=req.id, actor=admin, request=request, metadata={"status": payload.status},
    )
    await db.commit()
    return serialize_service_request(req)
```

Register in `api/main.py`: `from .routers import admin_catalog` + `app.include_router(admin_catalog.router, prefix="/api/v1")`.

- [ ] **Step 4: Run — PASS.** `python3 -m pytest tests/test_admin_catalog.py tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add api/routers/admin_catalog.py api/main.py tests/test_admin_catalog.py
git commit -m "feat: admin services CRUD and leads inbox endpoints"
```

---

### Task 12: Frontend API client + auth types

**Files:**
- Modify: `web/src/store/auth.ts` (AuthUser)
- Modify: `web/src/lib/api.ts` (types + `funnel` module + admin services/leads methods + `approval_status` on AdminUser update type)

**Interfaces:**
- Produces (consumed by Tasks 13–17):
  - `AuthUser.approval_status?: "approved" | "frozen" | "funnel"`, `AuthUser.phone?: string | null`
  - Types: `ServiceItem`, `FunnelLead`, `FunnelState`, `ServiceRequestOut`, `AdminLead`, `AdminLeadDetail`
  - `api.funnel.register/enroll/state/createSuite/catalog/recommendations/submitRequest`
  - `api.admin.listServices/createService/updateService/deactivateService/listLeads/leadDetail/updateLead/updateServiceRequest`
  - `api.auth.signup` accepts optional `phone`.

- [ ] **Step 1: Implement**

In `web/src/store/auth.ts` extend the interface:

```typescript
export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  phone?: string | null;
  is_active?: boolean;
  is_verified?: boolean;
  is_super_admin?: boolean;
  approval_status?: "approved" | "frozen" | "funnel";
}
```

In `web/src/lib/api.ts` add the types near the other exported types:

```typescript
export type BillingCycle = "one_time" | "monthly" | "yearly";

export interface ServiceItem {
  id: string;
  name: Record<string, string>;
  description: Record<string, string>;
  category: Record<string, string>;
  billing_cycle: BillingCycle;
  price_min: number;
  price_max: number | null;
  unit: Record<string, string> | null;
  is_active: boolean;
  sort_order: number;
}

export type CycleTotals = Partial<Record<BillingCycle, { min: number; max: number }>>;

export interface FunnelLead {
  id: string;
  suite_id: string | null;
  full_name: string;
  email: string;
  phone: string;
  status: string;
  progress: Record<string, boolean>;
}

export interface FunnelState {
  lead: FunnelLead | null;
  suite_id: string | null;
  steps: { suite_created?: boolean; request_submitted?: boolean };
}

export interface ServiceRequestOut {
  id: string;
  lead_id: string;
  items: (ServiceItem & { qty: number })[];
  totals: CycleTotals;
  customer_notes: string | null;
  status: "new" | "seen" | "handled";
  created_at: string;
}

export interface AdminLead extends FunnelLead {
  user_id: string;
  source: string;
  admin_notes: string | null;
  has_request?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminLeadDetail {
  lead: AdminLead;
  user: { id: string; email: string; full_name: string; phone?: string | null } | null;
  suite: { id: string; name: string; slug: string } | null;
  requests: ServiceRequestOut[];
}
```

Extend `api.auth.signup`'s payload type with `phone?: string`. Add inside `export const api = { ... }`:

```typescript
  funnel: {
    register: (data: { email: string; password: string; full_name: string; phone: string }) =>
      request<{ access_token: string; user: import("@/store/auth").AuthUser; lead_id: string }>(
        "/funnel/register", { method: "POST", body: JSON.stringify(data) }),
    enroll: (data?: { phone?: string }) => request<{ user: import("@/store/auth").AuthUser; lead_id: string }>(
      "/funnel/enroll", { method: "POST", body: JSON.stringify(data || {}) }),
    state: () => request<FunnelState>("/funnel/state"),
    createSuite: (data: { name: string }) =>
      request<{ id: string; name: string; slug: string; status: string }>(
        "/funnel/suite", { method: "POST", body: JSON.stringify(data) }),
    catalog: () => request<ServiceItem[]>("/funnel/catalog"),
    recommendations: () =>
      request<{ recommended_service_ids: string[] }>("/funnel/recommendations", { method: "POST" }),
    submitRequest: (data: { items: { service_id: string; qty: number }[]; customer_notes?: string }) =>
      request<ServiceRequestOut>("/funnel/service-request", { method: "POST", body: JSON.stringify(data) }),
  },
```

and inside the existing `admin: { ... }` module:

```typescript
    listServices: () => request<ServiceItem[]>("/admin/services"),
    createService: (data: Omit<ServiceItem, "id">) =>
      request<ServiceItem>("/admin/services", { method: "POST", body: JSON.stringify(data) }),
    updateService: (id: string, data: Partial<Omit<ServiceItem, "id">>) =>
      request<ServiceItem>(`/admin/services/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    deactivateService: (id: string) =>
      request<{ ok: boolean }>(`/admin/services/${id}`, { method: "DELETE" }),
    listLeads: (status?: string) =>
      request<AdminLead[]>(`/admin/leads${status ? `?status=${status}` : ""}`),
    leadDetail: (id: string) => request<AdminLeadDetail>(`/admin/leads/${id}`),
    updateLead: (id: string, data: { status?: string; admin_notes?: string }) =>
      request<AdminLead>(`/admin/leads/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    updateServiceRequest: (id: string, data: { status: "new" | "seen" | "handled" }) =>
      request<ServiceRequestOut>(`/admin/service-requests/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
```

Also extend the existing `admin.updateUser` `Pick<...>` union with `"approval_status"` (add `approval_status?: string` to the `AdminUser` type if not present).

- [ ] **Step 2: Type-check**

Run: `cd web && npx tsc --noEmit`
Expected: only the 2 pre-existing `.next/types/*2.ts` errors.

- [ ] **Step 3: Commit (inside `web/`)**

```bash
cd web && git add src/store/auth.ts src/lib/api.ts
git commit -m "feat: funnel + admin catalog API client, approval_status on auth user"
```

---

### Task 13: FrozenScreen + dashboard layout gating + funnel chrome

**Files:**
- Create: `web/src/components/FrozenScreen.tsx`
- Create: `web/src/components/funnel/FunnelChrome.tsx`
- Modify: `web/src/app/(dashboard)/layout.tsx`
- Modify: `web/src/lib/i18n/translations.ts` (keys below, in ar/he/en blocks)

**Interfaces:**
- Consumes: `AuthUser.approval_status`, `api.funnel.state` (Task 12).
- Produces: frozen users see only FrozenScreen; funnel users see FunnelChrome (progress header, no sidebar) wrapping the normal pages.

i18n keys (add to each language block; Arabic values shown, translate for he/en):

```
"frozen.title": "التطبيق حالياً بمرحلة إطلاق مغلقة"
"frozen.body": "OneShare غير مفتوح حالياً لمستخدمين خارجيين. بياناتك محفوظة وسنتواصل معك عند الفتح."
"frozen.cta": "ابدأ مع Connec — خطة تسويق وعرض سعر مجاني"
"frozen.logout": "تسجيل الخروج"
"funnel.steps.suite": "إنشاء السوت"
"funnel.steps.plan": "الخطة التسويقية"
"funnel.steps.work": "خطة العمل"
"funnel.steps.services": "الخدمات والأسعار"
"funnel.steps.request": "طلب الخدمة"
"funnel.next": "التالي"
```

- [ ] **Step 1: Implement `web/src/components/FrozenScreen.tsx`**

```tsx
"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/BrandMark";
import { useT } from "@/lib/i18n/LanguageContext";
import { useAuthStore } from "@/store/auth";

export function FrozenScreen() {
  const t = useT();
  const router = useRouter();
  const logout = useAuthStore((s) => s.logout);
  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="max-w-lg w-full rounded-2xl border border-border bg-card p-8 text-center space-y-5">
        <div className="flex justify-center"><BrandMark size="sm" /></div>
        <h1 className="text-2xl font-bold">{t("frozen.title")}</h1>
        <p className="text-muted-foreground leading-relaxed">{t("frozen.body")}</p>
        <Button asChild size="lg" className="w-full">
          <Link href="/startbyconnec">{t("frozen.cta")}</Link>
        </Button>
        <button
          onClick={() => { logout(); router.push("/login"); }}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          {t("frozen.logout")}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement `web/src/components/funnel/FunnelChrome.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/BrandMark";
import { useT } from "@/lib/i18n/LanguageContext";
import { api, FunnelState } from "@/lib/api";

const STEP_KEYS = ["suite", "plan", "work", "services", "request"] as const;

function stepHrefs(suiteId: string | null): Record<(typeof STEP_KEYS)[number], string> {
  return {
    suite: "/suite/new",
    plan: suiteId ? `/suite/${suiteId}/marketing-plan` : "/suite/new",
    work: suiteId ? `/suite/${suiteId}/work-plans` : "/suite/new",
    services: "/startbyconnec/services",
    request: "/startbyconnec/request",
  };
}

function currentIndex(pathname: string): number {
  if (pathname.startsWith("/startbyconnec/request")) return 4;
  if (pathname.startsWith("/startbyconnec/services")) return 3;
  if (pathname.includes("/work-plans")) return 2;
  if (pathname.includes("/marketing-plan")) return 1;
  return 0;
}

export function FunnelChrome({ children }: { children: React.ReactNode }) {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<FunnelState | null>(null);

  useEffect(() => {
    api.funnel.state().then(setState).catch(() => setState(null));
  }, [pathname]);

  const suiteId = state?.suite_id ?? null;
  const hrefs = stepHrefs(suiteId);
  const idx = currentIndex(pathname);
  const nextKey = STEP_KEYS[Math.min(idx + 1, STEP_KEYS.length - 1)];
  const nextDisabled = idx === 0 && !suiteId;

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="border-b border-border bg-card/60 sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <BrandMark size="sm" />
          <ol className="hidden md:flex items-center gap-2 text-xs">
            {STEP_KEYS.map((key, i) => (
              <li
                key={key}
                className={`px-2 py-1 rounded-full border ${
                  i === idx
                    ? "border-indigo-500 text-indigo-500 font-semibold"
                    : i < idx
                      ? "border-border text-muted-foreground line-through"
                      : "border-border text-muted-foreground"
                }`}
              >
                {i + 1}. {t(`funnel.steps.${key}`)}
              </li>
            ))}
          </ol>
          {idx < STEP_KEYS.length - 1 && (
            <Button size="sm" disabled={nextDisabled} onClick={() => router.push(hrefs[nextKey])}>
              {t("funnel.next")}
            </Button>
          )}
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
```

- [ ] **Step 3: Gate in `web/src/app/(dashboard)/layout.tsx`**

Right after the `if (!user) return null;` line, add:

```tsx
  if (user.approval_status === "frozen" && !user.is_super_admin) {
    return <FrozenScreen />;
  }
  if (user.approval_status === "funnel" && !user.is_super_admin) {
    return <FunnelChrome>{children}</FunnelChrome>;
  }
```

with imports `import { FrozenScreen } from "@/components/FrozenScreen";` and `import { FunnelChrome } from "@/components/funnel/FunnelChrome";`. Note the layout already refreshes the user via `api.auth.me()` on mount, so a status change takes effect on next load.

- [ ] **Step 4: Add the i18n keys** to `web/src/lib/i18n/translations.ts` in the `ar`, `he`, and `en` blocks (Hebrew: „האפליקציה בשלב השקה סגור", „OneShare עדיין לא פתוח למשתמשים חיצוניים...", „התחילו עם Connec — תוכנית שיווק והצעת מחיר חינם", „התנתקות", steps: „הקמת סוויטה", „תוכנית שיווק", „תוכנית עבודה", „שירותים ומחירים", „בקשת שירות", „הבא"; English equivalents).

- [ ] **Step 5: Verify + commit**

Run: `cd web && npx tsc --noEmit` (only the 2 known errors) — then:

```bash
cd web && git add src/components/FrozenScreen.tsx src/components/funnel/FunnelChrome.tsx "src/app/(dashboard)/layout.tsx" src/lib/i18n/translations.ts
git commit -m "feat: frozen screen with startbyconnec CTA + funnel chrome in dashboard layout"
```

---

### Task 14: Signup phone (optional) + frozen redirect after auth

**Files:**
- Modify: `web/src/app/(auth)/signup/page.tsx` (add optional phone input; pass `phone` to `api.auth.signup`)
- Modify: `web/src/app/(auth)/login/page.tsx` (no change to redirect logic needed — the dashboard layout gates frozen users — only verify)

**Steps:**

- [ ] **Step 1:** In the signup page add a phone `useState` + input styled like the existing name/email inputs, placed after the name field, with i18n keys `"auth.phone": "رقم الهاتف (اختياري)"` (+ he/en). Pass `phone: phone.trim() || undefined` in the `api.auth.signup({...})` call at line ~75.
- [ ] **Step 2:** Manual check: `cd web && npm run dev` → sign up a fresh user → expect to land on the FrozenScreen with the startbyconnec CTA.
- [ ] **Step 3: Commit**

```bash
cd web && git add "src/app/(auth)/signup/page.tsx" src/lib/i18n/translations.ts
git commit -m "feat: optional phone on signup"
```

---

### Task 15: startbyconnec public pages (landing + register)

**Files:**
- Create: `web/src/app/startbyconnec/layout.tsx`
- Create: `web/src/app/startbyconnec/page.tsx`
- Create: `web/src/app/startbyconnec/register/page.tsx`
- Modify: `web/src/lib/i18n/translations.ts`

**Interfaces:**
- Consumes: `api.funnel.register`, `api.funnel.enroll`, `useAuthStore.setAuth`.
- Produces: `/startbyconnec` (public landing), `/startbyconnec/register`. After register/enroll → `router.push("/suite/new")`.

- [ ] **Step 1: Layout** — `web/src/app/startbyconnec/layout.tsx`:

```tsx
"use client";
import { BrandMark } from "@/components/BrandMark";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

export default function StartByConnecLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="border-b border-border">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <BrandMark size="sm" />
          <LanguageSwitcher placement="bottom" />
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

- [ ] **Step 2: Landing** — `web/src/app/startbyconnec/page.tsx`: hero + three benefit cards + CTA. Use i18n keys:

```
"sbc.hero.title": "خطة تسويق كاملة لمصلحتك — مجاناً"
"sbc.hero.subtitle": "سجّل، أنشئ ملف علامتك، واحصل على خطة تسويقية وخطة عمل وعرض أسعار مخصص من Connec."
"sbc.hero.cta": "ابدأ الآن"
"sbc.benefit1.title": "ملف علامة كامل"        / body: "نبحث عن مصلحتك ونبني ملف العلامة تلقائياً."
"sbc.benefit2.title": "خطة تسويقية وخطة عمل"  / body: "خطة تسويق وخطة محتوى جاهزة للتنفيذ."
"sbc.benefit3.title": "عرض أسعار مخصص"        / body: "اختر الخدمات المناسبة واستلم عرض سعر واضح."
```

```tsx
"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/LanguageContext";

export default function StartByConnecLanding() {
  const t = useT();
  const benefits = ["benefit1", "benefit2", "benefit3"] as const;
  return (
    <div className="max-w-5xl mx-auto px-4 py-16 text-center space-y-10">
      <div className="space-y-4">
        <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight">{t("sbc.hero.title")}</h1>
        <p className="text-lg text-muted-foreground max-w-2xl mx-auto">{t("sbc.hero.subtitle")}</p>
        <Button asChild size="lg">
          <Link href="/startbyconnec/register">{t("sbc.hero.cta")}</Link>
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-3 text-start">
        {benefits.map((key) => (
          <div key={key} className="rounded-xl border border-border bg-card p-5">
            <h3 className="font-semibold mb-1">{t(`sbc.${key}.title`)}</h3>
            <p className="text-sm text-muted-foreground">{t(`sbc.${key}.body`)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Register** — `web/src/app/startbyconnec/register/page.tsx`. Fields: name, email, **phone (required)**, password. If a user is already logged in (`useAuthStore`), show a "متابعة بحسابك" button that calls `api.funnel.enroll()` then refreshes `me` into the store and pushes `/suite/new`. Keys: `"sbc.register.title": "سجّل للبدء"`, `"sbc.register.phone": "رقم الهاتف"`, `"sbc.register.submit": "ابدأ ببناء السوت"`, `"sbc.register.continue": "متابعة بحسابك الحالي"`.

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/LanguageContext";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

export default function FunnelRegisterPage() {
  const t = useT();
  const router = useRouter();
  const { user, setAuth, setUser } = useAuthStore();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const res = await api.funnel.register({ email, password, full_name: name, phone });
      setAuth(res.access_token, res.user);
      router.push("/suite/new");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function continueExisting() {
    setBusy(true); setError("");
    try {
      // logged-in users without a stored phone must provide one (backend 400s otherwise)
      const res = await api.funnel.enroll(phone.trim() ? { phone: phone.trim() } : undefined);
      setUser(res.user);
      router.push("/suite/new");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const inputCls = "w-full rounded-lg border border-border bg-background px-3 py-2";
  return (
    <div className="max-w-md mx-auto px-4 py-12">
      <h1 className="text-2xl font-bold mb-6 text-center">{t("sbc.register.title")}</h1>
      {user ? (
        <Button onClick={continueExisting} disabled={busy} className="w-full mb-4">
          {t("sbc.register.continue")}
        </Button>
      ) : null}
      <form onSubmit={submit} className="space-y-3">
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("auth.fullName")} required />
        <input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("auth.email")} required />
        <input className={inputCls} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("sbc.register.phone")} required minLength={6} />
        <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t("auth.password")} required minLength={6} />
        {error && <p className="text-sm text-red-500">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">{t("sbc.register.submit")}</Button>
      </form>
    </div>
  );
}
```

(If `auth.fullName` / `auth.email` / `auth.password` keys don't exist in translations, reuse the actual keys found in the signup page.)

- [ ] **Step 4: Verify + commit**

`cd web && npx tsc --noEmit`, load `/startbyconnec` in dev, then:

```bash
cd web && git add src/app/startbyconnec src/lib/i18n/translations.ts
git commit -m "feat: startbyconnec landing and funnel registration"
```

---

### Task 16: Wizard funnel branch

**Files:**
- Modify: `web/src/app/(dashboard)/suite/new/page.tsx:676` (suite creation call)

**Interfaces:**
- Consumes: `api.funnel.createSuite` (Task 12), `useAuthStore` user.

- [ ] **Step 1:** In `NewSuitePage`, read the user once near the top of the component (the file already imports the auth store — if not: `import { useAuthStore } from "@/store/auth";`):

```tsx
  const authUser = useAuthStore((s) => s.user);
  const isFunnelUser = authUser?.approval_status === "funnel";
```

Replace line 676:

```tsx
      const suite = await api.suites.create({ name: suiteName });
```

with:

```tsx
      const suite = isFunnelUser
        ? await api.funnel.createSuite({ name: suiteName })
        : await api.suites.create({ name: suiteName });
```

`api.funnel.createSuite` returns `{id, name, slug, status}` which is shape-compatible with the fields used downstream (`suite.id`). If a 409 `funnel_suite_exists` comes back, catch it and route the user forward instead of showing an error:

```tsx
      // inside the catch around suite creation:
      if (err instanceof ApiError && err.status === 409) {
        const state = await api.funnel.state();
        if (state.suite_id) { router.push(`/suite/${state.suite_id}/marketing-plan`); return; }
      }
```

(import `ApiError` from `@/lib/api` if not already imported).

- [ ] **Step 2:** Verify: `cd web && npx tsc --noEmit`.

- [ ] **Step 3: Commit**

```bash
cd web && git add "src/app/(dashboard)/suite/new/page.tsx"
git commit -m "feat: wizard creates funnel suites via /funnel/suite for funnel users"
```

---

### Task 17: Funnel services + request pages

**Files:**
- Create: `web/src/app/startbyconnec/services/page.tsx`
- Create: `web/src/app/startbyconnec/request/page.tsx`
- Create: `web/src/app/startbyconnec/done/page.tsx`
- Create: `web/src/lib/funnelSelection.ts` (selection persisted in sessionStorage between the two pages)
- Modify: `web/src/lib/i18n/translations.ts`

**Interfaces:**
- Consumes: `api.funnel.catalog/recommendations/submitRequest`, `ServiceItem`, `CycleTotals`.
- Produces: `loadSelection(): Record<string, number>`, `saveSelection(sel)` in `funnelSelection.ts`.

i18n keys (ar shown; add he/en):

```
"sbc.services.title": "مقترح الخدمات والأسعار"
"sbc.services.subtitle": "اختر الخدمات المناسبة لمصلحتك — الأسعار بالشيكل قبل الضريبة."
"sbc.services.recommended": "موصى لعملك"
"sbc.services.cycle.one_time": "لمرة واحدة"
"sbc.services.cycle.monthly": "شهري"
"sbc.services.cycle.yearly": "سنوي"
"sbc.services.continue": "متابعة لطلب الخدمة"
"sbc.request.title": "طلب خدمة جديد"
"sbc.request.notes": "ملاحظات (اختياري)"
"sbc.request.back": "رجوع لتعديل الاختيار"
"sbc.request.submit": "إرسال الطلب"
"sbc.done.title": "استلمنا طلبك!"
"sbc.done.body": "فريق Connec رح يتواصل معك خلال يوم عمل."
```

- [ ] **Step 1: `web/src/lib/funnelSelection.ts`**

```typescript
const KEY = "sbc_selection";

export function loadSelection(): Record<string, number> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

export function saveSelection(sel: Record<string, number>): void {
  sessionStorage.setItem(KEY, JSON.stringify(sel));
}
```

- [ ] **Step 2: Services page** — grouped by category, checkbox select, qty stepper when `unit` set, recommended badge, price / range + cycle badge, sticky continue button. Complete component:

```tsx
"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useLanguage, useT } from "@/lib/i18n/LanguageContext";
import { api, ServiceItem } from "@/lib/api";
import { loadSelection, saveSelection } from "@/lib/funnelSelection";

function price(item: ServiceItem): string {
  const min = item.price_min.toLocaleString();
  return item.price_max ? `₪${min}–${item.price_max.toLocaleString()}` : `₪${min}`;
}

export default function FunnelServicesPage() {
  const t = useT();
  const { lang } = useLanguage();
  const router = useRouter();
  const catalogLang = lang === "he" ? "he" : "ar";
  const [items, setItems] = useState<ServiceItem[]>([]);
  const [recommended, setRecommended] = useState<string[]>([]);
  const [selection, setSelection] = useState<Record<string, number>>({});

  useEffect(() => {
    setSelection(loadSelection());
    api.funnel.catalog().then(setItems).catch(() => setItems([]));
    api.funnel.recommendations()
      .then((r) => setRecommended(r.recommended_service_ids || []))
      .catch(() => setRecommended([]));
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, ServiceItem[]>();
    for (const item of items) {
      const key = item.category[catalogLang] || item.category.ar;
      map.set(key, [...(map.get(key) || []), item]);
    }
    return [...map.entries()];
  }, [items, catalogLang]);

  function toggle(id: string) {
    setSelection((prev) => {
      const next = { ...prev };
      if (next[id]) delete next[id];
      else next[id] = 1;
      saveSelection(next);
      return next;
    });
  }

  function setQty(id: string, qty: number) {
    setSelection((prev) => {
      const next = { ...prev, [id]: Math.max(1, qty) };
      saveSelection(next);
      return next;
    });
  }

  const count = Object.keys(selection).length;

  return (
    <div className="max-w-4xl mx-auto px-4 py-10 pb-28 space-y-8">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold">{t("sbc.services.title")}</h1>
        <p className="text-muted-foreground">{t("sbc.services.subtitle")}</p>
      </div>
      {grouped.map(([category, rows]) => (
        <section key={category} className="space-y-3">
          <h2 className="text-lg font-semibold">{category}</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {rows.map((item) => {
              const selected = Boolean(selection[item.id]);
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => toggle(item.id)}
                  className={`rounded-xl border p-4 text-start transition ${
                    selected ? "border-indigo-500 ring-1 ring-indigo-500 bg-indigo-500/5" : "border-border bg-card"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold">{item.name[catalogLang] || item.name.ar}</h3>
                    {recommended.includes(item.id) && (
                      <span className="shrink-0 text-[11px] rounded-full bg-emerald-500/10 text-emerald-600 px-2 py-0.5">
                        {t("sbc.services.recommended")}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">
                    {item.description[catalogLang] || item.description.ar}
                  </p>
                  <div className="flex items-center gap-2 mt-3 text-sm">
                    <span className="font-bold">{price(item)}</span>
                    <span className="rounded-full border border-border px-2 py-0.5 text-xs">
                      {t(`sbc.services.cycle.${item.billing_cycle}`)}
                    </span>
                    {item.unit && (
                      <span className="text-xs text-muted-foreground">
                        {item.unit[catalogLang] || item.unit.ar}
                      </span>
                    )}
                  </div>
                  {selected && item.unit && (
                    <div className="flex items-center gap-2 mt-3" onClick={(e) => e.stopPropagation()}>
                      <Button size="sm" variant="outline" onClick={() => setQty(item.id, (selection[item.id] || 1) - 1)}>-</Button>
                      <span className="min-w-8 text-center">{selection[item.id]}</span>
                      <Button size="sm" variant="outline" onClick={() => setQty(item.id, (selection[item.id] || 1) + 1)}>+</Button>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </section>
      ))}
      <div className="fixed bottom-0 inset-x-0 border-t border-border bg-background/95 backdrop-blur p-4">
        <div className="max-w-4xl mx-auto">
          <Button className="w-full" size="lg" disabled={!count} onClick={() => router.push("/startbyconnec/request")}>
            {t("sbc.services.continue")} ({count})
          </Button>
        </div>
      </div>
    </div>
  );
}
```

(Check `useLanguage`'s actual export shape in `web/src/lib/i18n/LanguageContext.tsx` — if it exposes `lang` differently, adapt the one line.)

- [ ] **Step 3: Request page** — recompute totals client-side (same rule as backend: qty floored to 1, `price_max || price_min`), show per-cycle summary, notes textarea, back + submit:

```tsx
"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useLanguage, useT } from "@/lib/i18n/LanguageContext";
import { api, BillingCycle, ServiceItem } from "@/lib/api";
import { loadSelection } from "@/lib/funnelSelection";

const CYCLES: BillingCycle[] = ["one_time", "monthly", "yearly"];

export default function FunnelRequestPage() {
  const t = useT();
  const { lang } = useLanguage();
  const catalogLang = lang === "he" ? "he" : "ar";
  const router = useRouter();
  const [items, setItems] = useState<ServiceItem[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selection = useMemo(() => loadSelection(), []);

  useEffect(() => {
    api.funnel.catalog().then(setItems).catch(() => setItems([]));
  }, []);

  const chosen = items.filter((i) => selection[i.id]);
  const totals = useMemo(() => {
    const acc: Record<string, { min: number; max: number }> = {};
    for (const item of chosen) {
      const qty = Math.max(1, selection[item.id] || 1);
      const bucket = (acc[item.billing_cycle] ||= { min: 0, max: 0 });
      bucket.min += item.price_min * qty;
      bucket.max += (item.price_max ?? item.price_min) * qty;
    }
    return acc;
  }, [chosen, selection]);

  async function submit() {
    setBusy(true); setError("");
    try {
      await api.funnel.submitRequest({
        items: chosen.map((i) => ({ service_id: i.id, qty: Math.max(1, selection[i.id] || 1) })),
        customer_notes: notes.trim() || undefined,
      });
      sessionStorage.removeItem("sbc_selection");
      router.push("/startbyconnec/done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const fmt = (n: number) => `₪${n.toLocaleString()}`;
  return (
    <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
      <h1 className="text-3xl font-bold text-center">{t("sbc.request.title")}</h1>
      <div className="rounded-xl border border-border bg-card divide-y divide-border">
        {chosen.map((item) => (
          <div key={item.id} className="flex items-center justify-between p-3 text-sm">
            <span>
              {item.name[catalogLang] || item.name.ar}
              {selection[item.id] > 1 ? ` ×${selection[item.id]}` : ""}
            </span>
            <span className="text-muted-foreground">{t(`sbc.services.cycle.${item.billing_cycle}`)}</span>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
        {CYCLES.filter((c) => totals[c]).map((cycle) => (
          <div key={cycle} className="flex items-center justify-between font-semibold">
            <span>{t(`sbc.services.cycle.${cycle}`)}</span>
            <span>
              {totals[cycle].min === totals[cycle].max
                ? fmt(totals[cycle].min)
                : `${fmt(totals[cycle].min)}–${fmt(totals[cycle].max)}`}
            </span>
          </div>
        ))}
      </div>
      <textarea
        className="w-full rounded-lg border border-border bg-background px-3 py-2 min-h-24"
        placeholder={t("sbc.request.notes")}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      {error && <p className="text-sm text-red-500">{error}</p>}
      <div className="flex gap-3">
        <Button variant="outline" className="flex-1" onClick={() => router.push("/startbyconnec/services")}>
          {t("sbc.request.back")}
        </Button>
        <Button className="flex-1" disabled={busy || !chosen.length} onClick={submit}>
          {t("sbc.request.submit")}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Done page** — simple confirmation:

```tsx
"use client";
import { useT } from "@/lib/i18n/LanguageContext";

export default function FunnelDonePage() {
  const t = useT();
  return (
    <div className="max-w-md mx-auto px-4 py-24 text-center space-y-3">
      <div className="text-5xl">🎉</div>
      <h1 className="text-2xl font-bold">{t("sbc.done.title")}</h1>
      <p className="text-muted-foreground">{t("sbc.done.body")}</p>
    </div>
  );
}
```

- [ ] **Step 5: Verify + commit**

`cd web && npx tsc --noEmit`, then:

```bash
cd web && git add src/app/startbyconnec src/lib/funnelSelection.ts src/lib/i18n/translations.ts
git commit -m "feat: funnel services proposal, request summary, and confirmation pages"
```

---

### Task 18: Admin UI — approval controls, services page, leads page

**Files:**
- Modify: `web/src/app/(dashboard)/admin/page.tsx` (users table: status pill + Approve/Freeze buttons + phone column; nav cards to the two new pages)
- Create: `web/src/app/(dashboard)/admin/services/page.tsx`
- Create: `web/src/app/(dashboard)/admin/leads/page.tsx`

**Interfaces:**
- Consumes: Task 12 `api.admin.*` methods.

- [ ] **Step 1: Users table controls.** In the admin users table rows add: a phone cell (`{u.phone || "—"}`), a status pill showing `u.approval_status`, and a per-row action reusing the existing `busyUserId` pattern:

```tsx
<Button
  size="sm"
  variant={u.approval_status === "approved" ? "outline" : "default"}
  disabled={busyUserId === u.id}
  onClick={async () => {
    setBusyUserId(u.id);
    try {
      const next = u.approval_status === "approved" ? "frozen" : "approved";
      await api.admin.updateUser(u.id, { approval_status: next });
      setUsers((prev) => prev.map((x) => (x.id === u.id ? { ...x, approval_status: next } : x)));
    } finally {
      setBusyUserId(null);
    }
  }}
>
  {u.approval_status === "approved" ? "Freeze" : "Approve"}
</Button>
```

Also add two link cards near the top of the page: `Link href="/admin/services"` («الخدمات — كتالوج startbyconnec») and `Link href="/admin/leads"` («الليدات — طلبات الخدمة»).

- [ ] **Step 2: Services page** (`admin/services/page.tsx`): table of all items (name.ar / name.he / category.ar / cycle / price or range / unit / active), inline edit via a side form (create + edit share it). Complete lean implementation: hold `form` state mirroring `ServiceItemIn` (two text inputs per bilingual field), `api.admin.createService` / `updateService` / `deactivateService`, refresh list after save. Guard the page with the same `user.is_super_admin` check pattern the admin page uses.

- [ ] **Step 3: Leads page** (`admin/leads/page.tsx`): left list (name, phone, status pill, has_request badge, created date; status filter buttons), right detail on click via `api.admin.leadDetail`: contact block (mailto/tel links), suite link (`/suite/{id}/profile` when present), each request rendered as items table (name.ar, qty, cycle, price) + per-cycle totals + customer notes + request status select (`api.admin.updateServiceRequest`), lead status select + admin notes textarea saved via `api.admin.updateLead`. Support `?lead=<id>` query param to auto-open a lead (Telegram deep link target).

- [ ] **Step 4: Verify + commit**

`cd web && npx tsc --noEmit`, manual dev-server pass over both pages, then:

```bash
cd web && git add "src/app/(dashboard)/admin"
git commit -m "feat: admin approval controls, services catalog editor, leads inbox"
```

---

### Task 19: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Backend suite** — `python3 -m pytest tests/ -q` → all green.
- [ ] **Step 2: Frontend** — `cd web && npx tsc --noEmit` (only the 2 known `.next` errors) and `npm run build` succeeds.
- [ ] **Step 3: Manual E2E (dev servers: uvicorn + npm run dev):**
  1. Log in as an existing non-owner user → FrozenScreen with CTA appears; API calls return 403 `account_frozen`.
  2. Log in as `w.sholy@gmail.com` → normal dashboard.
  3. `/startbyconnec` → register with phone → wizard opens under FunnelChrome → suite created (verify in DB: `owner_id` = w.sholy's user id, caller is a member, lead.suite_id set).
  4. Marketing plan generate works once; second generate returns 403 `funnel_regeneration_blocked`.
  5. Services page shows the seeded bilingual catalog with recommended badges; request submit → done page; Telegram message arrives in the company group (env loaded: `set -a; source api/.env; set +a`).
  6. Admin → leads shows the lead with request details + suite link; admin → services edit a price and see it reflected on the funnel services page.
- [ ] **Step 4: Commit any fixes; final commits in both repos.**
