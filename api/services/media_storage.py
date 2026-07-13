import logging
import mimetypes
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import httpx

from ..core.config import settings
from ..core.external_calls import external_call
from ..models.content import ContentPost, PostFormat

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static" / "posts"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StoredMedia:
    url: str
    backend: str
    key: Optional[str] = None
    public: bool = False
    content_type: str = "application/octet-stream"

    def to_dict(self) -> dict:
        return asdict(self)


def r2_configured() -> bool:
    return bool(
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket_name
        and settings.r2_public_url
    )


def storage_status() -> dict:
    missing = []
    checks = {
        "R2_ACCOUNT_ID": bool(settings.r2_account_id),
        "R2_ACCESS_KEY_ID": bool(settings.r2_access_key_id),
        "R2_SECRET_ACCESS_KEY": bool(settings.r2_secret_access_key),
        "R2_BUCKET_NAME": bool(settings.r2_bucket_name),
        "R2_PUBLIC_URL": bool(settings.r2_public_url),
    }
    for key, present in checks.items():
        if not present:
            missing.append(key)

    configured = not missing
    warnings = []
    if not configured:
        warnings.append("Generated media will fall back to local storage and may disappear after redeploys.")
        warnings.append("Publishing media to Meta requires a public HTTPS storage URL.")
    elif not settings.r2_public_url.startswith("https://"):
        configured = False
        warnings.append("R2_PUBLIC_URL must start with https:// so social platforms can fetch media.")

    return {
        "configured": configured,
        "backend": "r2" if configured else "local",
        "public": configured,
        "bucket_configured": bool(settings.r2_bucket_name),
        "public_url_configured": bool(settings.r2_public_url),
        "missing": missing,
        "warnings": warnings,
    }


def storage_test_key() -> str:
    return f"healthchecks/{uuid.uuid4().hex}.txt"


async def test_public_storage() -> dict:
    status = storage_status()
    if not status["configured"]:
        return {
            **status,
            "ok": False,
            "uploaded": False,
            "public_fetch_ok": False,
            "error": "R2 storage is not fully configured.",
        }

    try:
        stored = upload_bytes(
            storage_test_key(),
            b"co-suite storage health check\n",
            "text/plain; charset=utf-8",
        )
    except Exception as exc:
        return {
            **status,
            "ok": False,
            "uploaded": False,
            "public_fetch_ok": False,
            "error": str(exc),
        }

    try:
        async with external_call("r2", "verify_public_url", key=stored.key) as call:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.head(stored.url)
                if response.status_code in (405, 403):
                    response = await client.get(stored.url)
            call.note(status_code=response.status_code)
            public_ok = 200 <= response.status_code < 300
            if not public_ok:
                call.fail(f"Public URL returned HTTP {response.status_code}")
        return {
            **status,
            "ok": public_ok,
            "uploaded": True,
            "public_fetch_ok": public_ok,
            "status_code": response.status_code,
            "url": stored.url,
            "key": stored.key,
            "error": None if public_ok else f"Public URL returned HTTP {response.status_code}.",
        }
    except Exception as exc:
        return {
            **status,
            "ok": False,
            "uploaded": True,
            "public_fetch_ok": False,
            "url": stored.url,
            "key": stored.key,
            "error": str(exc),
        }


