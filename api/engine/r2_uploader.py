"""Cloudflare R2 uploader — hosts media so social platforms can fetch it.

Instagram Reels, TikTok, etc. require media accessible at a public HTTPS URL.
This module uploads to an R2 bucket and returns the public URL.

R2 is S3-compatible, so we use boto3 with a custom endpoint.
"""
import logging
import mimetypes
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import (
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET,
    R2_PUBLIC_URL_PREFIX,
    R2_SECRET_ACCESS_KEY,
)

log = logging.getLogger(__name__)

_endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None


def _client():
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        raise RuntimeError("R2 credentials missing — fill them in .env")
    return boto3.client(
        "s3",
        endpoint_url=_endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def ensure_bucket(bucket: str = R2_BUCKET) -> None:
    """Create the bucket if it doesn't exist."""
    c = _client()
    try:
        c.head_bucket(Bucket=bucket)
        log.info("Bucket '%s' already exists", bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            log.info("Creating bucket '%s'…", bucket)
            c.create_bucket(Bucket=bucket)
        else:
            raise


def upload(local_path: Path | str, key: str | None = None) -> str:
    """Upload a local file to R2.

    Returns the public HTTPS URL (requires R2_PUBLIC_URL_PREFIX to be set,
    which means the bucket must have r2.dev public access enabled OR a
    custom domain mapped in Cloudflare).
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    if not R2_PUBLIC_URL_PREFIX:
        raise RuntimeError(
            "R2_PUBLIC_URL_PREFIX is empty. Enable r2.dev for the bucket "
            "in Cloudflare dashboard and paste the URL into .env."
        )

    key = key or local_path.name
    content_type, _ = mimetypes.guess_type(local_path.name)
    content_type = content_type or "application/octet-stream"

    log.info("Uploading %s → r2://%s/%s", local_path, R2_BUCKET, key)
    _client().upload_file(
        Filename=str(local_path),
        Bucket=R2_BUCKET,
        Key=key,
        ExtraArgs={"ContentType": content_type},
    )

    url = R2_PUBLIC_URL_PREFIX.rstrip("/") + "/" + key
    log.info("Public URL: %s", url)
    return url


def upload_for_post(local_path: Path | str, post_id: str, filename: str | None = None) -> str:
    """Upload a media file for a given post; key = posts/<post_id>/<filename>."""
    local_path = Path(local_path)
    fname = filename or local_path.name
    key = f"posts/{post_id}/{fname}"
    return upload(local_path, key=key)
