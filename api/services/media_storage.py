import logging
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from ..core.config import settings

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
