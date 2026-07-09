from __future__ import annotations

import asyncio
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
from .media_storage import r2_configured, upload_bytes

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


async def list_user_background_assets(db: AsyncSession, suite_id: str) -> list[CreativeAsset]:
    """Active user-uploaded background assets belonging to one suite, newest first."""
    rows = (
        await db.execute(
            select(CreativeAsset)
            .where(CreativeAsset.active.is_(True))
            .where(CreativeAsset.kind.in_(sorted(VISUAL_KINDS)))
            .order_by(CreativeAsset.created_at.desc())
        )
    ).scalars().all()
    return [row for row in rows if is_user_uploaded_asset(row) and _asset_suite_id(row) == str(suite_id)]


def _asset_suite_id(asset: CreativeAsset) -> str | None:
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    value = meta.get("suite_id")
    return str(value) if value else None


def is_user_uploaded_asset(asset: CreativeAsset) -> bool:
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return bool(meta.get("user_uploaded"))


def user_uploaded_suite_assets(assets: list[CreativeAsset], suite_id: str | None) -> list[CreativeAsset]:
    """The suite's own user-uploaded visual backgrounds."""
    if not suite_id:
        return []
    return [
        asset
        for asset in assets
        if asset.kind in VISUAL_KINDS and is_user_uploaded_asset(asset) and _asset_suite_id(asset) == str(suite_id)
    ]


# A fresh same-suite user upload scores at least kind(+4) + suite(+6) + user(+8);
# anything above this floor still counts as a usable match even after usage and
# recency penalties. The floor alone is NOT enough to "win" a scene in blend
# mode: user_background_matches_scene additionally requires a real tag match
# with the scene text, so the flat bonuses can never clear the gate by
# themselves.
MINIMAL_USER_BACKGROUND_SCORE = 12

# Analysis wording that marks a user upload as unusable behind a speaker:
# screen recordings, app UI, and text-heavy frames read as glitches when
# composited under captions and a talking head.
UNUSABLE_BACKGROUND_HINTS = (
    "screenshot",
    "screen shot",
    "screen recording",
    "screen-recording",
    "screen capture",
    "screencast",
    "user interface",
    "app interface",
    "software interface",
    "app screen",
    "computer screen",
    "phone screen",
    "mobile screen",
    "web page",
    "webpage",
    "website",
    "browser window",
    "dashboard",
)


def is_asset_unusable_for_background(asset: CreativeAsset) -> bool:
    """True when a user upload must never be used as a scene background.

    Covers uploads whose vision analysis found burned-in text
    (``analysis.has_text``) or whose description/tags read as a screen
    recording / UI capture.
    """
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
    if bool(analysis.get("has_text")):
        return True
    analysis_tags = analysis.get("tags") if isinstance(analysis.get("tags"), list) else []
    haystack = " ".join(
        [str(analysis.get("description") or "")]
        + [str(tag) for tag in analysis_tags]
        + [str(tag) for tag in (asset.tags or [])]
    ).lower()
    return any(hint in haystack for hint in UNUSABLE_BACKGROUND_HINTS)


def _scene_tag_match_count(asset: CreativeAsset, scene_text: str) -> int:
    """How many of the asset's tags literally appear in the scene text."""
    scene = scene_text.lower()
    return sum(1 for tag in asset.tags or [] if str(tag).strip() and str(tag).lower() in scene)


def user_background_matches_scene(
    asset: CreativeAsset,
    scene_text: str,
    suite_id: str | None,
    *,
    min_score: int = MINIMAL_USER_BACKGROUND_SCORE,
) -> bool:
    """Blend-mode quality gate: does this user upload really fit the scene?

    Requires at least one tag/analysis match with the scene text on top of
    the score floor, so the flat kind+suite+user bonuses alone never let a
    random upload win a scene. Screen-recording/has_text uploads never match.
    """
    if is_asset_unusable_for_background(asset):
        return False
    if _scene_tag_match_count(asset, scene_text) == 0:
        return False
    return _score_asset(asset, scene_text, asset.kind, suite_id) >= min_score


def has_user_background_match(
    assets: list[CreativeAsset],
    *,
    scene_text: str,
    suite_id: str | None,
    min_score: int = MINIMAL_USER_BACKGROUND_SCORE,
) -> bool:
    """True when a user-uploaded suite background matches this scene well enough."""
    for asset in user_uploaded_suite_assets(assets, suite_id):
        if user_background_matches_scene(asset, scene_text, suite_id, min_score=min_score):
            return True
    return False


