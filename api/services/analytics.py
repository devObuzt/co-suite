"""Fetch analytics from Facebook Page and Instagram Business via Graph API."""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..core.external_calls import external_call

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v22.0"


async def _get(path: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{GRAPH}/{path}", params=params)
        if resp.status_code >= 400:
            body = _sanitize_meta_error(resp.text)
            raise RuntimeError(f"Meta API {path} [{resp.status_code}]: {body}")
        return resp.json()


def _sanitize_meta_error(text: str) -> str:
    """Keep Meta's useful error body but never log access tokens."""
    return re.sub(r'"access_token"\s*:\s*"[^"]+"', '"access_token":"[redacted]"', text)


# ── Facebook Page ─────────────────────────────────────────────────────────────

async def fetch_fb_page_summary(page_id: str, token: str) -> dict:
    """Basic page info: name, fan count."""
    async with external_call("meta", "fetch_page_info", page_id=page_id) as call:
        try:
            data = await _get(page_id, {
                "fields": "name,followers_count",
                "access_token": token,
            })
            return {
                "name": data.get("name"),
                "followers": data.get("followers_count", 0),
            }
        except Exception as e:
            log.warning("FB page summary failed: %s", e)
            call.fail(_sanitize_meta_error(str(e)))
            return {"error": str(e)}


async def fetch_fb_insights(page_id: str, token: str, days: int = 28) -> dict:
    """Page reach and engagement over the last `days` days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    metrics = [
        "page_impressions_unique",
        "page_post_engagements",
    ]
    result: dict = {}
    errors = []

    async with external_call("meta", "fetch_page_insights", page_id=page_id, days=days) as call:
        for metric in metrics:
            try:
                data = await _get(f"{page_id}/insights", {
                    "metric": metric,
                    "period": "day",
                    "since": int(since.timestamp()),
                    "until": int(until.timestamp()),
                    "access_token": token,
                })
                for item in data.get("data", []):
                    name = item["name"]
                    result[name] = [
                        {"date": v["end_time"][:10], "value": v["value"]}
                        for v in item.get("values", [])
                    ]
            except Exception as e:
                log.warning("FB insight metric %s failed: %s", metric, e)
                errors.append(f"{metric}: {e}")

        if errors and not result:
            call.fail(_sanitize_meta_error("; ".join(errors[:2])))
            return {"error": "; ".join(errors[:2])}
        if errors:
            call.note(warnings=len(errors))
            result["warnings"] = errors[:2]
        return result


async def fetch_fb_recent_posts(page_id: str, token: str, limit: int = 10) -> list[dict]:
    """Recent posts with like/comment/share counts."""
    async with external_call("meta", "fetch_page_posts", page_id=page_id) as call:
        try:
            data = await _get(f"{page_id}/posts", {
                "fields": "id,message,created_time,full_picture,likes.summary(true),comments.summary(true),shares",
                "limit": limit,
                "access_token": token,
            })
            posts = []
            for p in data.get("data", []):
                posts.append({
                    "id": p["id"],
                    "message": (p.get("message") or "")[:120],
                    "created_time": p.get("created_time"),
                    "image": p.get("full_picture"),
                    "likes": p.get("likes", {}).get("summary", {}).get("total_count", 0),
                    "comments": p.get("comments", {}).get("summary", {}).get("total_count", 0),
                    "shares": p.get("shares", {}).get("count", 0),
                })
            return posts
        except Exception as e:
            log.warning("FB posts failed: %s", e)
            call.fail(_sanitize_meta_error(str(e)))
            return []


# ── Instagram ─────────────────────────────────────────────────────────────────

async def fetch_ig_summary(ig_user_id: str, token: str) -> dict:
    """Follower count, media count, profile views."""
    async with external_call("meta", "fetch_instagram_info", ig_user_id=ig_user_id) as call:
        try:
            data = await _get(ig_user_id, {
                "fields": "username,followers_count,media_count,profile_picture_url",
                "access_token": token,
            })
            return {
                "username": data.get("username"),
                "followers": data.get("followers_count", 0),
                "media_count": data.get("media_count", 0),
                "profile_picture": data.get("profile_picture_url"),
            }
        except Exception as e:
            log.warning("IG summary failed: %s", e)
            call.fail(_sanitize_meta_error(str(e)))
            return {"error": str(e)}


async def fetch_ig_insights(ig_user_id: str, token: str, days: int = 28) -> dict:
    """Instagram reach and total-value metrics over the last `days` days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    result: dict = {}
    errors = []

    async with external_call("meta", "fetch_instagram_insights", ig_user_id=ig_user_id, days=days) as call:
        try:
            data = await _get(f"{ig_user_id}/insights", {
                "metric": "reach,follower_count",
                "period": "day",
                "since": int(since.timestamp()),
                "until": int(until.timestamp()),
                "access_token": token,
            })
            result: dict = {}
            for item in data.get("data", []):
                name = item["name"]
                values = [{"date": v["end_time"][:10], "value": v["value"]}
                          for v in item.get("values", [])]
                result[name] = values
        except Exception as e:
            log.warning("IG daily insights failed: %s", e)
            errors.append(f"daily: {e}")

        try:
            data = await _get(f"{ig_user_id}/insights", {
                "metric": "views,profile_views",
                "metric_type": "total_value",
                "period": "day",
                "since": int(since.timestamp()),
                "until": int(until.timestamp()),
                "access_token": token,
            })
            today = until.date().isoformat()
            for item in data.get("data", []):
                name = item["name"]
                value = (item.get("total_value") or {}).get("value", 0)
                result[name] = [{"date": today, "value": value}]
        except Exception as e:
            log.warning("IG total insights failed: %s", e)
            errors.append(f"total: {e}")

        if errors and not result:
            call.fail(_sanitize_meta_error("; ".join(errors)))
            return {"error": "; ".join(errors)}
        if errors:
            call.note(warnings=len(errors))
            result["warnings"] = errors
        return result


async def fetch_ig_recent_media(ig_user_id: str, token: str, limit: int = 9) -> list[dict]:
    """Recent IG posts with engagement."""
    async with external_call("meta", "fetch_instagram_media", ig_user_id=ig_user_id) as call:
        try:
            data = await _get(f"{ig_user_id}/media", {
                "fields": "id,caption,media_type,timestamp,like_count,comments_count,media_url,thumbnail_url,permalink",
                "limit": limit,
                "access_token": token,
            })
            return [
                {
                    "id": m["id"],
                    "caption": (m.get("caption") or "")[:120],
                    "media_type": m.get("media_type"),
                    "timestamp": m.get("timestamp"),
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "image": m.get("media_url") or m.get("thumbnail_url"),
                    "url": m.get("permalink"),
                }
                for m in data.get("data", [])
            ]
        except Exception as e:
            log.warning("IG media failed: %s", e)
            call.fail(_sanitize_meta_error(str(e)))
            return []


# ── Aggregator ────────────────────────────────────────────────────────────────

async def fetch_suite_analytics(connections: dict, days: int = 28) -> dict:
    """Top-level: gather all analytics for a suite from its connections."""
    result: dict = {"facebook": {}, "instagram": {}, "days": days, "errors": []}

    fb = connections.get("facebook", {})
    ig = connections.get("instagram", {})

    page_id = fb.get("page_id")
    page_token = fb.get("page_access_token")
    ig_user_id = ig.get("ig_user_id")
    # Instagram uses the page token too
    ig_token = ig.get("page_access_token") or page_token

    if page_id and page_token:
        summary, insights, posts = await _gather(
            fetch_fb_page_summary(page_id, page_token),
            fetch_fb_insights(page_id, page_token, days),
            fetch_fb_recent_posts(page_id, page_token),
        )
        errors = []
        if summary.get("error"):
            errors.append(f"Facebook summary: {summary.pop('error')}")
        if insights.get("error"):
            errors.append(f"Facebook insights: {insights.pop('error')}")
        for warning in insights.pop("warnings", []):
            errors.append(f"Facebook insight warning: {warning}")
        result["errors"].extend(errors)
        result["facebook"] = {**summary, "insights": insights, "recent_posts": posts}

    if ig_user_id and ig_token:
        summary, insights, media = await _gather(
            fetch_ig_summary(ig_user_id, ig_token),
            fetch_ig_insights(ig_user_id, ig_token, days),
            fetch_ig_recent_media(ig_user_id, ig_token),
        )
        errors = []
        if summary.get("error"):
            errors.append(f"Instagram summary: {summary.pop('error')}")
        if insights.get("error"):
            errors.append(f"Instagram insights: {insights.pop('error')}")
        for warning in insights.pop("warnings", []):
            errors.append(f"Instagram insight warning: {warning}")
        result["errors"].extend(errors)
        result["instagram"] = {**summary, "insights": insights, "recent_media": media}

    return result


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros)
