"""Meta (Facebook + Instagram) OAuth service."""
import httpx
from typing import Optional
from ..core.config import settings
from ..core.external_calls import external_call

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
    "ads_management",
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
        # rerequest forces the granular asset-selection dialog to reappear,
        # otherwise Facebook silently reuses the first grant's page subset
        f"&auth_type=rerequest"
    )


async def exchange_code(code: str) -> dict:
    """Exchange short-lived code for a short-lived user token."""
    redirect_uri = f"{settings.frontend_url}/connections/callback"
    async with external_call("meta", "oauth_exchange_code") as call:
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
            call.note(status_code=resp.status_code)
            resp.raise_for_status()
            return resp.json()


async def get_long_lived_token(short_token: str) -> str:
    """Exchange short-lived for 60-day long-lived token."""
    async with external_call("meta", "oauth_extend_token") as call:
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
            call.note(status_code=resp.status_code)
            resp.raise_for_status()
            return resp.json()["access_token"]


async def get_user_pages(user_token: str) -> list[dict]:
    """Get all Facebook Pages the user manages, including IG account info."""
    async with external_call("meta", "fetch_pages") as call:
        async with httpx.AsyncClient() as client:
            pages: list[dict] = []
            url = f"{GRAPH}/me/accounts"
            params = {
                "access_token": user_token,
                "fields": "id,name,access_token,instagram_business_account{id,name,username,profile_picture_url}",
                "limit": 100,
            }
            # Graph API paginates; follow paging.next until exhausted
            while url:
                resp = await client.get(url, params=params)
                call.note(status_code=resp.status_code)
                resp.raise_for_status()
                body = resp.json()
                pages.extend(body.get("data", []))
                url = body.get("paging", {}).get("next")
                params = None  # paging.next already includes all query params
            call.note(pages=len(pages))
            return pages


async def get_ad_accounts(user_token: str) -> list[dict]:
    """Get ad accounts the user can access."""
    async with external_call("meta", "fetch_ad_accounts") as call:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH}/me/adaccounts",
                params={
                    "access_token": user_token,
                    "fields": "id,account_id,name,account_status,currency,timezone_name,business{name}",
                    "limit": 100,
                },
            )
            call.note(status_code=resp.status_code)
            resp.raise_for_status()
            accounts = resp.json().get("data", [])
            call.note(ad_accounts=len(accounts))
            return accounts


async def verify_token(token: str) -> Optional[dict]:
    """Inspect a token. Returns info dict or None if invalid."""
    try:
        # Exceptions propagate through the context manager (logged as a
        # failed call) before the outer except turns them into None.
        async with external_call("meta", "verify_token") as call:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH}/debug_token",
                    params={
                        "input_token": token,
                        "access_token": f"{settings.meta_app_id}|{settings.meta_app_secret}",
                    },
                )
                call.note(status_code=resp.status_code)
                resp.raise_for_status()
                data = resp.json().get("data", {})
                call.note(token_valid=bool(data.get("is_valid")))
                return data if data.get("is_valid") else None
    except Exception:
        return None
