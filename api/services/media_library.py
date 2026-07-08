"""Media library helpers: filing finished renders and building the browse tree.

The media library is a per-suite archive of finished assets. Items are grouped
into named libraries (e.g. finished talking-head montages) and browsed by
year/month derived from ``created_at``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from ..models.media_asset import MediaAsset
from ..models.suite import Suite

MONTAGE_TALKING_HEAD_LIBRARY = "montage_talking_head"

LIBRARY_LABELS: dict[str, str] = {
    MONTAGE_TALKING_HEAD_LIBRARY: "مونتاج — شخصية أمام الكاميرا",
}


def library_label(key: str) -> str:
    return LIBRARY_LABELS.get(key, key)


def montage_media_asset(suite: Suite, job_id: str, montage_result: Any) -> Optional[MediaAsset]:
    """Build the MediaAsset for a finished montage render, or None if the
    result was not rendered or its output never made it to public storage."""
    if not isinstance(montage_result, dict) or not montage_result.get("rendered"):
        return None
    output_url = str(montage_result.get("output_url") or "")
    if not output_url.startswith("https://"):
        return None

    render: dict = {}
    package = montage_result.get("video_montage")
    if isinstance(package, dict) and isinstance(package.get("render"), dict):
        render = package["render"]
    duration_seconds: Optional[float] = None
    raw_duration = render.get("duration_seconds")
    if raw_duration is not None:
        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError):
            duration_seconds = None

    created = datetime.now(timezone.utc)
    return MediaAsset(
        suite_id=suite.id,
        library=MONTAGE_TALKING_HEAD_LIBRARY,
        title=f"مونتاج {suite.name} — {created:%Y-%m-%d}",
        url=output_url,
        content_type="video/mp4",
        duration_seconds=duration_seconds,
        source_job_id=job_id,
    )


def build_media_tree(rows: Iterable[Sequence]) -> list[dict]:
    """Turn (library, year, month, count) aggregation rows into the nested
    libraries -> years -> months payload the frontend renders.

    Postgres EXTRACT returns Decimal, so year/month are coerced with int().
    Years and months are sorted newest first.
    """
    libraries: dict[str, dict[int, dict[int, int]]] = {}
    for library, year, month, count in rows:
        years = libraries.setdefault(str(library), {})
        months = years.setdefault(int(year), {})
        month_key = int(month)
        months[month_key] = months.get(month_key, 0) + int(count)

    payload: list[dict] = []
    for library in sorted(libraries):
        years_payload = []
        for year in sorted(libraries[library], reverse=True):
            months_payload = [
                {"month": f"{month:02d}", "count": libraries[library][year][month]}
                for month in sorted(libraries[library][year], reverse=True)
            ]
            years_payload.append({"year": year, "months": months_payload})
        payload.append({"key": library, "label": library_label(library), "years": years_payload})
    return payload


def serialize_media_asset(asset: MediaAsset) -> dict:
    return {
        "id": asset.id,
        "title": asset.title,
        "url": asset.url,
        "thumbnail_url": asset.thumbnail_url,
        "content_type": asset.content_type,
        "duration_seconds": asset.duration_seconds,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }
