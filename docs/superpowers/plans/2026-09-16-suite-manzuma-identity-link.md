# Suite ↔ Manzuma Identity Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a co-Suite suite and a Manzuma business the same entity, so any product can read that business's strategy and no product keeps its own copy of platform tokens.

**Architecture:** Manzuma accounts becomes the identity source — co-Suite verifies the caller's Manzuma session server-to-server and resolves a local user and suite from it, behind a feature flag, with password sign-in still working underneath. co-Suite publishes one read-only internal endpoint that returns a stable strategy summary to other products, authenticated by a per-module service key. Platform tokens move to the accounts vault; co-Suite asks for them at use time and stores none.

**Tech Stack:** FastAPI + SQLAlchemy async + pydantic-settings + httpx + pytest (co-Suite API); Next.js 16 + TypeScript + vitest (OneShare and co-Suite web).

**Spec:** `docs/superpowers/specs/2026-09-16-suite-manzuma-identity-link-design.md`

## Global Constraints

- **Three repositories.** `devObuzt/co-suite` (this one), `devObuzt/co-suite-web`, `devObuzt/manzuma-oneshare`. Every task names its repository. Never edit `devObuzt/Afkarwts` — it is a live production system.
- **This repo has no Alembic.** Schema comes from `Base.metadata.create_all` plus explicit `ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements in `api/main.py` (see lines 63–85). Follow that idiom exactly; do not introduce a migration tool in this plan.
- **No secret ever reaches a log or a browser.** Not a session cookie, not a bearer token, not a Meta access token, not a service key. Log ids only.
- **`MANZUMA_SSO` starts `false`.** Every step ships dark; the flag is flipped only in Task 10.
- **Password sign-in keeps working** for the whole plan. Removing it is out of scope here.
- **The endpoint contract is fixed** by the spec: `GET /internal/v1/suite?organization_id=…`, `Authorization: Bearer <module key>`, and the JSON shape in the spec's section 2. Do not add fields to it in this plan.
- **Accounts base URL:** `https://accounts.manzuma.app`. Session endpoint: `GET /api/session`. Vault endpoint: `POST /api/internal/integrations/token`.
- **Arabic is the product language of these repos' comments and commit messages in OneShare, English in co-Suite.** Match the file you are editing.
- **QA:** `AGENTS.md` in this repo requires the `cosuite-qa` skill for user-facing or operational changes before calling work complete.

## File Structure

**co-suite (API)**

| File | Responsibility |
|---|---|
| `api/core/config.py` (modify) | Four new settings: accounts URL, service key, SSO flag, internal keys map |
| `api/models/user.py` (modify) | `manzuma_user_id` column |
| `api/models/suite.py` (modify) | `organization_id` column |
| `api/main.py` (modify) | Two `ALTER TABLE` statements; register the internal router |
| `api/services/manzuma_accounts.py` (create) | Verifying a Manzuma session and reading vault tokens over HTTP |
| `api/services/manzuma_link.py` (create) | Pure rules: which local user, which suite, which approval status |
| `api/core/service_auth.py` (create) | Per-module key auth for inbound internal calls |
| `api/routers/internal.py` (create) | `GET /internal/v1/suite` |
| `api/services/suite_summary.py` (create) | Pure mapping from the suite row to the published contract |
| `api/core/security.py` (modify) | Session branch inside `get_current_user`, behind the flag |
| `api/routers/connections.py` (modify) | Stop returning tokens to the browser; read from the vault |

**manzuma-oneshare**

| File | Responsibility |
|---|---|
| `src/lib/suite-client.ts` (create) | Typed HTTP client for the contract |
| `src/lib/strategy.ts` (create) | The `strategy` port plus its fake |
| `tests/suiteClient.test.ts` (create) | Mapping, 404, failure behaviour |

**co-suite-web**

| File | Responsibility |
|---|---|
| `src/lib/manzumaSession.ts` (create) | Read the Manzuma session on the client |
| `src/app/link-suite/page.tsx` (create) | The explicit "link this suite to this business" confirmation |

---

### Task 1: Settings and schema columns

**Repository:** `co-suite`

**Files:**
- Modify: `api/core/config.py`
- Modify: `api/models/user.py`
- Modify: `api/models/suite.py`
- Modify: `api/main.py` (the `ALTER TABLE` block that starts at line 63)
- Test: `tests/test_manzuma_link_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.manzuma_accounts_url: str`, `settings.manzuma_service_key: str`, `settings.manzuma_sso: bool`, `settings.internal_service_keys: str`; `User.manzuma_user_id: Optional[str]`; `Suite.organization_id: Optional[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manzuma_link_schema.py
from api.core.config import settings
from api.models.suite import Suite
from api.models.user import User


def test_settings_carry_the_manzuma_link_configuration():
    assert settings.manzuma_accounts_url == "https://accounts.manzuma.app"
    assert settings.manzuma_sso is False  # ships dark
    assert settings.manzuma_service_key == ""
    assert settings.internal_service_keys == ""


def test_link_columns_exist_and_are_unique():
    user_column = User.__table__.columns["manzuma_user_id"]
    suite_column = Suite.__table__.columns["organization_id"]

    assert user_column.unique is True
    assert user_column.nullable is True
    assert suite_column.unique is True
    assert suite_column.nullable is True
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_manzuma_link_schema.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'manzuma_accounts_url'`

- [ ] **Step 3: Add the settings**

In `api/core/config.py`, inside `class Settings(BaseSettings)`, next to the other integration settings:

```python
    # Manzuma link (see docs/superpowers/specs/2026-09-16-suite-manzuma-identity-link-design.md)
    manzuma_accounts_url: str = "https://accounts.manzuma.app"
    manzuma_service_key: str = ""      # our key when we call the accounts vault
    manzuma_sso: bool = False          # flip only after the path is proven
    internal_service_keys: str = ""    # "oneshare:key,heartbeat:key" — products calling us
```

- [ ] **Step 4: Add the columns**

In `api/models/user.py`, inside `class User`:

```python
    # Set the first time this person signs in with a Manzuma session. Nullable
    # because the link happens per user, not in one migration night.
    manzuma_user_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
```

In `api/models/suite.py`, inside `class Suite`:

```python
    # The Manzuma business this suite IS. One suite per business — the unique
    # constraint is what makes "suite = business" true rather than aspirational.
    organization_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
```

- [ ] **Step 5: Add the two ALTER statements**

In `api/main.py`, in the existing list of startup statements (the one containing `"ALTER TABLE suites ADD COLUMN IF NOT EXISTS strategy JSON"`), append:

```python
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS manzuma_user_id VARCHAR",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_manzuma_user_id ON users (manzuma_user_id)",
                    "ALTER TABLE suites ADD COLUMN IF NOT EXISTS organization_id VARCHAR",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_suites_organization_id ON suites (organization_id)",
```

