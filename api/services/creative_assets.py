from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.admin import CreativeAsset
from ..models.suite import Suite
from .content_generator import _generate_image

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
CREATIVE_ROOT = STATIC_ROOT / "creative_assets"
CREATIVE_ROOT.mkdir(parents=True, exist_ok=True)

AUDIO_KINDS = {"sfx", "music", "transition"}
VISUAL_KINDS = {"visual_image", "visual_video"}
ALL_KINDS = AUDIO_KINDS | VISUAL_KINDS


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
    await db.commit()


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
    classification = classify_asset(title or filename, kind=kind)
    row = CreativeAsset(
        kind=kind,
        title=title.strip() or safe_asset_filename(filename),
        storage_url=public_static_url(path),
        source_url=source_url,
        content_type=media_type,
        tags=classification["tags"],
        use_cases=classification["use_cases"],
        classification=classification,
        metadata_json={"filename": filename},
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


async def generate_visual_asset_for_scene(
    db: AsyncSession,
    *,
    suite: Suite,
    scene_text: str,
    kind: str = "visual_image",
) -> CreativeAsset | None:
    if kind != "visual_image":
        return None
    prompt = (
        "Vertical cinematic marketing background for a short social video. "
        "No text, no logos, leave clean center space for a talking person. "
        "Make it modern, high-energy, premium, suitable for this spoken line: "
        f"{scene_text}. Business name: {suite.name}."
    )
    image_bytes = _generate_image(prompt, "9:16", allow_imagen_fallback=True, visible_text=None)
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
    )


def serialize_creative_asset(asset: CreativeAsset) -> dict[str, Any]:
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
        "last_used_at": asset.last_used_at,
        "metadata": asset.metadata_json or {},
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }
