#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.creative_assets import classify_asset, suggested_use_cases  # noqa: E402

STATIC_LIBRARY = ROOT / "api" / "static" / "creative_assets" / "library"
MANIFEST_PATH = STATIC_LIBRARY / "manifest.json"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def slugify(value: str) -> str:
    value = value.strip().replace("&", "and")
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip(".-_").lower() or "asset"


def title_from_path(path: Path) -> str:
    title = path.stem.replace("-", " ").replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title[:1].upper() + title[1:] if title else path.stem


def duration_seconds(path: Path) -> float | None:
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()
        return round(float(output), 3) if output else None
    except Exception:
        return None


def detect_kind(relative: Path) -> str | None:
    parts = [part.lower() for part in relative.parts]
    suffix = relative.suffix.lower()
    if suffix not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
        return None
    if "__macosx" in parts or relative.name.startswith("._") or relative.name == ".DS_Store":
        return None
    if "music" in parts and suffix in AUDIO_EXTENSIONS:
        return "music"
    if "sfx" in parts and suffix in AUDIO_EXTENSIONS:
        return "sfx"
    if any("trasnitions" in part or "transitions" in part for part in parts) and suffix in VIDEO_EXTENSIONS:
        return "transition_video"
    return None


def extra_tags(relative: Path, kind: str) -> list[str]:
    haystack = relative.as_posix().lower()
    tags: list[str] = []
    if "portrait" in haystack or "9.16" in haystack or "9:16" in haystack:
        tags.extend(["portrait", "9:16"])
    if "landscape" in haystack or "16.9" in haystack or "16:9" in haystack:
        tags.extend(["landscape", "16:9"])
    if "flash" in haystack:
        tags.extend(["light", "flash"])
    if "film" in haystack:
        tags.extend(["film", "classic"])
    if "shutter" in haystack:
        tags.extend(["shutter", "camera"])
    if "notification" in haystack or "ringtone" in haystack:
        tags.extend(["notification", "scifi"])
    if "swoosh" in haystack or "whoosh" in haystack:
        tags.extend(["whoosh", "transition"])
    if "fashion" in haystack:
        tags.append("fashion")
    if "luxe" in haystack or "prestige" in haystack:
        tags.extend(["luxury", "fashion"])
    if kind == "music" and not tags:
        tags.extend(["energy", "business"])
    return tags


def entry_for_file(source: Path, relative: Path) -> dict:
    kind = detect_kind(relative)
    if not kind:
        raise ValueError(f"Unsupported asset path: {relative}")
    orientation = "portrait" if "portrait" in [p.lower() for p in relative.parts] else "landscape" if "landscape" in [p.lower() for p in relative.parts] else None
    subdir = kind if not orientation else f"{kind}/{orientation}"
    digest = hashlib.sha1(relative.as_posix().encode("utf-8")).hexdigest()[:10]
    filename = f"{slugify(source.stem)}-{digest}{source.suffix.lower()}"
    target = STATIC_LIBRARY / subdir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    storage_url = f"/static/creative_assets/library/{subdir}/{filename}"
    title = title_from_path(source)
    prompt = f"{relative.as_posix()} {title}"
    classification = classify_asset(title, kind=kind, prompt=prompt)
    tags = sorted(set([*classification.get("tags", []), *extra_tags(relative, kind)]))
    use_cases = suggested_use_cases(kind, tags)
    content_type = mimetypes.guess_type(target.name)[0] or ("video/mp4" if kind == "transition_video" else "audio/mpeg")
    return {
        "library_key": hashlib.sha1(storage_url.encode("utf-8")).hexdigest(),
        "kind": kind,
        "title": title,
        "storage_url": storage_url,
        "content_type": content_type,
        "duration_seconds": duration_seconds(target),
        "tags": tags,
        "use_cases": use_cases,
        "classification": {
            **classification,
            "tags": tags,
            "use_cases": use_cases,
            "source_folder": relative.parent.as_posix(),
        },
        "metadata": {
            "original_path": relative.as_posix(),
            "orientation": orientation,
            "library": "Videos Assets",
        },
        "active": True,
    }


def import_zip(zip_path: Path, *, clean: bool = False) -> dict:
    if clean and STATIC_LIBRARY.exists():
        shutil.rmtree(STATIC_LIBRARY)
    STATIC_LIBRARY.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="oneshare-video-assets-") as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_dir)

        entries = []
        for source in sorted(tmp_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(tmp_dir)
            if detect_kind(relative):
                entries.append(entry_for_file(source, relative))

    entries.sort(key=lambda item: (item["kind"], item["metadata"].get("orientation") or "", item["title"]))
    manifest = {
        "source": zip_path.name,
        "asset_count": len(entries),
        "assets": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the OneShare video montage creative asset library.")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--clean", action="store_true", help="Remove the existing built-in library before importing.")
    args = parser.parse_args()
    manifest = import_zip(args.zip_path, clean=args.clean)
    counts: dict[str, int] = {}
    for asset in manifest["assets"]:
        counts[asset["kind"]] = counts.get(asset["kind"], 0) + 1
    print(f"Imported {manifest['asset_count']} assets into {STATIC_LIBRARY}")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
