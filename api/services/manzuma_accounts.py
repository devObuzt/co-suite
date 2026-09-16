"""Talking to Manzuma accounts: who is signed in, and which token to act with.

Accounts owns identity and holds every platform token encrypted. This module is
the only place in co-Suite that calls it, so credential handling stays in one
file: nothing here is ever logged, and the session cache is keyed by a hash of
the credential rather than the credential itself.
"""
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Optional

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
    # Whether accounts itself proved these identifiers. Default False: an
    # identifier nobody vouched for must never adopt an existing account.
    email_verified: bool = False
    phone_verified: bool = False


_session_cache: dict[str, tuple[float, Optional[ManzumaSession]]] = {}


def _cache_key(cookie: Optional[str], bearer: Optional[str]) -> str:
    return hashlib.sha256(f"{cookie or ''}|{bearer or ''}".encode()).hexdigest()


def _parse(payload: dict[str, Any]) -> Optional[ManzumaSession]:
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
        email_verified=bool(user.get("emailVerified")),
        phone_verified=bool(user.get("phoneVerified")),
    )


async def verify_session(
    cookie: Optional[str],
    bearer: Optional[str],
    transport: Optional[httpx.BaseTransport] = None,
) -> Optional[ManzumaSession]:
    """Ask accounts who this caller is. Anything but a yes comes back as None."""
    if not cookie and not bearer:
        return None

    key = _cache_key(cookie, bearer)
    cached = _session_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < SESSION_TTL_SECONDS:
        return cached[1]

    headers: dict[str, str] = {}
    if cookie:
        headers["cookie"] = cookie
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            res = await client.get(f"{settings.manzuma_accounts_url}/api/session", headers=headers)
        session = _parse(res.json()) if res.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        # Accounts unreachable, or a body that is not the contract. The caller
        # falls back to the legacy path; we never guess an identity.
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

    What this returns is never stored: not in the database, not in a log.
    """
    if not settings.manzuma_service_key:
        return None

    body: dict[str, str] = {"organizationId": organization_id, "provider": provider}
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
