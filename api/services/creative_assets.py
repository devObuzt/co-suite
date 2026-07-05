from __future__ import annotations

import json
import mimetypes
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.admin import CreativeAsset
from ..models.suite import Suite
from .content_generator import _generate_image, _generate_video_media

log = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
CREATIVE_ROOT = STATIC_ROOT / "creative_assets"
CREATIVE_ROOT.mkdir(parents=True, exist_ok=True)

AUDIO_KINDS = {"sfx", "music", "transition"}
VISUAL_KINDS = {"visual_image", "visual_video"}
VIDEO_TRANSITION_KINDS = {"transition_video"}
ALL_KINDS = AUDIO_KINDS | VISUAL_KINDS | VIDEO_TRANSITION_KINDS
BUILTIN_LIBRARY_MANIFEST = CREATIVE_ROOT / "library" / "manifest.json"


def public_static_url(path: Path) -> str:
    try:
        relative = path.relative_to(STATIC_ROOT)
    except ValueError:
        return path.as_uri()
    return f"/static/{relative.as_posix()}"


def safe_asset_filename(filename: str | None, fallback: str = "asset") -> str:
    name = (filename or fallback).split("/")[-1].split("\\")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def classify_asset(filename: str, *, kind: str, prompt: str | None = None) -> dict[str, Any]:
    haystack = f"{filename} {prompt or ''}".lower()
    rules = [
        ("energy", ["energy", "upbeat", "fast", "jump", "pop", "طاقة", "حماس"]),
        ("happy", ["happy", "fun", "smile", "joy", "فرح", "مبهج"]),
        ("fashion", ["fashion", "style", "luxury", "glam", "فاشن", "ستايل", "فاخر"]),
        ("drama", ["drama", "sad", "slow", "dark", "دراما", "حزين"]),
        ("news", ["news", "alert", "report", "breaking", "اخبار", "خبر"]),
        ("shock", ["shock", "hit", "impact", "boom", "صادم", "ضربة"]),
        ("light", ["light", "flash", "shine", "glow", "اضاءة", "وميض"]),
        ("classic", ["classic", "soft", "piano", "كلاسيك", "هادئ"]),
        ("noise", ["noise", "static", "glitch", "distort", "ضجيج", "تشويش"]),
        ("whoosh", ["whoosh", "swipe", "sweep", "انتقال", "سحب"]),
        ("shutter", ["shutter", "camera", "كاميرا", "تصوير"]),
        ("notification", ["notification", "ringtone", "notify", "اشعار", "تنبيه"]),
        ("pop", ["pop", "bubble", "click", "بوب", "نقرة"]),
        ("film", ["film", "grain", "cinematic", "سينمائي", "فيلم"]),
        ("portrait", ["portrait", "9.16", "9:16", "vertical", "بورتريت", "عمودي"]),
        ("landscape", ["landscape", "16.9", "16:9", "horizontal", "لاندسكيب", "افقي"]),
        ("business", ["business", "office", "meeting", "market", "work", "اعمال", "مكتب"]),
        ("search", ["search", "google", "seo", "بحث", "جوجل"]),
    ]
    tags = [tag for tag, words in rules if any(word in haystack for word in words)]
    if kind == "transition" and not any(tag in tags for tag in ["whoosh", "light", "noise", "shock"]):
        tags.append("whoosh")
    if kind == "music" and not tags:
        tags.extend(["energy", "business"])
    if kind == "sfx" and not tags:
        tags.append("impact")
    if kind == "transition_video" and not any(tag in tags for tag in ["light", "film", "noise", "shock", "portrait", "landscape"]):
        tags.extend(["light", "portrait"])
    if kind in VISUAL_KINDS and not tags:
        tags.extend(["business", "energy"])
    return {
        "tags": sorted(set(tags)),
        "use_cases": suggested_use_cases(kind, tags),
        "auto_classified": True,
    }


def suggested_use_cases(kind: str, tags: list[str]) -> list[str]:
    if kind == "music":
        return ["background_music", "mood_bed"]
    if kind == "transition":
        return ["scene_boundary", "attention_beat", "text_hit"]
    if kind == "sfx":
        return ["attention_beat", "title_pop", "visual_accent"]
    if kind == "transition_video":
        return ["visual_transition", "scene_boundary", "flash_overlay"]
    if kind == "visual_video":
        return ["animated_background", "topic_cutaway", "scene_layer"]
    return ["background_image", "topic_cutaway", "scene_layer"]


