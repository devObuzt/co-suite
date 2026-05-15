"""Meta (Facebook + Instagram) publisher.

For each approved post:
  • Upload media files to R2 → get public HTTPS URLs.
  • Post to Facebook Page (using Page Access Token).
  • Post to Instagram Business (using same Page Access Token + IG User ID).

Caption is the same on both platforms; hashtags appended.
"""
import json
import logging
import time
from pathlib import Path

import httpx

from . import posts_bank, r2_uploader
from .config import (
    META_IG_USER_ID,
    META_PAGE_ACCESS_TOKEN,
    META_PAGE_ID,
)

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"

# Max wait for IG video processing (Reels can take 1-3 minutes)
IG_VIDEO_POLL_INTERVAL = 5
IG_VIDEO_MAX_WAIT = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_caption(post: dict) -> str:
    """Combine caption + hashtags into a single string."""
    body = post.get("caption", "") or ""
    raw_tags = post.get("hashtags")
    if isinstance(raw_tags, str):
        try:
            tags = json.loads(raw_tags)
        except json.JSONDecodeError:
            tags = []
    else:
        tags = raw_tags or []
    if tags:
        body = body.rstrip() + "\n\n" + " ".join(tags)
    return body


def _api_post(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}"
    r = httpx.post(url, data=params, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"Meta API POST {path} failed [{r.status_code}]: {r.text}")
    return r.json()


def _api_get(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}"
    r = httpx.get(url, params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Meta API GET {path} failed [{r.status_code}]: {r.text}")
    return r.json()


def _upload_media_files(post: dict) -> list[str]:
    """Upload all media for a post to R2 and return their public URLs."""
    media_paths = posts_bank.get_media_paths(post)
    if not media_paths:
        raise RuntimeError(f"Post {post['id']} has no media")

    urls = []
    for p in media_paths:
        url = r2_uploader.upload_for_post(p, post["id"], filename=Path(p).name)
        urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Facebook publishers
# ---------------------------------------------------------------------------

def publish_fb_image(media_url: str, caption: str) -> str:
    """Post a single photo to the Facebook Page."""
    data = _api_post(
        f"{META_PAGE_ID}/photos",
        {
            "url": media_url,
            "caption": caption,
            "access_token": META_PAGE_ACCESS_TOKEN,
            "published": "true",
        },
    )
    return data.get("post_id") or data.get("id", "")


def publish_fb_album(media_urls: list[str], caption: str) -> str:
    """Post a multi-photo album (carousel) to the Facebook Page."""
    # Step 1: upload each photo as unpublished, get its fbid
    fbids = []
    for url in media_urls:
        data = _api_post(
            f"{META_PAGE_ID}/photos",
            {
                "url": url,
                "access_token": META_PAGE_ACCESS_TOKEN,
                "published": "false",
            },
        )
        fbids.append(data["id"])

    # Step 2: create a feed post with attached_media
    attached = [{"media_fbid": fbid} for fbid in fbids]
    data = _api_post(
        f"{META_PAGE_ID}/feed",
        {
            "message": caption,
            "attached_media": json.dumps(attached),
            "access_token": META_PAGE_ACCESS_TOKEN,
        },
    )
    return data.get("id", "")


def publish_fb_video(media_url: str, caption: str) -> str:
    """Post a video / reel to the Facebook Page."""
    data = _api_post(
        f"{META_PAGE_ID}/videos",
        {
            "file_url": media_url,
            "description": caption,
            "access_token": META_PAGE_ACCESS_TOKEN,
        },
    )
    return data.get("id", "")


# ---------------------------------------------------------------------------
# Instagram publishers
# ---------------------------------------------------------------------------

def _ig_wait_for_ready(container_id: str) -> None:
    """Poll an IG media container until it's FINISHED (mostly for videos)."""
    waited = 0
    while waited < IG_VIDEO_MAX_WAIT:
        data = _api_get(
            container_id,
            {"fields": "status_code,status", "access_token": META_PAGE_ACCESS_TOKEN},
        )
        status = data.get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"IG container {container_id} failed: {data}")
        log.info("  …IG container %s status=%s (waited %ds)", container_id, status, waited)
        time.sleep(IG_VIDEO_POLL_INTERVAL)
        waited += IG_VIDEO_POLL_INTERVAL
    raise TimeoutError(f"IG container {container_id} didn't finish within {IG_VIDEO_MAX_WAIT}s")


def _ig_publish(container_id: str) -> str:
    data = _api_post(
        f"{META_IG_USER_ID}/media_publish",
        {"creation_id": container_id, "access_token": META_PAGE_ACCESS_TOKEN},
    )
    return data.get("id", "")


def publish_ig_image(media_url: str, caption: str) -> str:
    data = _api_post(
        f"{META_IG_USER_ID}/media",
        {
            "image_url": media_url,
            "caption": caption,
            "access_token": META_PAGE_ACCESS_TOKEN,
        },
    )
    return _ig_publish(data["id"])


def publish_ig_carousel(media_urls: list[str], caption: str) -> str:
    # Step 1: create a container for each slide
    child_ids = []
    for url in media_urls:
        d = _api_post(
            f"{META_IG_USER_ID}/media",
            {
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": META_PAGE_ACCESS_TOKEN,
            },
        )
        child_ids.append(d["id"])

    # Step 2: create the carousel container
    d = _api_post(
        f"{META_IG_USER_ID}/media",
        {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
            "access_token": META_PAGE_ACCESS_TOKEN,
        },
    )
    return _ig_publish(d["id"])


def publish_ig_reel(media_url: str, caption: str) -> str:
    d = _api_post(
        f"{META_IG_USER_ID}/media",
        {
            "media_type": "REELS",
            "video_url": media_url,
            "caption": caption,
            "access_token": META_PAGE_ACCESS_TOKEN,
        },
    )
    _ig_wait_for_ready(d["id"])
    return _ig_publish(d["id"])


# ---------------------------------------------------------------------------
# Top-level: publish a post end-to-end
# ---------------------------------------------------------------------------

def publish_post(post_id: str) -> dict:
    """Publish a post to both Facebook Page and Instagram Business.

    Returns a dict of {platform: post_id_or_error}.
    Updates the DB record with publishing results.
    """
    post = posts_bank.get_post(post_id)
    if not post:
        raise RuntimeError(f"Post {post_id} not found")
    if post["status"] not in ("APPROVED", "SCHEDULED"):
        log.warning("Publishing post %s in unexpected status: %s", post_id, post["status"])

    log.info("Publishing post %s (%s) to Meta…", post_id, post["format"])

    # 1. Upload to R2
    media_urls = _upload_media_files(post)
    log.info("  uploaded %d file(s) to R2", len(media_urls))

    caption = _full_caption(post)
    fmt = post["format"]
    results: dict[str, str] = {}

    # 2. Facebook
    try:
        if fmt == "video":
            fb_id = publish_fb_video(media_urls[0], caption)
        elif fmt == "carousel":
            fb_id = publish_fb_album(media_urls, caption)
        else:
            fb_id = publish_fb_image(media_urls[0], caption)
        results["facebook"] = fb_id
        log.info("  ✅ FB: %s", fb_id)
    except Exception as e:
        log.exception("  ❌ FB publish failed: %s", e)
        results["facebook_error"] = str(e)

    # 3. Instagram
    if META_IG_USER_ID:
        try:
            if fmt == "video":
                ig_id = publish_ig_reel(media_urls[0], caption)
            elif fmt == "carousel":
                ig_id = publish_ig_carousel(media_urls, caption)
            else:
                ig_id = publish_ig_image(media_urls[0], caption)
            results["instagram"] = ig_id
            log.info("  ✅ IG: %s", ig_id)
        except Exception as e:
            log.exception("  ❌ IG publish failed: %s", e)
            results["instagram_error"] = str(e)
    else:
        log.info("  (Instagram skipped — no META_IG_USER_ID configured)")

    # 4. Update DB
    notes_obj = {"r2_urls": media_urls, "publish_results": results}
    posts_bank.update_post(post_id, notes=json.dumps(notes_obj, ensure_ascii=False))

    if "facebook" in results or "instagram" in results:
        posts_bank.mark_published(post_id)
    else:
        posts_bank.update_post(post_id, status="PUBLISH_FAILED")

    return results
