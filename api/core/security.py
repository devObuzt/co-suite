import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .config import settings
from .database import get_db
from ..models.user import User

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    return jwt.encode({"sub": user_id, "exp": expire}, settings.secret_key, algorithm=settings.algorithm)


FROZEN_ALLOWED_PREFIXES = ("/api/v1/auth", "/api/v1/funnel")


def _path_in(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


# Explicit allowlist for "funnel" (anonymous self-registered lead) users.
# Anything not matched here is blocked (403 account_frozen), even under
# /api/v1/onboarding or /api/v1/suites — no bare-prefix leakage.
_FUNNEL_GET_PATTERNS = [
    re.compile(p)
    for p in (
        r"^/api/v1/onboarding(/.*)?$",
        r"^/api/v1/suites/?$",
        r"^/api/v1/suites/[^/]+$",
        r"^/api/v1/suites/[^/]+/marketing-plan(/.*)?$",
    )
]

_FUNNEL_POST_EXACT = {
    "/api/v1/onboarding/extract-brand",
    "/api/v1/onboarding/save-brand-step",
    "/api/v1/onboarding/save-brand",
    "/api/v1/onboarding/upload-brand-asset",
    "/api/v1/onboarding/translate-brand-fields",
    "/api/v1/onboarding/generate-strategy",
    "/api/v1/onboarding/generate-brand-assets",
}

_FUNNEL_POST_PATTERNS = [
    re.compile(p)
    for p in (
        r"^/api/v1/suites/[^/]+/marketing-plan/generate$",
        r"^/api/v1/suites/[^/]+/marketing-plan/social-content-plan/generate$",
        r"^/api/v1/suites/[^/]+/marketing-plan/paid-content-plan/generate$",
        r"^/api/v1/suites/[^/]+/marketing-plan/social-content-plan/selection$",
        r"^/api/v1/suites/[^/]+/marketing-plan/paid-content-plan/selection$",
    )
]


def _funnel_path_allowed(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    method = method.upper()

    # Auth + funnel-router endpoints are open to any method (register, enroll,
    # state, catalog, recommendations, service-request, etc.).
    if _path_in(path, FROZEN_ALLOWED_PREFIXES):
        return True

    if method == "GET":
        return any(pattern.match(path) for pattern in _FUNNEL_GET_PATTERNS)

    if method == "POST":
        if path in _FUNNEL_POST_EXACT:
            return True
        return any(pattern.match(path) for pattern in _FUNNEL_POST_PATTERNS)

    return False


def frozen_path_allowed(approval_status: str, method: str, path: str) -> bool:
    """Per-status API gate. Anything not approved sees only its allowlist."""
    if approval_status == "approved":
        return True
    if approval_status == "funnel":
        return _funnel_path_allowed(method, path)
    return _path_in(path, FROZEN_ALLOWED_PREFIXES)


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
