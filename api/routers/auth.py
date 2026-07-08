from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from ..core.config import settings
from ..core.database import get_db
from ..core.security import hash_password, verify_password, create_access_token, get_current_user
from ..models.user import User
from ..services.admin_audit import ensure_admin_flag, record_audit_log, serialize_user_public

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        phone=(data.phone or "").strip() or None,
    )
    if data.email.strip().lower() == settings.admin_email.strip().lower():
        user.is_super_admin = True
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await record_audit_log(
        db,
        action="auth.signup",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=user,
        request=request,
        metadata={"email": user.email},
        commit=True,
    )

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=serialize_user_public(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    user = await ensure_admin_flag(user, db)
    await record_audit_log(
        db,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        target_user_id=user.id,
        actor=user,
        request=request,
        metadata={"email": user.email},
        commit=True,
    )
    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=serialize_user_public(user),
    )


@router.get("/me")
async def me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    current_user = await ensure_admin_flag(current_user, db)
    return serialize_user_public(current_user)