def filter_assets_for_backgrounds_mode(
    assets: list[CreativeAsset],
    *,
    mode: str,
    suite_id: str | None,
    selected_ids: list[str] | set[str] | None = None,
) -> tuple[list[CreativeAsset], bool]:
    """Apply the job's backgrounds_mode + explicit selection to the asset pool.

    Returns ``(assets, allow_generated_backgrounds)``. Uploads are a LIBRARY:
    a user-uploaded background participates in a render ONLY when its id is in
    this job's ``selected_ids``. No selection (empty/None) means every user
    upload is excluded and the render behaves as if the feature didn't exist
    (generated/library backgrounds only). In every mode:

    - user uploads belonging to a DIFFERENT suite are hard-excluded — another
      client's media must never even be scoreable for this suite's videos;
    - user uploads flagged as screen recordings / UI / burned-in text are
      quality-excluded from the visual pool (logged).

    In ``user_only`` mode (and only when the job actually selected usable user
    uploads) visual candidates are additionally restricted to the selected
    backgrounds and AI background generation is disabled; audio/transition
    assets always pass through untouched. ``user_only`` without a usable
    selection falls back to the default generated/blend behaviour.
    """
    selection = {str(item) for item in (selected_ids or []) if str(item).strip()}
    kept: list[CreativeAsset] = []
    for asset in assets:
        if asset.kind not in VISUAL_KINDS or not is_user_uploaded_asset(asset):
            kept.append(asset)
            continue
        if not suite_id or _asset_suite_id(asset) != str(suite_id):
            log.warning(
                "Excluding foreign-suite user background %s (asset suite %s, montage suite %s) from candidate pool",
                asset.id,
                _asset_suite_id(asset),
                suite_id,
            )
            continue
        if str(asset.id) not in selection:
            log.info(
                "Excluding user background %s for suite %s: not selected for this job (library-only upload)",
                asset.id,
                suite_id,
            )
            continue
        if is_asset_unusable_for_background(asset):
            log.warning(
                "Skipping user background %s for suite %s: analysis flags it as screen recording/UI/text-heavy, unusable behind a speaker",
                asset.id,
                suite_id,
            )
            continue
        kept.append(asset)
    user_assets = user_uploaded_suite_assets(kept, suite_id)
    if mode == "user_only" and user_assets:
        user_ids = {asset.id for asset in user_assets}
        filtered = [asset for asset in kept if asset.kind not in VISUAL_KINDS or asset.id in user_ids]
        return filtered, False
    return kept, True


def _score_asset(asset: CreativeAsset, scene_text: str, wanted_kind: str, suite_id: str | None = None) -> int:
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
    # Backgrounds belong to their suite: prefer own visuals, never leak another
    # client's generated backgrounds into this suite's videos.
    asset_suite = _asset_suite_id(asset)
    if suite_id and asset_suite:
        if asset_suite == suite_id:
            score += 6
            # The user's own uploads beat suite-generated backgrounds, which
            # beat the shared library: user upload > generated > library.
            if is_user_uploaded_asset(asset):
                score += 8
        elif wanted_kind in VISUAL_KINDS:
            score -= 20
    last_used = asset.last_used_at
    if last_used is not None:
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last_used).total_seconds() < 24 * 3600:
            score -= 3
    score -= min(asset.usage_count, 10)
    return score


def pick_asset(
    assets: list[CreativeAsset],
    *,
    kind: str,
    scene_text: str = "",
    suite_id: str | None = None,
    variety_seed: int = 0,
    user_match_required: bool = False,
) -> CreativeAsset | None:
    candidates = [asset for asset in assets if asset.kind == kind]
    if kind in VISUAL_KINDS and user_match_required:
        # Blend mode: a user upload only wins a scene when it genuinely
        # matches the scene text — otherwise generated/library media compete
        # for the slot instead.
        gated: list[CreativeAsset] = []
        for asset in candidates:
            if is_user_uploaded_asset(asset) and not user_background_matches_scene(asset, scene_text, suite_id):
                log.info(
                    "User background %s does not match scene text well enough; leaving the scene to generated/library media",
                    asset.id,
                )
                continue
            gated.append(asset)
        candidates = gated
    if not candidates:
        return None
    scored = sorted(
        ((asset, _score_asset(asset, scene_text, kind, suite_id)) for asset in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    if kind in VISUAL_KINDS:
        # Rotate between the top candidates so consecutive renders vary. The
        # rotation pool never contains negative-relevance assets (e.g. another
        # suite's generated backgrounds), so variety can't reintroduce what
        # scoring pushed out.
        usable = [asset for asset, score in scored if score >= 0]
        if not usable:
            return None
        pool = usable[: min(3, len(usable))]
        return pool[variety_seed % len(pool)]
    return scored[0][0]


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
    guessed_type, _ = mimetypes.guess_type(clean_filename)
    media_type = content_type or guessed_type or "application/octet-stream"

    # Containers are ephemeral: a worker-local /static file dies on the next
    # redeploy and leaves a dead DB row behind, so durable storage (R2) is the
    # primary target. Local disk is only a dev/self-hosted fallback.
    storage_url: str | None = None
    if r2_configured():
        try:
            stored = await asyncio.to_thread(
                upload_bytes, f"creative_assets/{kind}/{clean_filename}", data, media_type
            )
            storage_url = stored.url
        except Exception:
            log.exception("R2 upload failed for creative asset %s; falling back to local storage", clean_filename)
    if not storage_url:
        folder = CREATIVE_ROOT / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / clean_filename
        path.write_bytes(data)
        storage_url = public_static_url(path)

    classification = classify_asset(title or filename, kind=kind, prompt=classification_prompt)
    row = CreativeAsset(
        kind=kind,
        title=title.strip() or safe_asset_filename(filename),
        storage_url=storage_url,
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
        "Background plate only: absolutely no people, faces, hands, bodies, or human silhouettes — "
        "a real person is composited on top and any generated human reads as a glitch. "
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
            metadata={"scene_text": scene_text, "generated": True, "provider": "google_veo", "suite_id": suite.id},
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
            metadata={"scene_text": scene_text, "generated": True, "provider": "google_image", "suite_id": suite.id},
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
