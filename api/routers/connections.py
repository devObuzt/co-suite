"""Platform connections — OAuth flows and connection management."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel
from typing import Optional

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.user import User
from ..models.suite import Suite
from ..services.meta_oauth import (
    get_oauth_url, exchange_code, get_long_lived_token, get_user_pages, get_ad_accounts,
    fetch_page_token, verify_token
)
from ..services.meta_ads_manager import fetch_campaigns
from ..services.youtube_oauth import (
    get_youtube_oauth_url,
    exchange_youtube_code,
    fetch_authorized_channel,
)
from ..services.google_ads import (
    get_google_ads_oauth_url,
    exchange_google_ads_code,
    fetch_google_user_info,
    list_accessible_customers,
    fetch_google_ads_campaigns,
)

router = APIRouter(prefix="/connections", tags=["connections"])


# ── GET OAuth URL ─────────────────────────────────────────────────────────────

@router.get("/{suite_id}/meta/auth-url")
async def meta_auth_url(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    return {"url": get_oauth_url(suite.id)}


# ── OAuth Callback (called by frontend after redirect) ────────────────────────

class CallbackRequest(BaseModel):
    suite_id: str
    code: str


class PageSelection(BaseModel):
    suite_id: str
    page_id: str
    page_name: str
    # Pages reached via a Business Portfolio arrive without a token; the server
    # resolves one from the stored user token instead of rejecting the request.
    page_access_token: Optional[str] = None
    ig_user_id: Optional[str] = None
    ig_username: Optional[str] = None
    ad_account_id: Optional[str] = None
    ad_account_name: Optional[str] = None
    ad_account_currency: Optional[str] = None


class GoogleCustomerSelection(BaseModel):
    suite_id: str
    customer_id: str
    customer_name: Optional[str] = None


@router.post("/meta/callback")
async def meta_callback(
    data: CallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange OAuth code → long-lived token → return list of pages to choose from."""
    suite = await _get_suite(data.suite_id, current_user, db)

    try:
        token_data = await exchange_code(data.code)
        short_token = token_data["access_token"]
        long_token = await get_long_lived_token(short_token)
        pages = await get_user_pages(long_token)
    except httpx.HTTPStatusError as e:
        # never echo the exception string: request URLs embed the access token
        raise HTTPException(
            status_code=400,
            detail=f"Meta OAuth failed: Meta returned {e.response.status_code} while fetching your account data. Try reconnecting.",
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Meta OAuth failed: could not complete the connection. Try reconnecting.")

    # Ad accounts are optional: users without ads permissions (e.g. app not yet
    # approved for ads scopes) should still be able to connect their pages.
    try:
        ad_accounts = await get_ad_accounts(long_token)
    except Exception:
        ad_accounts = []

    # Store user token temporarily on suite (will be replaced by page token on selection)
    connections = dict(suite.connections or {})
    connections["meta_user_token"] = long_token
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()

    return {"pages": pages, "ad_accounts": ad_accounts}


@router.post("/meta/select-page")
async def meta_select_page(
    data: PageSelection,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """After the user picks a Facebook Page, store its access token + IG info."""
    suite = await _get_suite(data.suite_id, current_user, db)

    connections = dict(suite.connections or {})

    page_token = data.page_access_token
    if not page_token:
        user_token = connections.get("meta_user_token")
        if user_token:
            page_token = await fetch_page_token(user_token, data.page_id)
    if not page_token:
        raise HTTPException(
            status_code=400,
            detail="Could not get a posting token for this Page. Make sure you have a role on it, then reconnect.",
        )

    connections["facebook"] = {
        "connected": True,
        "page_id": data.page_id,
        "page_name": data.page_name,
        "page_access_token": page_token,
    }
    if data.ig_user_id:
        connections["instagram"] = {
            "connected": True,
            "ig_user_id": data.ig_user_id,
            "username": data.ig_username,
            "page_access_token": page_token,
        }
    if data.ad_account_id:
        connections["meta_ads"] = {
            "connected": True,
            "ad_account_id": data.ad_account_id,
            "ad_account_name": data.ad_account_name,
            "currency": data.ad_account_currency,
            "user_access_token": connections.get("meta_user_token"),
        }
    # Clean up temp user token
    connections.pop("meta_user_token", None)
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()

    return {"ok": True, "connections": _safe_connections(connections)}


@router.get("/{suite_id}/google/auth-url")
async def google_auth_url(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    try:
        return {"url": get_google_ads_oauth_url(suite.id)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/google/callback")
async def google_callback(
    data: CallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(data.suite_id, current_user, db)
    try:
        token_data = await exchange_google_ads_code(data.code)
        refresh_token = token_data.get("refresh_token")
        access_token = token_data.get("access_token")
        if not refresh_token:
            raise RuntimeError("Google did not return a refresh token. Reconnect and approve offline access.")
        google_user = await fetch_google_user_info(access_token)
        customers = await list_accessible_customers(access_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Google Ads OAuth failed: {e}")

    connections = dict(suite.connections or {})
    connections["google_ads_pending"] = {
        "refresh_token": refresh_token,
        "user_email": google_user.get("email"),
        "user_name": google_user.get("name"),
    }
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()

    return {"customers": customers}


@router.post("/google/select-customer")
async def google_select_customer(
    data: GoogleCustomerSelection,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(data.suite_id, current_user, db)
    connections = dict(suite.connections or {})
    pending = connections.get("google_ads_pending") or {}
    refresh_token = pending.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Google Ads OAuth session expired. Connect again.")

    connections["google_ads"] = {
        "connected": True,
        "customer_id": data.customer_id.replace("-", ""),
        "customer_name": data.customer_name or data.customer_id,
        "user_email": pending.get("user_email"),
        "user_name": pending.get("user_name"),
        "refresh_token": refresh_token,
    }
    connections.pop("google_ads_pending", None)
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()
    return {"ok": True, "connections": _safe_connections(connections)}


# ── YouTube ───────────────────────────────────────────────────────────────────
#
# No select-channel step, unlike Google Ads: a YouTube authorization binds to the
# single channel the user picked in Google's own chooser, so the callback already
# knows the target. See youtube_oauth.fetch_authorized_channel.

@router.get("/{suite_id}/youtube/auth-url")
async def youtube_auth_url(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    try:
        return {"url": get_youtube_oauth_url(suite.id)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/youtube/callback")
async def youtube_callback(
    data: CallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(data.suite_id, current_user, db)
    try:
        token_data = await exchange_youtube_code(data.code)
        refresh_token = token_data.get("refresh_token")
        access_token = token_data.get("access_token")
        if not refresh_token:
            raise RuntimeError(
                "Google did not return a refresh token. Disconnect and approve offline access again."
            )
        channel = await fetch_authorized_channel(access_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YouTube OAuth failed: {e}")

    connections = dict(suite.connections or {})
    connections["youtube"] = {
        "connected": True,
        **channel,
        "refresh_token": refresh_token,
    }
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()

    return {"ok": True, "channel": channel, "connections": _safe_connections(connections)}


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.delete("/{suite_id}/{platform}")
async def disconnect(
    suite_id: str,
    platform: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    connections = dict(suite.connections or {})
    connections.pop(platform, None)
    if platform == "facebook":
        connections.pop("instagram", None)
        connections.pop("meta_ads", None)
    if platform == "google_ads":
        connections.pop("google_ads_pending", None)
    suite.connections = connections
    flag_modified(suite, "connections")
    await db.commit()
    return {"ok": True}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/{suite_id}")
async def get_connections(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    return _safe_connections(suite.connections or {})


@router.get("/{suite_id}/meta/campaigns")
async def meta_campaigns(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    connections = dict(suite.connections or {})
    meta_ads = connections.get("meta_ads") or {}
    await db.close()

    return await fetch_campaigns(
        meta_ads.get("ad_account_id", ""),
        meta_ads.get("user_access_token", ""),
    )


@router.get("/{suite_id}/google/campaigns")
async def google_campaigns(
    suite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    suite = await _get_suite(suite_id, current_user, db)
    connections = dict(suite.connections or {})
    google_ads = connections.get("google_ads") or {}
    await db.close()

    return await fetch_google_ads_campaigns(
        google_ads.get("customer_id", ""),
        google_ads.get("refresh_token", ""),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_suite(suite_id: str, user: User, db: AsyncSession) -> Suite:
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    suite = result.scalar_one_or_none()
    if not suite or suite.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


def _safe_connections(connections: dict) -> dict:
    """Strip access tokens before sending to frontend."""
    safe = {}
    for platform, data in connections.items():
        if isinstance(data, dict):
            safe[platform] = {k: v for k, v in data.items() if "token" not in k.lower()}
        else:
            safe[platform] = data
    return safe
