"""Meta (Facebook + Instagram) OAuth service."""
import asyncio
import httpx
from typing import Optional
from ..core.config import settings
from ..core.external_calls import external_call

GRAPH = "https://graph.facebook.com/v22.0"

# Graph API can be slow for accounts with many pages; default 5s timeout is not enough
META_TIMEOUT = httpx.Timeout(30.0)

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
        async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
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
        async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
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


PAGE_FIELDS = (
    "id,name,access_token,"
    "instagram_business_account{id,name,username,profile_picture_url}"
)


async def _fetch_all(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
    """Follow Graph API paging.next until the edge is exhausted."""
    items: list[dict] = []
    while url:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
        params = None  # paging.next already carries every query param
    return items


async def _fetch_business_pages(
    client: httpx.AsyncClient, user_token: str, business_id: str
) -> list[dict]:
    """Pages a Business Portfolio owns or manages for a client."""
    pages: list[dict] = []
    for edge in ("owned_pages", "client_pages"):
        try:
            pages.extend(
                await _fetch_all(
                    client,
                    f"{GRAPH}/{business_id}/{edge}",
                    {"access_token": user_token, "fields": PAGE_FIELDS, "limit": 100},
                )
            )
        except httpx.HTTPError:
            continue  # one inaccessible edge must not sink the whole list
    return pages


async def _fetch_page_token(
    client: httpx.AsyncClient, user_token: str, page_id: str
) -> Optional[str]:
    """Ask for a single page's access token (portfolio edges don't include one)."""
    try:
        resp = await client.get(
            f"{GRAPH}/{page_id}",
            params={"access_token": user_token, "fields": "access_token"},
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except httpx.HTTPError:
        return None


async def fetch_page_token(user_token: str, page_id: str) -> Optional[str]:
    """Public wrapper: resolve one page's access token from a user token."""
    async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
        return await _fetch_page_token(client, user_token, page_id)


async def get_user_pages(user_token: str) -> list[dict]:
    """Get all Facebook Pages the user manages, including IG account info.

    /me/accounts only returns pages the user holds a *direct* role on. Pages
    reached through a Business Portfolio asset assignment are invisible there,
    even for an admin with every permission — so walk the portfolios too.
    """
    async with external_call("meta", "fetch_pages") as call:
        async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
            direct = await _fetch_all(
                client,
                f"{GRAPH}/me/accounts",
                {"access_token": user_token, "fields": PAGE_FIELDS, "limit": 100},
            )
            by_id = {p["id"]: p for p in direct if p.get("id")}

            try:
                businesses = await _fetch_all(
                    client,
                    f"{GRAPH}/me/businesses",
                    {"access_token": user_token, "fields": "id,name", "limit": 100},
                )
            except httpx.HTTPError:
                businesses = []  # no business_management access; direct pages still work

            if businesses:
                results = await asyncio.gather(
                    *(
                        _fetch_business_pages(client, user_token, b["id"])
                        for b in businesses
                        if b.get("id")
                    ),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        continue
                    for page in result:
                        if page.get("id") and page["id"] not in by_id:
                            by_id[page["id"]] = page

            # Portfolio edges omit access_token; fetch it per page so the
            # picker can actually connect them.
            missing = [p for p in by_id.values() if not p.get("access_token")]
            if missing:
                tokens = await asyncio.gather(
                    *(_fetch_page_token(client, user_token, p["id"]) for p in missing),
                    return_exceptions=True,
                )
                for page, token in zip(missing, tokens):
                    if isinstance(token, str) and token:
                        page["access_token"] = token

            call.note(
                pages=len(by_id),
                direct=len(direct),
                businesses=len(businesses),
                token_backfilled=sum(
                    1 for p in missing if p.get("access_token")
                ),
                token_missing=sum(
                    1 for p in by_id.values() if not p.get("access_token")
                ),
            )
            return list(by_id.values())


async def get_ad_accounts(user_token: str) -> list[dict]:
    """Get ad accounts the user can access."""
    async with external_call("meta", "fetch_ad_accounts") as call:
        async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
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
            async with httpx.AsyncClient(timeout=META_TIMEOUT) as client:
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