async def list_active_assets(db: AsyncSession, *, kinds: set[str] | None = None) -> list[CreativeAsset]:
    query = select(CreativeAsset).where(CreativeAsset.active.is_(True)).order_by(CreativeAsset.usage_count.asc(), CreativeAsset.created_at.desc())
    if kinds:
        query = query.where(CreativeAsset.kind.in_(sorted(kinds)))
    return (await db.execute(query)).scalars().all()


def _score_asset(asset: CreativeAsset, scene_text: str, wanted_kind: str) -> int:
    score = 4 if asset.kind == wanted_kind else 0
    scene = scene_text.lower()
    for tag in asset.tags or []:
        if str(tag).lower() in scene:
            score += 3
    for use_case in asset.use_cases or []:
        if wanted_kind == "transition" and use_case in {"scene_boundary", "attention_beat", "text_hit"}:
            score += 2
        if wanted_kind in VISUAL_KINDS and use_case in {"animated_background", "topic_cutaway", "scene_layer"}:
            score += 2
    score -= min(asset.usage_count, 10)
    return score


def pick_asset(assets: list[CreativeAsset], *, kind: str, scene_text: str = "") -> CreativeAsset | None:
    candidates = [asset for asset in assets if asset.kind == kind]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: _score_asset(item, scene_text, kind), reverse=True)[0]


