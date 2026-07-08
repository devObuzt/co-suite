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
