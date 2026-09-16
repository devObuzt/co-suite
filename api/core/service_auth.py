"""Per-module keys for the internal API other Manzuma products call.

One key per product, so a leaked OneShare key cannot be used to impersonate
HeartBeat and can be rotated on its own. Same shape accounts uses for its vault,
so neither side invents a second auth scheme.
"""
import hmac
from typing import Optional

from fastapi import HTTPException, Request, status

from .config import settings


def _key_map() -> dict[str, str]:
    pairs: dict[str, str] = {}
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