- [ ] **Step 6: Run the test**

Run: `pytest tests/test_manzuma_link_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Run the whole suite to prove nothing else moved**

Run: `pytest -q`
Expected: the same result as before this task — no new failures.

- [ ] **Step 8: Commit**

```bash
git add api/core/config.py api/models/user.py api/models/suite.py api/main.py tests/test_manzuma_link_schema.py
git commit -m "feat(link): settings and columns for the Manzuma identity link"
```

---

### Task 2: The accounts client

**Repository:** `co-suite`

**Files:**
- Create: `api/services/manzuma_accounts.py`
- Test: `tests/test_manzuma_accounts_client.py`

**Interfaces:**
- Consumes: `settings.manzuma_accounts_url`, `settings.manzuma_service_key` (Task 1).
- Produces:
  - `@dataclass(frozen=True) ManzumaSub(module: str, plan: str, status: str)`
  - `@dataclass(frozen=True) ManzumaOrg(id: str, name: str, role: str, subscriptions: tuple[ManzumaSub, ...])`
  - `@dataclass(frozen=True) ManzumaSession(user_id: str, email: str | None, phone: str | None, name: str | None, organizations: tuple[ManzumaOrg, ...])`
  - `async def verify_session(cookie: str | None, bearer: str | None) -> ManzumaSession | None`
  - `async def vault_token(organization_id: str, provider: str, asset_id: str | None = None) -> str | None`
  - `def _cache_key(cookie: str | None, bearer: str | None) -> str` (hash only — used by the test)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manzuma_accounts_client.py
import httpx
import pytest

from api.services import manzuma_accounts as ma


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_verify_session_maps_the_accounts_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/session"
        assert request.headers["cookie"] == "manzuma.session=abc"
        return httpx.Response(200, json={
            "authenticated": True,
            "user": {"id": "u1", "email": "W@Example.com", "phone": "+972501234567", "name": "Wisam"},
            "organizations": [
                {
                    "id": "org1", "name": "Afkar", "slug": "afkar", "role": "owner",
                    "subscriptions": [
                        {"organizationId": "org1", "module": "cosuite", "plan": "pro", "status": "active"}
                    ],
                }
            ],
        })

    session = await ma.verify_session(cookie="manzuma.session=abc", bearer=None, transport=_transport(handler))

    assert session.user_id == "u1"
    assert session.email == "W@Example.com"
    assert session.organizations[0].id == "org1"
    assert session.organizations[0].role == "owner"
    assert session.organizations[0].subscriptions[0].module == "cosuite"
    assert session.organizations[0].subscriptions[0].status == "active"


@pytest.mark.asyncio
async def test_verify_session_returns_none_when_not_authenticated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"authenticated": False})

    assert await ma.verify_session(cookie="x=1", bearer=None, transport=_transport(handler)) is None


@pytest.mark.asyncio
async def test_verify_session_returns_none_when_accounts_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    assert await ma.verify_session(cookie="x=1", bearer=None, transport=_transport(handler)) is None


def test_cache_key_never_contains_the_credential():
    key = ma._cache_key("manzuma.session=supersecret", None)
    assert "supersecret" not in key
    assert len(key) == 64  # sha256 hex
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_manzuma_accounts_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.manzuma_accounts'`

- [ ] **Step 3: Write the client**

```python
# api/services/manzuma_accounts.py
"""Talking to Manzuma accounts: who is signed in, and which token to act with.

Accounts owns identity and holds every platform token encrypted. This module is
the only place in co-Suite that calls it, so the credential handling stays in
one file: nothing here is ever logged, and the cache is keyed by a hash.
"""
import hashlib
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..core.config import settings

TIMEOUT = httpx.Timeout(10.0)
SESSION_TTL_SECONDS = 30
# What accounts calls a live subscription. Anything else (cancelled, past_due)
# is not a reason to unfreeze an account.
ACTIVE_SUBSCRIPTION_STATUSES = ("active", "trialing")


@dataclass(frozen=True)
class ManzumaSub:
    module: str
    plan: str
    status: str


@dataclass(frozen=True)
class ManzumaOrg:
    id: str
    name: str
    role: str
    subscriptions: tuple[ManzumaSub, ...]

    def subscribes_to(self, module: str) -> bool:
        """An active subscription for this product, in this business."""
        return any(
            sub.module == module and sub.status in ACTIVE_SUBSCRIPTION_STATUSES
            for sub in self.subscriptions
        )


@dataclass(frozen=True)
class ManzumaSession:
    user_id: str
    email: Optional[str]
    phone: Optional[str]
    name: Optional[str]
    organizations: tuple[ManzumaOrg, ...]


_session_cache: dict[str, tuple[float, Optional[ManzumaSession]]] = {}


def _cache_key(cookie: Optional[str], bearer: Optional[str]) -> str:
    return hashlib.sha256(f"{cookie or ''}|{bearer or ''}".encode()).hexdigest()


def _parse(payload: dict) -> Optional[ManzumaSession]:
    if not payload.get("authenticated") or not payload.get("user"):
        return None
    user = payload["user"]
    orgs = tuple(
        ManzumaOrg(
            id=org.get("id", ""),
            name=org.get("name", ""),
            role=org.get("role", "member"),
            subscriptions=tuple(
                ManzumaSub(
                    module=sub.get("module", ""),
                    plan=sub.get("plan", ""),
                    status=sub.get("status", ""),
                )
                for sub in org.get("subscriptions") or []
            ),
        )
        for org in payload.get("organizations") or []
        if org.get("id")
    )
    return ManzumaSession(
        user_id=user.get("id", ""),
        email=user.get("email"),
        phone=user.get("phone"),
        name=user.get("name"),
        organizations=orgs,
    )


async def verify_session(
    cookie: Optional[str],
    bearer: Optional[str],
    transport: Optional[httpx.BaseTransport] = None,
) -> Optional[ManzumaSession]:
    """Ask accounts who this caller is. Returns None for anything but a yes."""
    if not cookie and not bearer:
        return None

    key = _cache_key(cookie, bearer)
    cached = _session_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < SESSION_TTL_SECONDS:
        return cached[1]

    headers = {}
    if cookie:
        headers["cookie"] = cookie
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            res = await client.get(f"{settings.manzuma_accounts_url}/api/session", headers=headers)
        session = _parse(res.json()) if res.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        # Accounts unreachable or nonsense body. The caller falls back to the
        # legacy path; we never guess an identity.
        session = None

    _session_cache[key] = (now, session)
    return session


async def vault_token(
    organization_id: str,
    provider: str,
    asset_id: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> Optional[str]:
    """A provider token for this business, from the encrypted vault.

    We never store what this returns. Not in the database, not in a log.
    """
    if not settings.manzuma_service_key:
        return None

    body = {"organizationId": organization_id, "provider": provider}
    if asset_id:
        body["assetId"] = asset_id

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            res = await client.post(
                f"{settings.manzuma_accounts_url}/api/internal/integrations/token",
                headers={"authorization": f"Bearer {settings.manzuma_service_key}"},
                json=body,
            )
        if res.status_code != 200:
            return None
        return res.json().get("accessToken")
    except (httpx.HTTPError, ValueError):
        return None
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_manzuma_accounts_client.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/manzuma_accounts.py tests/test_manzuma_accounts_client.py
git commit -m "feat(link): client for the accounts session and token vault"
```

