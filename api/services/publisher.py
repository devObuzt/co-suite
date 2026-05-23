"""Multi-tenant Meta publisher.

Adapts connec-content-engine's meta_publisher.py to use per-suite connection
tokens stored in the DB instead of hardcoded env vars.

Image URL strategy:
  1. If media_url already starts with https:// (e.g. R2) → use as-is.
  2. If media_url is a local /static/ path and R2 is configured → upload first.
  3. Otherwise → publish caption-only (text post) with a warning.
"""
import json
import logging
import time
from typing import Optional

import httpx

from ..core.config import settings
from ..models.content import ContentPost, PostFormat, PostStatus
from .media_storage import upload_static_path

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v22.0"
IG_POLL_INTERVAL = 5
IG_MAX_WAIT = 300


# ── Helpers ───────────────────────────────────────────────────────────────────

def _full_caption(post: ContentPost) -> str:
    body = post.caption or ""
    tags = post.hashtags or []
    if tags:
        body = body.rstrip() + "\n\n" + " ".join(tags)
    return body


def _api_post(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}"
    r = httpx.post(url, data=params, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"Meta API POST {path} [{r.status_code}]: {r.text}")
    return r.json()


def _api_get(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}"
    r = httpx.get(url, params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Meta API GET {path} [{r.status_code}]: {r.text}")
    return r.json()


def _resolve_url(local_or_remote: str) -> Optional[str]:
    """Return a public HTTPS URL or None if image can't be made public."""
    if local_or_remote.startswith("https://"):
        return local_or_remote

    # Local static path — try R2 upload
    if settings.r2_access_key_id and settings.r2_public_url:
        try:
            return upload_static_path(local_or_remote).url
        except Exception as e:
            log.warning("R2 upload failed: %s", e)

    return None


def _platform_media(post: ContentPost, platform: str) -> list[str]:
    meta = post.ai_metadata or {}
    platform_media = meta.get("platform_media") or {}
    urls = platform_media.get(platform) or []
    if urls:
        return urls
    return post.media_urls or []


# ── Facebook ──────────────────────────────────────────────────────────────────

def _fb_image(page_id: str, token: str, url: str, caption: str) -> str:
    data = _api_post(f"{page_id}/photos", {"url": url, "caption": caption, "access_token": token, "published": "true"})
    return data.get("post_id") or data.get("id", "")


def _fb_text(page_id: str, token: str, caption: str) -> str:
    data = _api_post(f"{page_id}/feed", {"message": caption, "access_token": token})
    return data.get("id", "")


def _fb_album(page_id: str, token: str, urls: list[str], caption: str) -> str:
    fbids = []
    for url in urls:
        d = _api_post(f"{page_id}/photos", {"url": url, "access_token": token, "published": "false"})
        fbids.append(d["id"])
    data = _api_post(f"{page_id}/feed", {
        "message": caption,
        "attached_media": json.dumps([{"media_fbid": fid} for fid in fbids]),
        "access_token": token,
    })
    return data.get("id", "")


def _fb_video(page_id: str, token: str, url: str, caption: str) -> str:
    data = _api_post(f"{page_id}/videos", {"file_url": url, "description": caption, "access_token": token})
    return data.get("id", "")


# ── Instagram ─────────────────────────────────────────────────────────────────

def _ig_wait(container_id: str, token: str) -> None:
    waited = 0
    while waited < IG_MAX_WAIT:
        d = _api_get(container_id, {"fields": "status_code", "access_token": token})
        status = d.get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"IG container {container_id} failed: {d}")
        time.sleep(IG_POLL_INTERVAL)
        waited += IG_POLL_INTERVAL
    raise TimeoutError(f"IG container timed out after {IG_MAX_WAIT}s")


def _ig_publish(ig_user_id: str, container_id: str, token: str) -> str:
    data = _api_post(f"{ig_user_id}/media_publish", {"creation_id": container_id, "access_token": token})
    return data.get("id", "")