def _r2_client():
    if not r2_configured():
        raise RuntimeError("R2 storage is not configured")

    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def _public_url(key: str) -> str:
    return f"{settings.r2_public_url.rstrip('/')}/{key}"


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredMedia:
    with external_call("r2", "upload_object", key=key, size_bytes=len(data)):
        _r2_client().put_object(
            Bucket=settings.r2_bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    return StoredMedia(
        url=_public_url(key),
        backend="r2",
        key=key,
        public=True,
        content_type=content_type,
    )


def save_local(filename: str, data: bytes, content_type: str = "application/octet-stream") -> StoredMedia:
    path = STATIC_DIR / filename
    path.write_bytes(data)
    return StoredMedia(
        url=f"/static/posts/{filename}",
        backend="local",
        key=str(path),
        public=False,
        content_type=content_type,
    )


def store_post_media(
    post_id: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> StoredMedia:
    if r2_configured():
        try:
            return upload_bytes(f"posts/{post_id}/{filename}", data, content_type)
        except Exception as exc:
            log.warning("R2 upload failed for %s, falling back to local storage: %s", filename, exc)

    return save_local(filename, data, content_type)


def store_brand_asset(
    suite_id: str,
    asset_type: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> StoredMedia:
    if not r2_configured():
        raise RuntimeError("Storage not configured")
    key = f"{asset_type}s/{suite_id}/{filename}"
    return upload_bytes(key, data, content_type)


def upload_static_path(static_path: str, content_type: Optional[str] = None) -> StoredMedia:
    if static_path.startswith("https://"):
        return StoredMedia(url=static_path, backend="remote", public=True)
    if not r2_configured():
        raise RuntimeError("R2 storage is not configured")

    local = Path(__file__).parent.parent / static_path.lstrip("/")
    if not local.exists():
        raise FileNotFoundError(local)

    guessed_type, _ = mimetypes.guess_type(local.name)
    media_type = content_type or guessed_type or "application/octet-stream"
    key = f"posts/legacy/{local.name}"
    return upload_bytes(key, local.read_bytes(), media_type)


def _media_item(url: str) -> dict:
    public = url.startswith("https://")
    if public:
        backend = "r2" if settings.r2_public_url and url.startswith(settings.r2_public_url.rstrip("/")) else "remote"
    elif url.startswith("/static/"):
        backend = "local"
    else:
        backend = "unsupported"
    return {
        "url": url,
        "backend": backend,
        "public": public,
        "publish_ready": public,
    }


def platform_media_for_post(post: ContentPost, platform: str) -> list[str]:
    meta = post.ai_metadata or {}
    platform_media = meta.get("platform_media") or {}
    urls = platform_media.get(platform) or []
    if urls:
        return [url for url in urls if isinstance(url, str) and url]
    return [url for url in (post.media_urls or []) if isinstance(url, str) and url]


def _media_readiness_for_urls(post: ContentPost, urls: list[str]) -> dict:
    meta = post.ai_metadata or {}
    requires_media = meta.get("requires_media")
    if requires_media is None:
        requires_media = meta.get("content_type") != "text" and post.format in {
            PostFormat.image,
            PostFormat.carousel,
            PostFormat.video,
        }

    items = [_media_item(url) for url in urls]

    if not requires_media:
        return {
            "state": "not_required",
            "publish_ready": True,
            "reason": None,
            "items": items,
        }
    if not urls:
        failed = bool(meta.get("media_error") or meta.get("media_generation_failed"))
        return {
            "state": "failed" if failed else "missing",
            "publish_ready": False,
            "reason": (
                "Media generation failed. You can retry generation or publish as text only where supported."
                if failed
                else "No generated media is attached to this post."
            ),
            "items": [],
        }
    if all(item["public"] for item in items):
        return {
            "state": "ready",
            "publish_ready": True,
            "reason": None,
            "items": items,
        }
    if any(item["backend"] == "local" for item in items):
        return {
            "state": "local-only",
            "publish_ready": False,
            "reason": "Media is stored locally and is not available as a durable public HTTPS URL.",
            "items": items,
        }
    return {
        "state": "unsupported",
        "publish_ready": False,
        "reason": "Media URL is not a supported public HTTPS URL.",
        "items": items,
    }


def media_readiness_for_post(post: ContentPost, platforms: Optional[list[str]] = None) -> dict:
    requested_platforms = [platform for platform in (platforms or []) if platform in {"facebook", "instagram"}]
    if not requested_platforms:
        urls = [url for url in (post.media_urls or []) if isinstance(url, str) and url]
        return _media_readiness_for_urls(post, urls)

    platform_states = {
        platform: _media_readiness_for_urls(post, platform_media_for_post(post, platform))
        for platform in requested_platforms
    }
    if len(platform_states) == 1:
        platform, state = next(iter(platform_states.items()))
        return {**state, "platforms": {platform: state}}

    if all(state.get("publish_ready") for state in platform_states.values()):
        aggregate_state = "ready"
        if all(state.get("state") == "not_required" for state in platform_states.values()):
            aggregate_state = "not_required"
        return {
            "state": aggregate_state,
            "publish_ready": True,
            "reason": None,
            "platforms": platform_states,
        }

    reasons = [
        f"{platform}: {state.get('reason')}"
        for platform, state in platform_states.items()
        if not state.get("publish_ready") and state.get("reason")
    ]
    state_names = {state.get("state") for state in platform_states.values()}
    return {
        "state": state_names.pop() if len(state_names) == 1 else "blocked",
        "publish_ready": False,
        "reason": " ".join(reasons) or "One or more requested platforms do not have publish-ready media.",
        "platforms": platform_states,
    }