---

### Task 3: The resolution rules

**Repository:** `co-suite`

**Files:**
- Create: `api/services/manzuma_link.py`
- Test: `tests/test_manzuma_link_rules.py`

**Interfaces:**
- Consumes: `ManzumaSession`, `ManzumaOrg` (Task 2).
- Produces:
  - `def normalize_email(value: str | None) -> str | None`
  - `def normalize_phone(value: str | None) -> str | None`
  - `def approval_for(org: ManzumaOrg | None) -> str`
  - `def suite_decision(linked_suite_id: str | None, unlinked_owned_suite_ids: list[str]) -> tuple[str, str | None]` returning one of `("use", suite_id)`, `("offer_link", suite_id)`, `("create", None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manzuma_link_rules.py
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSub
from api.services.manzuma_link import approval_for, normalize_email, normalize_phone, suite_decision


def test_email_and_phone_normalize_for_matching():
    assert normalize_email("  W@Example.COM ") == "w@example.com"
    assert normalize_email(None) is None
    assert normalize_phone("050-123-4567") == "0501234567"
    assert normalize_phone("+972 50 123 4567") == "+972501234567"
    assert normalize_phone("") is None


def test_approval_follows_the_cosuite_subscription():
    live = ManzumaSub(module="cosuite", plan="pro", status="active")
    cancelled = ManzumaSub(module="cosuite", plan="pro", status="cancelled")
    elsewhere = ManzumaSub(module="oneshare", plan="starter", status="active")

    assert approval_for(ManzumaOrg("o1", "Afkar", "owner", (live,))) == "approved"
    assert approval_for(ManzumaOrg("o2", "Old", "owner", (cancelled,))) == "frozen"
    assert approval_for(ManzumaOrg("o3", "Other", "owner", (elsewhere,))) == "frozen"
    assert approval_for(None) == "frozen"


def test_suite_decision_prefers_the_linked_suite():
    assert suite_decision("s1", ["s2"]) == ("use", "s1")


def test_suite_decision_offers_a_single_unlinked_suite():
    assert suite_decision(None, ["s2"]) == ("offer_link", "s2")


def test_suite_decision_creates_when_there_is_nothing_or_too_much_to_choose():
    assert suite_decision(None, []) == ("create", None)
    assert suite_decision(None, ["s2", "s3"]) == ("create", None)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_manzuma_link_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.manzuma_link'`

- [ ] **Step 3: Write the rules**

```python
# api/services/manzuma_link.py
"""The rules that decide which local row a Manzuma session belongs to.

Pure on purpose: every branch here is a decision about somebody's account or
somebody's business, and those are the branches worth testing without a
database in the way.
"""
import re
from typing import Optional

from .manzuma_accounts import ManzumaOrg


def normalize_email(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().lower()
    return cleaned or None


def normalize_phone(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return None
    keep_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    return f"+{digits}" if keep_plus else digits


def approval_for(org: Optional[ManzumaOrg]) -> str:
    """A new person is approved when their business pays for co-Suite.

    The freeze rule does not change — its input does: a subscription instead of
    a manual decision.
    """
    return "approved" if org and org.subscribes_to("cosuite") else "frozen"


def suite_decision(
    linked_suite_id: Optional[str],
    unlinked_owned_suite_ids: list[str],
) -> tuple[str, Optional[str]]:
    """Which suite this business works with.

    Linking is never automatic when there is a choice to get wrong: one
    unlinked suite is an offer the person confirms, more than one is a
    decision only they can make.
    """
    if linked_suite_id:
        return ("use", linked_suite_id)
    if len(unlinked_owned_suite_ids) == 1:
        return ("offer_link", unlinked_owned_suite_ids[0])
    return ("create", None)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_manzuma_link_rules.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/manzuma_link.py tests/test_manzuma_link_rules.py
git commit -m "feat(link): rules for resolving a session to a user and a suite"
```

---

### Task 4: Resolving the local user from a session

**Repository:** `co-suite`

**Files:**
- Modify: `api/services/manzuma_link.py`
- Test: `tests/test_manzuma_link_resolve_user.py`

**Interfaces:**
- Consumes: Task 3's helpers, `ManzumaSession` (Task 2), `User` model (Task 1).
- Produces: `async def resolve_user(db, session: ManzumaSession, org: ManzumaOrg | None) -> User` — returns an existing adopted user or a newly created one, always with `manzuma_user_id` set. Adoption by email or phone happens **only** when the session carries `email_verified` / `phone_verified` from accounts; otherwise a new account is created. `ManzumaSession` carries both flags, defaulting to `False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manzuma_link_resolve_user.py
import pytest

from api.models.user import User
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSession, ManzumaSub
from api.services.manzuma_link import resolve_user


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeDB:
    """Answers each select in the order resolve_user asks: id, email, phone."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.added = []
        self.commits = 0

    async def execute(self, *_args, **_kwargs):
        return _Result(self.answers.pop(0) if self.answers else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


SESSION = ManzumaSession(
    user_id="u1", email="W@Example.com", phone="050-123-4567", name="Wisam", organizations=()
)
ORG = ManzumaOrg(
    id="o1", name="Afkar", role="owner",
    subscriptions=(ManzumaSub(module="cosuite", plan="pro", status="active"),),
)


@pytest.mark.asyncio
async def test_returns_the_already_linked_user_without_writing():
    linked = User(id="local1", email="w@example.com", hashed_password="x", full_name="Wisam")
    linked.manzuma_user_id = "u1"
    db = FakeDB([linked])

    user = await resolve_user(db, SESSION, ORG)

    assert user is linked
    assert db.added == []


@pytest.mark.asyncio
async def test_adopts_a_legacy_user_by_email_and_keeps_its_status():
    legacy = User(id="local2", email="w@example.com", hashed_password="x", full_name="Wisam")
    legacy.approval_status = "frozen"
    db = FakeDB([None, legacy])

    user = await resolve_user(db, SESSION, ORG)

    assert user.manzuma_user_id == "u1"
    assert user.approval_status == "frozen"  # adoption never promotes
    assert db.commits == 1


@pytest.mark.asyncio
async def test_creates_an_approved_user_when_the_business_pays_for_cosuite():
    db = FakeDB([None, None, None])

    user = await resolve_user(db, SESSION, ORG)

    assert user.manzuma_user_id == "u1"
    assert user.email == "w@example.com"
    assert user.approval_status == "approved"
    assert user.hashed_password == ""  # no usable password
    assert db.added == [user]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_manzuma_link_resolve_user.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_user'`

