"""Meta (Facebook + Instagram) OAuth service."""
import httpx
from typing import Optional
from ..core.config import settings

GRAPH = "https://graph.facebook.com/v22.0"

META_SCOPES = [
    "pages_manage_posts",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_show_list",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "ads_read",
    "business_management",
    "public_profile",
    "email",
]


def get_oauth_url(suite_id: str) -> str:
    redirect_uri = f"{settings.frontend_url}/connections/callback"
    scope = ",".join(META_SCOPES)
    return (
        f"https://www.facebook.com/dialog/oauth"
        f"?client_id={settings.meta_app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={suite_id}"
        f"&response_type=code"
    )


async def exchange_code(code: str) -> dict:
    """Exchange short-lived code for a short-lived user token."""
    redirect_uri = f"{settings.frontend_url}/connections/callback"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_long_lived_token(short_token: str) -> str:
    """Exchange short-lived for 60-day long-lived token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def get_user_pages(user_token: str) -> list[dict]:
    """Get all Facebook Pages the user manages, including IG account info."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH}/me/accounts",
            params={
                "access_token": user_token,
                "fields": "id,name,access_token,instagram_business_account{id,name,username,profile_picture_url}",
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


async def verify_token(token: str) -> Optional[dict]:
    """Inspect a token. Returns info dict or None if invalid."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH}/debug_token",
                params={
                    "input_token": token,
                    "access_token": f"{settings.meta_app_id}|{settings.meta_app_secret}",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data if data.get("is_valid") else None
    except Exception:
        return None