async def record_asset_usage(db: AsyncSession, asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    rows = (await db.execute(select(CreativeAsset).where(CreativeAsset.id.in_(asset_ids)))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.usage_count = int(row.usage_count or 0) + asset_ids.count(row.id)
        row.last_used_at = now
    await db.flush()


async def create_asset_from_bytes(
    db: AsyncSession,
    *,
    kind: str,
    title: str,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    source_url: str | None = None,
    created_by_user_id: str | None = None,
    classification_prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CreativeAsset:
    if kind not in ALL_KINDS:
        raise ValueError(f"Unsupported creative asset kind: {kind}")
    clean_filename = f"{uuid.uuid4().hex}_{safe_asset_filename(filename)}"
    folder = CREATIVE_ROOT / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / clean_filename
    path.write_bytes(data)
    guessed_type, _ = mimetypes.guess_type(path.name)
    media_type = content_type or guessed_type or "application/octet-stream"
    classification = classify_asset(title or filename, kind=kind, prompt=classification_prompt)
    row = CreativeAsset(
        kind=kind,
        title=title.strip() or safe_asset_filename(filename),
        storage_url=public_static_url(path),
        source_url=source_url,
        content_type=media_type,
        tags=classification["tags"],
        use_cases=classification["use_cases"],
        classification=classification,
        metadata_json={"filename": filename, **(metadata or {})},
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def create_asset_from_remote(
    db: AsyncSession,
    *,
    kind: str,
    source_url: str,
    title: str | None = None,
    created_by_user_id: str | None = None,
) -> CreativeAsset:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(source_url)
        response.raise_for_status()
    filename = safe_asset_filename(source_url.split("?", 1)[0], f"{kind}.bin")
    return await create_asset_from_bytes(
        db,
        kind=kind,
        title=title or filename,
        filename=filename,
        data=response.content,
        content_type=response.headers.get("content-type"),
        source_url=source_url,
        created_by_user_id=created_by_user_id,
    )


async def seed_builtin_creative_assets(db: AsyncSession) -> int:
    if not BUILTIN_LIBRARY_MANIFEST.exists():
        return 0
    try:
        manifest = json.loads(BUILTIN_LIBRARY_MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read built-in creative asset manifest: %s", exc)
        return 0

    entries = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return 0

    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 1937440217})

    changed = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip()
        storage_url = str(entry.get("storage_url") or "").strip()
        library_key = str(entry.get("library_key") or "").strip()
        if kind not in ALL_KINDS or not storage_url.startswith("/static/") or not library_key:
            continue
        source_url = f"builtin:{library_key}"
        with db.no_autoflush:
            row = (
                await db.execute(select(CreativeAsset).where(CreativeAsset.source_url == source_url))
            ).scalar_one_or_none()
        metadata = dict(entry.get("metadata") or {})
        metadata.update({"builtin": True, "library_key": library_key})
        if not row:
            row = CreativeAsset(kind=kind, title=str(entry.get("title") or library_key), storage_url=storage_url, source_url=source_url)
            db.add(row)
            changed += 1
        row.kind = kind
        row.title = str(entry.get("title") or row.title or library_key)
        row.storage_url = storage_url
        row.content_type = entry.get("content_type")
        row.duration_seconds = entry.get("duration_seconds")
        row.tags = entry.get("tags") or []
        row.use_cases = entry.get("use_cases") or suggested_use_cases(kind, row.tags or [])
        row.classification = entry.get("classification") or classify_asset(row.title, kind=kind)
        row.metadata_json = metadata
        row.active = bool(entry.get("active", True))
    if changed or entries:
        await db.commit()
    return changed


async def count_builtin_creative_assets(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(CreativeAsset).where(CreativeAsset.source_url.like("builtin:%"))
            )
        ).scalar_one()
        or 0
    )


async def generate_visual_asset_for_scene(
    db: AsyncSession,
    *,
    suite: Suite,
    scene_text: str,
    kind: str = "visual_image",
) -> CreativeAsset | None:
    base_prompt = (
        "Vertical 9:16 cinematic marketing background for a short social video. "
        "No readable text, no logos, no UI screenshots. Leave clean center space for a talking person. "
        "Make it modern, high-energy, premium, and clearly connected to this spoken line: "
        f"{scene_text}. Business name: {suite.name}."
    )
    if kind == "visual_video":
        video_prompt = (
            f"{base_prompt} Create subtle continuous motion: moving light streaks, depth, camera drift, "
            "soft particles or contextual b-roll movement. It should work as a background layer behind a speaker."
        )
        idea = {
            "id": f"visual-background-{uuid.uuid4().hex[:8]}",
            "division": "marketing",
            "topic": scene_text[:120],
            "aspect_ratio": "9:16",
            "video_subtype": "video_with_titles",
            "video_prompt": video_prompt,
            "video_title_en": "",
            "video_hook_en": "",
            "music_style": "silent visual background, no voiceover, no prominent music",
            "sfx_notes": "No sound is needed. Generate only a clean moving visual background.",
            "generation_request": {"model_tier": "fast"},
            "use_voiceover": False,
        }
        brand = {
            "name": suite.name,
            "industry": (suite.brand or {}).get("industry") if isinstance(suite.brand, dict) else None,
            "niche": (suite.brand or {}).get("niche") if isinstance(suite.brand, dict) else None,
            "services": (suite.brand or {}).get("services") if isinstance(suite.brand, dict) else [],
            "products": (suite.brand or {}).get("products") if isinstance(suite.brand, dict) else [],
            "target_audience": (suite.brand or {}).get("target_audience") if isinstance(suite.brand, dict) else None,
        }
        try:
            video_bytes = _generate_video_media(idea, brand)
        except Exception as exc:
            log.warning("Visual video background generation failed for suite %s: %s", suite.id, exc)
            return None
        if not video_bytes:
            return None
        return await create_asset_from_bytes(
            db,
            kind="visual_video",
            title=f"{suite.name} animated background",
            filename=f"{suite.slug or suite.id}-visual-background.mp4",
            data=video_bytes,
            content_type="video/mp4",
            source_url=None,
            created_by_user_id=None,
            classification_prompt=video_prompt,
            metadata={"scene_text": scene_text, "generated": True, "provider": "google_veo"},
        )

    if kind == "visual_image":
        image_bytes = _generate_image(base_prompt, "9:16", allow_imagen_fallback=True, visible_text=None)
        if not image_bytes:
            return None
        return await create_asset_from_bytes(
            db,
            kind="visual_image",
            title=f"{suite.name} visual background",
            filename=f"{suite.slug or suite.id}-visual.png",
            data=image_bytes,
            content_type="image/png",
            source_url=None,
            created_by_user_id=None,
            classification_prompt=base_prompt,
            metadata={"scene_text": scene_text, "generated": True, "provider": "google_image"},
        )

    return None


def serialize_creative_asset(asset: CreativeAsset) -> dict[str, Any]:
    def serialize_datetime(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    return {
        "id": asset.id,
        "kind": asset.kind,
        "title": asset.title,
        "storage_url": asset.storage_url,
        "source_url": asset.source_url,
        "content_type": asset.content_type,
        "duration_seconds": asset.duration_seconds,
        "tags": asset.tags or [],
        "use_cases": asset.use_cases or [],
        "classification": asset.classification or {},
        "active": asset.active,
        "usage_count": asset.usage_count,
        "last_used_at": serialize_datetime(asset.last_used_at),
        "metadata": asset.metadata_json or {},
        "created_at": serialize_datetime(asset.created_at),
        "updated_at": serialize_datetime(asset.updated_at),
    }