- [ ] **Step 3: Implement `resolve_user`**

Append to `api/services/manzuma_link.py`:

```python
from sqlalchemy import select

from ..models.user import User
from .manzuma_accounts import ManzumaSession


async def resolve_user(db, session: ManzumaSession, org: Optional[ManzumaOrg]) -> User:
    """The local row for this Manzuma person, adopting a legacy one if it is theirs.

    Order matters: the explicit link first, then email, then phone. A person who
    signed up here years ago with the same email keeps their suites, their
    history and their approval status — they just stop having a password.
    """
    found = (await db.execute(select(User).where(User.manzuma_user_id == session.user_id))).scalar_one_or_none()
    if found:
        return found

    email = normalize_email(session.email)
    if email:
        found = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if not found:
        phone = normalize_phone(session.phone)
        if phone:
            found = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()

    if found:
        found.manzuma_user_id = session.user_id
        await db.commit()
        await db.refresh(found)
        return found

    created = User(
        email=email or f"{session.user_id}@manzuma.local",
        hashed_password="",
        full_name=session.name or email or "Manzuma user",
        phone=normalize_phone(session.phone),
    )
    created.manzuma_user_id = session.user_id
    created.approval_status = approval_for(org)
    created.is_verified = True
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_manzuma_link_resolve_user.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/manzuma_link.py tests/test_manzuma_link_resolve_user.py
git commit -m "feat(link): resolve a Manzuma session to a local user"
```

---

### Task 5: The session branch in `get_current_user`

**Repository:** `co-suite`

**Files:**
- Modify: `api/core/security.py` (the `get_current_user` dependency at the end of the file)
- Test: `tests/test_manzuma_session_auth.py`

**Interfaces:**
- Consumes: `verify_session` (Task 2), `resolve_user` (Task 4), `settings.manzuma_sso` (Task 1).
- Produces: `get_current_user` accepting a Manzuma session; `MANZUMA_COOKIE_NAMES` tuple used by the web app task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manzuma_session_auth.py
import pytest
from fastapi import HTTPException

from api.core import security
from api.core.config import settings
from api.models.user import User
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSession, ManzumaSub


class _Request:
    def __init__(self, cookie=None):
        self.headers = {"cookie": cookie} if cookie else {}
        self.method = "GET"
        self.url = type("U", (), {"path": "/api/v1/suites/"})()


SESSION = ManzumaSession(
    user_id="u1", email="w@example.com", phone=None, name="Wisam",
    organizations=(
        ManzumaOrg(
            id="o1", name="Afkar", role="owner",
            subscriptions=(ManzumaSub(module="cosuite", plan="pro", status="active"),),
        ),
    ),
)


@pytest.mark.asyncio
async def test_session_branch_is_off_while_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", False)
    called = False

    async def _verify(**_kwargs):
        nonlocal called
        called = True
        return SESSION

    monkeypatch.setattr(security, "verify_session", _verify)

    assert await security.manzuma_user_or_none(_Request("manzuma.session=abc"), db=None) is None
    assert called is False


@pytest.mark.asyncio
async def test_session_branch_resolves_a_user_when_the_flag_is_on(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)
    user = User(id="local1", email="w@example.com", hashed_password="", full_name="Wisam")
    user.approval_status = "approved"

    async def _verify(cookie=None, bearer=None):
        return SESSION

    async def _resolve(_db, session, org):
        assert session.user_id == "u1"
        assert org.id == "o1"
        return user

    monkeypatch.setattr(security, "verify_session", _verify)
    monkeypatch.setattr(security, "resolve_user", _resolve)

    assert await security.manzuma_user_or_none(_Request("manzuma.session=abc"), db=None) is user


@pytest.mark.asyncio
async def test_a_request_without_a_session_falls_through(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)

    async def _verify(cookie=None, bearer=None):
        return None

    monkeypatch.setattr(security, "verify_session", _verify)

    assert await security.manzuma_user_or_none(_Request(), db=None) is None


@pytest.mark.asyncio
async def test_a_frozen_user_is_still_blocked_on_a_product_path(monkeypatch):
    monkeypatch.setattr(settings, "manzuma_sso", True)
    frozen = User(id="local2", email="x@example.com", hashed_password="", full_name="X")
    frozen.approval_status = "frozen"

    with pytest.raises(HTTPException) as err:
        security.enforce_status(frozen, "GET", "/api/v1/suites/")

    assert err.value.status_code == 403
    assert err.value.detail == "account_frozen"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_manzuma_session_auth.py -v`
Expected: FAIL — `AttributeError: module 'api.core.security' has no attribute 'manzuma_user_or_none'`

- [ ] **Step 3: Implement the branch**

In `api/core/security.py`, add the imports and two helpers, then use them inside `get_current_user`:

```python
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..services.manzuma_accounts import verify_session
from ..services.manzuma_link import resolve_user

# The session cookie accounts sets on .manzuma.app, production and local.
MANZUMA_COOKIE_NAMES = ("__Secure-manzuma.session", "manzuma.session")

optional_bearer = HTTPBearer(auto_error=False)


def enforce_status(user: User, method: str, path: str) -> User:
    """The frozen/funnel gate, unchanged — extracted so both branches share it."""
    if not user.is_super_admin and not frozen_path_allowed(user.approval_status or "frozen", method, path):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_frozen")
    return user


async def manzuma_user_or_none(request: Request, db) -> Optional[User]:
    """The Manzuma identity for this request, or None to try the legacy path."""
    if not settings.manzuma_sso:
        return None

    cookie = request.headers.get("cookie")
    if cookie and not any(name in cookie for name in MANZUMA_COOKIE_NAMES):
        cookie = None
    if not cookie:
        return None

    session = await verify_session(cookie=cookie, bearer=None)
    if not session:
        return None

    org = session.organizations[0] if session.organizations else None
    return await resolve_user(db, session, org)
```

Then change `get_current_user` so the session branch is tried first and the JWT branch stays exactly as it is:

```python
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    linked = await manzuma_user_or_none(request, db)
    if linked:
        return enforce_status(linked, request.method, request.url.path)

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

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
    return enforce_status(user, request.method, request.url.path)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_manzuma_session_auth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the whole suite — the bearer change touches every authenticated route**

Run: `pytest -q`
Expected: no new failures. If a test asserted a 403 from a missing `Authorization` header, it now sees 401; fix the test only if the old status was the accident, and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add api/core/security.py tests/test_manzuma_session_auth.py
git commit -m "feat(link): accept a Manzuma session in get_current_user, behind the flag"
```

---

### Task 6: Service-key auth for inbound internal calls

**Repository:** `co-suite`

**Files:**
- Create: `api/core/service_auth.py`
- Test: `tests/test_internal_service_auth.py`

**Interfaces:**
- Consumes: `settings.internal_service_keys` (Task 1).
- Produces: `def calling_module(authorization: str | None) -> str | None`, and the FastAPI dependency `async def require_module(request: Request) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_internal_service_auth.py
import pytest
from fastapi import HTTPException

from api.core import service_auth
from api.core.config import settings


class _Request:
    def __init__(self, authorization=None):
        self.headers = {"authorization": authorization} if authorization else {}


def test_calling_module_matches_one_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc,heartbeat:def")

    assert service_auth.calling_module("Bearer abc") == "oneshare"
    assert service_auth.calling_module("Bearer def") == "heartbeat"


def test_calling_module_rejects_everything_else(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")

    assert service_auth.calling_module("Bearer wrong") is None
    assert service_auth.calling_module("abc") is None
    assert service_auth.calling_module(None) is None
    assert service_auth.calling_module("Bearer ") is None


def test_no_keys_configured_means_no_access(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "")

    assert service_auth.calling_module("Bearer abc") is None


@pytest.mark.asyncio
async def test_dependency_raises_401_without_a_valid_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_keys", "oneshare:abc")

    assert await service_auth.require_module(_Request("Bearer abc")) == "oneshare"

    with pytest.raises(HTTPException) as err:
        await service_auth.require_module(_Request("Bearer nope"))
    assert err.value.status_code == 401
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_internal_service_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.core.service_auth'`

- [ ] **Step 3: Implement**

```python
# api/core/service_auth.py
"""Per-module keys for the internal API other Manzuma products call.

One key per product, so a leaked OneShare key cannot be used to impersonate
HeartBeat and can be rotated on its own. Same shape accounts uses for its vault.
"""
import hmac
from typing import Optional

from fastapi import HTTPException, Request, status

from .config import settings


def _key_map() -> dict[str, str]:
    pairs = {}
    for item in (settings.internal_service_keys or "").split(","):
        name, _, key = item.partition(":")
        if name.strip() and key.strip():
            pairs[name.strip()] = key.strip()
    return pairs


def calling_module(authorization: Optional[str]) -> Optional[str]:
    """The product behind this key, or None. Constant-time comparison."""
    header = authorization or ""
    presented = header[7:] if header.startswith("Bearer ") else ""
    if not presented:
        return None

    for name, key in _key_map().items():
        if hmac.compare_digest(presented, key):
            return name
    return None


async def require_module(request: Request) -> str:
    module = calling_module(request.headers.get("authorization"))
    if not module:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return module
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_internal_service_auth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/core/service_auth.py tests/test_internal_service_auth.py
git commit -m "feat(link): per-module key auth for the internal API"
```

---

### Task 7: The strategy summary and its endpoint

**Repository:** `co-suite`

**Files:**
- Create: `api/services/suite_summary.py`
- Create: `api/routers/internal.py`
- Modify: `api/main.py` (router registration near line 199)
- Test: `tests/test_suite_summary.py`

**Interfaces:**
- Consumes: `require_module` (Task 6), `Suite` model (Task 1).
- Produces: `def suite_summary(suite: Suite) -> dict` — the published contract; `GET /internal/v1/suite?organization_id=`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suite_summary.py
from api.models.suite import Suite
from api.services.suite_summary import suite_summary


def _suite(**over) -> Suite:
    suite = Suite(id="s1", owner_id="u1", name="Afkar", slug="afkar")
    suite.organization_id = "o1"
    suite.brand = {"description": "healthy food", "tagline": "eat well", "services": ["catering"], "logo_url": "x"}
    suite.strategy = {
        "marketing_plan": {
            "audience": {
                "problem": "no time to cook",
                "demographics": {"age": "25-45", "gender": "all", "language": "ar", "social_status": "working"},
                "personas": [{"name": "Sara", "age": 34, "profession": "nurse", "needs": "fast", "challenges": "shifts"}],
            },
            "keywords": ["healthy", "delivery"],
            "content_themes": ["recipes"],
        },
        "marketing_message": "eat well without cooking",
        "language": "ar",
    }
    for key, value in over.items():
        setattr(suite, key, value)
    return suite


def test_summary_publishes_the_contract_shape():
    out = suite_summary(_suite())

    assert out["suite"]["id"] == "s1"
    assert out["brand"]["tagline"] == "eat well"
    assert out["audience"]["language"] == "ar"
    assert out["audience"]["demographics"]["age"] == "25-45"
    assert out["audience"]["personas"][0]["name"] == "Sara"
    assert out["audience"]["keywords"] == ["healthy", "delivery"]
    assert out["marketing_message"] == "eat well without cooking"
    assert out["content_themes"] == ["recipes"]


def test_summary_survives_a_suite_with_no_strategy_yet():
    out = suite_summary(_suite(strategy=None, brand=None))

    assert out["suite"]["id"] == "s1"
    assert out["brand"] == {"description": "", "tagline": "", "services": []}
    assert out["audience"]["personas"] == []
    assert out["marketing_message"] == ""


def test_summary_never_leaks_connections_or_tokens():
    suite = _suite()
    suite.connections = {"meta_user_token": "EAA-secret", "facebook": {"page_access_token": "EAA-secret"}}

    assert "EAA-secret" not in str(suite_summary(suite))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_suite_summary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.suite_summary'`

- [ ] **Step 3: Write the mapper**

```python
# api/services/suite_summary.py
"""The suite, in the shape other products are allowed to depend on.

The `strategy` column is co-Suite's internal blob and changes whenever its
generators change. This function is the published contract, so a change there
stays here instead of breaking OneShare.
"""
from typing import Any

from ..models.suite import Suite


def _plan(suite: Suite) -> dict[str, Any]:
    strategy = suite.strategy or {}
    return strategy.get("marketing_plan") or {}


def suite_summary(suite: Suite) -> dict[str, Any]:
    strategy = suite.strategy or {}
    brand = suite.brand or {}
    plan = _plan(suite)
    audience = plan.get("audience") or {}
    demographics = audience.get("demographics") or {}

    return {
        "suite": {
            "id": suite.id,
            "name": suite.name,
            "status": getattr(suite.status, "value", suite.status) or "onboarding",
            "updated_at": suite.updated_at.isoformat() if suite.updated_at else None,
        },
        "brand": {
            "description": brand.get("description") or "",
            "tagline": brand.get("tagline") or "",
            "services": brand.get("services") or [],
        },
        "audience": {
            "language": demographics.get("language") or strategy.get("language") or "",
            "demographics": {
                "age": demographics.get("age") or "",
                "gender": demographics.get("gender") or "",
                "social_status": demographics.get("social_status") or "",
            },
            "problem": audience.get("problem") or "",
            "personas": audience.get("personas") or [],
            "keywords": plan.get("keywords") or [],
        },
        "marketing_message": strategy.get("marketing_message") or "",
        "content_themes": plan.get("content_themes") or [],
    }
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_suite_summary.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the router**

```python
# api/routers/internal.py
"""The internal API other Manzuma products call. Service keys only, read only."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.service_auth import require_module
from ..models.suite import Suite
from ..services.suite_summary import suite_summary

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.get("/suite")
async def read_suite(
    organization_id: str = Query(..., min_length=1),
    module: str = Depends(require_module),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Suite).where(Suite.organization_id == organization_id))
    suite = result.scalar_one_or_none()
    if not suite:
        # Not an error: the business simply has no suite yet, and the caller
        # turns this into an invitation to create one.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_suite")

    print(f"[internal] {module} → suite {suite.id} org={organization_id}")
    return suite_summary(suite)
```

Register it in `api/main.py` next to the other routers, **without** the `/api/v1` prefix:

```python
app.include_router(internal.router)
```

and add `internal` to the routers import list at the top of the file.

- [ ] **Step 6: Run the suite**

Run: `pytest -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add api/services/suite_summary.py api/routers/internal.py api/main.py tests/test_suite_summary.py
git commit -m "feat(link): internal endpoint publishing the suite strategy summary"
```

---

### Task 8: OneShare reads the suite

**Repository:** `manzuma-oneshare`

**Files:**
- Create: `src/lib/suite-client.ts`
- Create: `src/lib/strategy.ts`
- Test: `tests/suiteClient.test.ts`

**Interfaces:**
- Consumes: the contract from Task 7.
- Produces:
  - `type SuiteStrategy = { suiteId: string; suiteName: string; brand: {...}; audience: {...}; marketingMessage: string; contentThemes: string[] }`
  - `async function fetchSuiteStrategy(organizationId: string): Promise<SuiteStrategy | null>` — `null` means "no suite"
  - `type StrategyPort = { get(organizationId: string): Promise<SuiteStrategy | null> }` with `strategyPort` (real) and `fakeStrategyPort(value)` (tests)

- [ ] **Step 1: Write the failing test**

```ts
// tests/suiteClient.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchSuiteStrategy } from "@/lib/suite-client";

const CONTRACT = {
  suite: { id: "s1", name: "Afkar", status: "active", updated_at: "2026-09-16T10:00:00Z" },
  brand: { description: "healthy food", tagline: "eat well", services: ["catering"] },
  audience: {
    language: "ar",
    demographics: { age: "25-45", gender: "all", social_status: "working" },
    problem: "no time to cook",
    personas: [{ name: "Sara", age: 34, profession: "nurse", needs: "fast", challenges: "shifts" }],
    keywords: ["healthy"],
  },
  marketing_message: "eat well without cooking",
  content_themes: ["recipes"],
};

afterEach(() => vi.unstubAllGlobals());

describe("fetchSuiteStrategy", () => {
  it("بيحوّل العقد لشكل داخلي", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(CONTRACT))));
    const out = await fetchSuiteStrategy("org1");

    expect(out!.suiteName).toBe("Afkar");
    expect(out!.audience.language).toBe("ar");
    expect(out!.audience.personas[0].name).toBe("Sara");
    expect(out!.marketingMessage).toBe("eat well without cooking");
  });

  it("٤٠٤ معناها ما في سوت — مش خطأ", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    expect(await fetchSuiteStrategy("org1")).toBeNull();
  });

  it("عطل بالخدمة بيرمي — الصفحة بتقرر شو بتعمل، مش العميل", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    await expect(fetchSuiteStrategy("org1")).rejects.toThrow(/suite/i);
  });

  it("شخصيات ناقصة ما بتكسر التحويل", async () => {
    const thin = { ...CONTRACT, audience: { ...CONTRACT.audience, personas: undefined } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(thin))));

    const out = await fetchSuiteStrategy("org1");
    expect(out!.audience.personas).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npx vitest run tests/suiteClient.test.ts`
Expected: FAIL — cannot resolve `@/lib/suite-client`

- [ ] **Step 3: Write the client**

```ts
// src/lib/suite-client.ts
/**
 * استراتيجية السوت — العقل اللي المنتج بينفّذه.
 *
 * السوت بيحكي لمين نحكي وشو نحكي؛ OneShare بيحكي من وين وبكم. العقد مرقّم
 * بنسخة عند co-Suite، فأي تغيير بشكله بيجي كـ v2 مش بصمت.
 */
export type SuitePersona = {
  name: string;
  age: number | null;
  profession: string;
  needs: string;
  challenges: string;
};

export type SuiteStrategy = {
  suiteId: string;
  suiteName: string;
  brand: { description: string; tagline: string; services: string[] };
  audience: {
    language: string;
    demographics: { age: string; gender: string; socialStatus: string };
    problem: string;
    personas: SuitePersona[];
    keywords: string[];
  };
  marketingMessage: string;
  contentThemes: string[];
};

const BASE = () => process.env.COSUITE_API_URL || "";
const KEY = () => process.env.COSUITE_SERVICE_KEY || "";

/** `null` معناها البزنس لسا بلا سوت — دعوة، مش خطأ. */
export async function fetchSuiteStrategy(organizationId: string): Promise<SuiteStrategy | null> {
  const url = `${BASE()}/internal/v1/suite?organization_id=${encodeURIComponent(organizationId)}`;
  const res = await fetch(url, { headers: { authorization: `Bearer ${KEY()}` }, cache: "no-store" });

  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`suite read failed (${res.status})`);

  const raw = (await res.json()) as Record<string, never>;
  const suite = (raw.suite ?? {}) as { id?: string; name?: string };
  const brand = (raw.brand ?? {}) as { description?: string; tagline?: string; services?: string[] };
  const audience = (raw.audience ?? {}) as {
    language?: string;
    demographics?: { age?: string; gender?: string; social_status?: string };
    problem?: string;
    personas?: Array<Record<string, unknown>>;
    keywords?: string[];
  };
  const demographics = audience.demographics ?? {};

  return {
    suiteId: suite.id ?? "",
    suiteName: suite.name ?? "",
    brand: {
      description: brand.description ?? "",
      tagline: brand.tagline ?? "",
      services: brand.services ?? [],
    },
    audience: {
      language: audience.language ?? "",
      demographics: {
        age: demographics.age ?? "",
        gender: demographics.gender ?? "",
        socialStatus: demographics.social_status ?? "",
      },
      problem: audience.problem ?? "",
      personas: (audience.personas ?? []).map((p) => ({
        name: String(p.name ?? ""),
        age: typeof p.age === "number" ? p.age : null,
        profession: String(p.profession ?? ""),
        needs: String(p.needs ?? ""),
        challenges: String(p.challenges ?? ""),
      })),
      keywords: audience.keywords ?? [],
    },
    marketingMessage: String(raw.marketing_message ?? ""),
    contentThemes: (raw.content_themes as string[] | undefined) ?? [],
  };
}
```

- [ ] **Step 4: Run the test**

Run: `npx vitest run tests/suiteClient.test.ts`
Expected: PASS (4 passed)

- [ ] **Step 5: Add the port**

```ts
// src/lib/strategy.ts
/**
 * منفذ الاستراتيجية — نفس فكرة منافذ محرك الإنبوكس: الشغل اللي بيلزمه سوت
 * بينبنى وبينفحص بلا ما نشغّل co-Suite.
 */
import { fetchSuiteStrategy, type SuiteStrategy } from "./suite-client";

export type StrategyPort = {
  get(organizationId: string): Promise<SuiteStrategy | null>;
};

export const strategyPort: StrategyPort = { get: fetchSuiteStrategy };

/** للتستات: بيرجّع اللي بتعطيه ياه، بلا شبكة. */
export function fakeStrategyPort(value: SuiteStrategy | null): StrategyPort {
  return { get: async () => value };
}
```

- [ ] **Step 6: Verify the repo's gates**

Run: `npx tsc --noEmit && npm run lint && npx vitest run && bash scripts/check-inbox-isolation.sh`
Expected: all pass. The isolation script must still pass — `src/inbox/` does not import any of this.

- [ ] **Step 7: Commit**

```bash
git add src/lib/suite-client.ts src/lib/strategy.ts tests/suiteClient.test.ts
git commit -m "عميل استراتيجية السوت ومنفذها — العقل بيوصل للمنتج"
```

---

### Task 9: co-Suite web signs in with the Manzuma session

**Repository:** `co-suite-web`

**Files:**
- Create: `src/lib/manzumaSession.ts`
- Create: `src/app/link-suite/page.tsx`
- Modify: `src/lib/api.ts` (the `getToken`/`buildHeaders` pair at the top, lines 33–47)

**Interfaces:**
- Consumes: `GET {accounts}/api/session`; the API from Tasks 5 and 7.
- Produces: `async function manzumaSession(): Promise<{ userId: string; organizations: Array<{ id: string; name: string; role: string }> } | null>`.

- [ ] **Step 1: Write the failing test**

```ts
// tests/manzumaSession.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { manzumaSession } from "@/lib/manzumaSession";

afterEach(() => vi.unstubAllGlobals());

describe("manzumaSession", () => {
  it("returns the session with organizations", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      authenticated: true,
      user: { id: "u1" },
      organizations: [{ id: "o1", name: "Afkar", role: "owner" }],
    }))));

    const session = await manzumaSession();
    expect(session!.userId).toBe("u1");
    expect(session!.organizations[0].name).toBe("Afkar");
  });

  it("returns null when nobody is signed in", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ authenticated: false }))));
    expect(await manzumaSession()).toBeNull();
  });

  it("returns null instead of throwing when accounts is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await manzumaSession()).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npx vitest run tests/manzumaSession.test.ts`
Expected: FAIL — cannot resolve `@/lib/manzumaSession`

- [ ] **Step 3: Implement the session reader**

```ts
// src/lib/manzumaSession.ts
/**
 * Who is signed in, according to Manzuma accounts.
 *
 * The app is served from cosuite.manzuma.app, so the shared session cookie
 * reaches this fetch with `credentials: "include"`. No token is stored here:
 * the cookie is the credential, and the API verifies it server-side.
 */
export type ManzumaOrg = { id: string; name: string; role: string };
export type ManzumaSession = { userId: string; organizations: ManzumaOrg[] };

const ACCOUNTS = process.env.NEXT_PUBLIC_MANZUMA_ACCOUNTS_URL || "https://accounts.manzuma.app";

export async function manzumaSession(): Promise<ManzumaSession | null> {
  try {
    const res = await fetch(`${ACCOUNTS}/api/session`, { credentials: "include", cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data?.authenticated || !data?.user?.id) return null;
    return {
      userId: data.user.id,
      organizations: (data.organizations ?? []).map((o: ManzumaOrg) => ({
        id: o.id,
        name: o.name,
        role: o.role,
      })),
    };
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Send the cookie with API calls**

In `src/lib/api.ts`, the request helpers must include credentials so the API sees the Manzuma cookie. In both places that call `fetch(`${API_BASE}${path}`, …)` (lines 79 and 104), add `credentials: "include"` to the options object. Leave the existing bearer logic untouched — during the transition an old token still works.

- [ ] **Step 5: Write the link screen**

```tsx
// src/app/link-suite/page.tsx
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { manzumaSession, type ManzumaOrg } from "@/lib/manzumaSession";

/**
 * Linking a suite to a business is a one-time, explicit act: it decides which
 * business's campaigns, tokens and billing this strategy belongs to, and it
 * cannot be guessed on the customer's behalf.
 */
export default function LinkSuite() {
  const [orgs, setOrgs] = useState<ManzumaOrg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void manzumaSession().then((session) => setOrgs(session?.organizations ?? []));
  }, []);

  async function link(orgId: string) {
    setBusy(true);
    setError("");
    try {
      await api.suites.linkOrganization(orgId);
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Linking failed");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-lg p-6">
      <h1 className="text-2xl font-bold">Link this suite to your business</h1>
      <p className="mt-2 text-sm text-zinc-400">
        Your suite becomes the strategy for that business: its campaigns, its connected
        accounts and its team.
      </p>

      {orgs.map((org) => (
        <button
          key={org.id}
          disabled={busy}
          onClick={() => link(org.id)}
          className="mt-3 w-full rounded-xl border border-zinc-700 p-4 text-start hover:border-emerald-500 disabled:opacity-50"
        >
          <div className="font-bold">{org.name}</div>
          <div className="text-xs text-zinc-500">{org.role}</div>
        </button>
      ))}

      {orgs.length === 0 && (
        <p className="mt-6 text-sm text-zinc-500">
          No business found on your Manzuma account. Create one first at accounts.manzuma.app.
        </p>
      )}

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
    </main>
  );
}
```

Add the call it uses to `src/lib/api.ts`, inside the existing `suites` object:

```ts
    linkOrganization: (organizationId: string) =>
      request<{ ok: boolean; suite_id: string }>("/suites/link-organization", {
        method: "POST",
        body: JSON.stringify({ organization_id: organizationId }),
      }),
```

- [ ] **Step 6: Add the endpoint it calls (co-suite API)**

In `api/routers/suites.py`, add:

```python
@router.post("/link-organization")
async def link_organization(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link the caller's single unlinked suite to one of their businesses."""
    organization_id = (payload or {}).get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="organization_id_required")

    taken = (await db.execute(select(Suite).where(Suite.organization_id == organization_id))).scalar_one_or_none()
    if taken:
        raise HTTPException(status_code=409, detail="organization_already_linked")

    owned = (await db.execute(
        select(Suite).where(Suite.owner_id == current_user.id, Suite.organization_id.is_(None))
    )).scalars().all()
    if len(owned) != 1:
        raise HTTPException(status_code=409, detail="ambiguous_suite")

    owned[0].organization_id = organization_id
    await db.commit()
    print(f"[link] suite {owned[0].id} → org {organization_id} by user {current_user.id}")
    return {"ok": True, "suite_id": owned[0].id}
```

- [ ] **Step 7: Run both test suites**

Run (co-suite-web): `npx vitest run tests/manzumaSession.test.ts && npx tsc --noEmit`
Run (co-suite): `pytest -q`
Expected: both pass.

- [ ] **Step 8: Commit in each repository**

```bash
# co-suite-web
git add src/lib/manzumaSession.ts src/app/link-suite/page.tsx src/lib/api.ts tests/manzumaSession.test.ts
git commit -m "feat: sign in with the Manzuma session and link a suite to a business"

# co-suite
git add api/routers/suites.py
git commit -m "feat(link): endpoint to link a suite to a Manzuma business"
```

---

### Task 10: Tokens from the vault, and the flag

**Repository:** `co-suite`

**Files:**
- Modify: `api/routers/connections.py`
- Test: `tests/test_connections_no_token_leak.py`

**Interfaces:**
- Consumes: `vault_token` (Task 2), `Suite.organization_id` (Task 1).
- Produces: `async def meta_token_for(suite: Suite, asset_id: str | None = None) -> str | None` — the one way co-Suite gets a Meta token.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connections_no_token_leak.py
import inspect

import pytest

from api.models.suite import Suite
from api.routers import connections


def test_no_route_returns_a_token_to_the_browser():
    source = inspect.getsource(connections)
    for needle in ("page_access_token\":", "meta_user_token\":", "\"access_token\":"):
        assert needle not in source, f"a response still carries {needle}"


@pytest.mark.asyncio
async def test_meta_token_comes_from_the_vault(monkeypatch):
    suite = Suite(id="s1", owner_id="u1", name="Afkar", slug="afkar")
    suite.organization_id = "o1"

    async def _vault(organization_id, provider, asset_id=None, transport=None):
        assert (organization_id, provider, asset_id) == ("o1", "meta", "page1")
        return "vault-token"

    monkeypatch.setattr(connections, "vault_token", _vault)

    assert await connections.meta_token_for(suite, "page1") == "vault-token"


@pytest.mark.asyncio
async def test_a_suite_with_no_business_has_no_token(monkeypatch):
    suite = Suite(id="s2", owner_id="u1", name="Solo", slug="solo")

    assert await connections.meta_token_for(suite, "page1") is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_connections_no_token_leak.py -v`
