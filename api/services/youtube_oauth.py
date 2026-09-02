"""YouTube OAuth + channel lookup for connected suites.

Deliberately a **separate Google Cloud project** from Google Ads: `youtube.upload`
is a restricted scope, and adding it to the Ads consent screen opens a fresh review
that can freeze the Ads OAuth in `google_ads.py` for every client at once.

Two things measured on 2026-09-02 that shape this module:

- An **Internal** OAuth app cannot authorize a Brand Account channel — and every
  client channel is a Brand Account. Consent is evaluated against the *selected
  channel's* identity, which sits outside the Workspace org, so it returns
  `Error 403: org_internal`. The credentials here therefore belong to an
  **External** app; an Internal client id only ever works for our own channels.
- Unlike Google Ads, a YouTube authorization binds to **one channel**: the user
  picks it in Google's own account chooser during consent, so `channels.list?mine=true`
  comes back with exactly that channel. There is no "list the accounts, then pick
  one" step to mirror `google_ads.select-customer` — the callback can store it.
"""
from urllib.parse import urlencode

import httpx

from ..core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

YOUTUBE_SCOPE = " ".join([
    "https://www.googleapis.com/auth/youtube.upload",     # upload the video
    "https://www.googleapis.com/auth/youtube.readonly",   # confirm which channel we are on
    # captions.insert rejects youtube.upload — it needs force-ssl. Without it the
    # video uploads fine and only the caption track 403s, after the quota is spent.
    "https://www.googleapis.com/auth/youtube.force-ssl",
])


def _redirect_uri() -> str:
    return f"{settings.frontend_url}/connections/youtube/callback"


def _missing_youtube_config() -> list[str]:
    required = {
        "YOUTUBE_CLIENT_ID": settings.youtube_client_id,
        "YOUTUBE_CLIENT_SECRET": settings.youtube_client_secret,
    }
    return [name for name, value in required.items() if not value]


def get_youtube_oauth_url(suite_id: str) -> str:
    missing = _missing_youtube_config()
    if missing:
        raise RuntimeError("Missing YouTube configuration: " + ", ".join(missing))
    if not settings.frontend_url.startswith("https://"):
        raise RuntimeError("FRONTEND_URL must be the public HTTPS web domain for YouTube OAuth.")

    params = urlencode({
        "client_id": settings.youtube_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": YOUTUBE_SCOPE,
        "access_type": "offline",
        # Without prompt=consent Google skips the refresh token on re-authorization,
        # and the connection silently becomes read-once.
        "prompt": "consent",
        "state": suite_id,
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


async def exchange_youtube_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_youtube_access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def fetch_authorized_channel(access_token: str) -> dict:
    """The channel this authorization actually lands on.

    Called on connect to record the target, and again before every publish: the
    cost of getting this wrong is a client's video on somebody else's channel.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{YOUTUBE_API}/channels",
            params={"part": "snippet,statistics", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"YouTube channel lookup failed [{resp.status_code}]: {resp.text}")
        items = resp.json().get("items") or []
        if not items:
            raise RuntimeError(
                "This Google account has no YouTube channel. Pick the account that owns "
                "the channel in Google's chooser, not a plain Gmail account."
            )
        item = items[0]
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        thumbnails = snippet.get("thumbnails") or {}
        return {
            "channel_id": item.get("id"),
            "channel_title": snippet.get("title"),
            "custom_url": snippet.get("customUrl"),
            "thumbnail": ((thumbnails.get("default") or {}).get("url")),
            "subscribers": stats.get("subscriberCount"),
            "videos": stats.get("videoCount"),
        }