def _ig_image(ig_user_id: str, token: str, url: str, caption: str) -> str:
    d = _api_post(f"{ig_user_id}/media", {"image_url": url, "caption": caption, "access_token": token})
    return _ig_publish(ig_user_id, d["id"], token)


def _ig_carousel(ig_user_id: str, token: str, urls: list[str], caption: str) -> str:
    child_ids = []
    for url in urls:
        d = _api_post(f"{ig_user_id}/media", {"image_url": url, "is_carousel_item": "true", "access_token": token})
        child_ids.append(d["id"])
    d = _api_post(f"{ig_user_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": token,
    })
    return _ig_publish(ig_user_id, d["id"], token)


def _ig_reel(ig_user_id: str, token: str, url: str, caption: str) -> str:
    d = _api_post(f"{ig_user_id}/media", {"media_type": "REELS", "video_url": url, "caption": caption, "access_token": token})
    _ig_wait(d["id"], token)
    return _ig_publish(ig_user_id, d["id"], token)


# ── Main entry point ──────────────────────────────────────────────────────────

def publish_post(post: ContentPost, connections: dict, platforms: list[str]) -> dict:
    """
    Publish a ContentPost to the requested platforms.

    connections: suite.connections dict (contains page tokens, ig ids)
    platforms: list of "facebook", "instagram", or both

    Returns {"facebook": id_or_error, "instagram": id_or_error, "warnings": [...]}
    """
    results: dict = {"warnings": []}
    caption = _full_caption(post)
    fmt = post.format

    # ── Facebook ──────────────────────────────────────────────────────────────
    if "facebook" in platforms:
        fb = connections.get("facebook", {})
        page_id = fb.get("page_id")
        token = fb.get("page_access_token")
        raw_urls = _platform_media(post, "facebook")
        public_urls = [resolved for url in raw_urls if (resolved := _resolve_url(url))]
        has_media = bool(public_urls)
        if raw_urls and not has_media:
            results["warnings"].append(
                "Facebook media is stored locally and couldn't be made public. "
                "Configure R2 in api/.env to publish media. Publishing text-only."
            )

        if not page_id or not token:
            results["facebook_error"] = "Facebook not connected"
        else:
            try:
                if not has_media:
                    fb_id = _fb_text(page_id, token, caption)
                elif fmt == PostFormat.video:
                    fb_id = _fb_video(page_id, token, public_urls[0], caption)
                elif fmt == PostFormat.carousel and len(public_urls) > 1:
                    fb_id = _fb_album(page_id, token, public_urls, caption)
                else:
                    fb_id = _fb_image(page_id, token, public_urls[0], caption)
                results["facebook"] = fb_id
                log.info("FB published: %s", fb_id)
            except Exception as e:
                log.exception("FB publish failed")
                results["facebook_error"] = str(e)

    # ── Instagram ─────────────────────────────────────────────────────────────
    if "instagram" in platforms:
        ig = connections.get("instagram", {})
        ig_user_id = ig.get("ig_user_id")
        token = ig.get("page_access_token") or connections.get("facebook", {}).get("page_access_token")
        raw_urls = _platform_media(post, "instagram")
        public_urls = [resolved for url in raw_urls if (resolved := _resolve_url(url))]
        has_media = bool(public_urls)

        if not ig_user_id or not token:
            results["instagram_error"] = "Instagram not connected"
        elif not has_media:
            results["instagram_error"] = "Instagram requires an image. Configure R2 to enable."
        else:
            try:
                if fmt == PostFormat.video:
                    ig_id = _ig_reel(ig_user_id, token, public_urls[0], caption)
                elif fmt == PostFormat.carousel and len(public_urls) > 1:
                    ig_id = _ig_carousel(ig_user_id, token, public_urls, caption)
                else:
                    ig_id = _ig_image(ig_user_id, token, public_urls[0], caption)
                results["instagram"] = ig_id
                log.info("IG published: %s", ig_id)
            except Exception as e:
                log.exception("IG publish failed")
                results["instagram_error"] = str(e)

    return results