Expected: FAIL — `AttributeError: module 'api.routers.connections' has no attribute 'meta_token_for'`

- [ ] **Step 3: Add the accessor and stop storing tokens**

In `api/routers/connections.py`:

```python
from ..services.manzuma_accounts import vault_token


async def meta_token_for(suite: Suite, asset_id: Optional[str] = None) -> Optional[str]:
    """A Meta token for this suite's business, from the encrypted vault.

    co-Suite stores none of its own. A suite that is not linked to a business
    has no token, and the caller shows the "connect Meta" empty state.
    """
    if not suite.organization_id:
        return None
    return await vault_token(suite.organization_id, "meta", asset_id)
```

Then, in the same file: every place that reads `connections["meta_user_token"]` or `connections[...]["page_access_token"]` calls `meta_token_for(suite, asset_id)` instead, and every place that **writes** a token into `connections` writes only the identifier (`page_id`, `instagram_id`, `ad_account_id`). Every response model field that carried a token is removed.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_connections_no_token_leak.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run everything**

Run: `pytest -q`
Expected: no new failures. Fix any test that asserted a token in a response — that assertion was the bug.

- [ ] **Step 6: Commit**

```bash
git add api/routers/connections.py tests/test_connections_no_token_leak.py
git commit -m "feat(link): Meta tokens come from the vault, and never reach the browser"
```

- [ ] **Step 7: Turn the flag on in production**

Set on the co-Suite Railway service: `MANZUMA_ACCOUNTS_URL`, `MANZUMA_SERVICE_KEY`, `INTERNAL_SERVICE_KEYS=oneshare:<key>`, and `MANZUMA_SSO=true`. Set on accounts: `INTERNAL_SERVICE_KEYS` gains `cosuite:<key>`. Set on OneShare: `COSUITE_API_URL`, `COSUITE_SERVICE_KEY`.

Then verify, in this order:

```bash
# 1. a signed-out call is refused
curl -s -o /dev/null -w "%{http_code}\n" "https://<cosuite-api>/internal/v1/suite?organization_id=o1"   # 401

# 2. with the module key, an unlinked business reads as "no suite"
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <oneshare key>" \
  "https://<cosuite-api>/internal/v1/suite?organization_id=<unlinked org>"                              # 404

# 3. and a linked one returns the contract
curl -s -H "Authorization: Bearer <oneshare key>" \
  "https://<cosuite-api>/internal/v1/suite?organization_id=<linked org>" | head -c 400                  # JSON
```

- [ ] **Step 8: Run the QA skill**

`AGENTS.md` requires it: run `cosuite-qa` over sign-in with a Manzuma session, linking a suite, and the Meta connection screens, and report exactly what was checked on production.

---

## Self-Review

**Spec coverage.** Identity (spec §1) → Tasks 1, 3, 4, 5, 9. Contract (§2) → Tasks 6, 7, 8. Tokens (§3) → Task 10. OneShare side (§4) → Task 8; the "no suite" empty state is deliberately deferred to the Campaigns plan, because OneShare has no Campaigns surface to host it yet — the client and the port, which that screen needs, land here. Rollout (§Rollout) → the task order plus Task 10 Step 7. Testing (§Testing) → the test steps in every task, plus the QA step.

**Not covered on purpose:** dropping `suite_members`, removing password sign-in, and stripping the token keys out of existing `connections` rows. All three are destructive, all three come after this plan settles in production, and each deserves its own small change.

**Response shape, verified:** `manzuma-accounts/src/app/api/session/route.ts` answers `{authenticated, user: {id, email, phone, name, image}, organizations: [{id, name, slug, role, subscriptions: [{organizationId, module, plan, status, limits}]}]}`, and `401` with `{authenticated: false}` for a caller it does not recognise. Task 2's parser and Task 3's approval rule are written against that shape. The one judgement call is which statuses count as live: this plan takes `active` and `trialing`, which is where `ACTIVE_SUBSCRIPTION_STATUSES` is defined — check it against `manzuma-accounts/src/db/schema.ts` before Task 3 and widen it there if the column allows another live value.
