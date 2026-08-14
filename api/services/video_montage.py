from __future__ import annotations

import asyncio
import json
import logging
import zlib
import math
import mimetypes
import random
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Any, Callable

import httpx
import requests
from sqlalchemy.ext.asyncio import AsyncSession
from arabic_reshaper import reshape
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from ..core.config import settings
from ..core.external_calls import external_call
from ..core.observability import log_event
from ..models.admin import CreativeAsset
from ..models.suite import Suite
from .media_storage import r2_configured, upload_bytes
from .montage_magic_director import (
    CLASSIC_TEMPLATES,
    MAGIC_SFX_QUERIES,
    MAGIC_TEMPLATE,
    MAGIC_TEMPLATES,
    apply_magic_directions,
    heuristic_magic_direction,
    montage_template,
)
from .montage_notes_analyzer import analyze_and_apply_montage_notes
from .montage_shot_list import generate_shot_list
from .creative_assets import (
    AUDIO_KINDS,
    VIDEO_TRANSITION_KINDS,
    VISUAL_KINDS,
    filter_assets_for_backgrounds_mode,
    generate_visual_asset_for_scene,
    has_user_background_match,
    list_active_assets,
    pick_asset,
    record_asset_usage,
    serialize_creative_asset,
)

log = logging.getLogger(__name__)

ProgressWriter = Callable[[dict[str, Any]], None]

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MONTAGE_ROOT = STATIC_ROOT / "video_montage"
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
MAX_REMOTE_BYTES = 500 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 45
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MAX_DISTINCT_BACKGROUND_VIDEOS = 2
MAX_MONTAGE_SCENES = 24
# Magic works in micro-frames (owner-approved range: 0.8-2.3 seconds), so it
# needs a much larger scene budget than the default template.
MAGIC_MAX_MONTAGE_SCENES = 48
MAGIC_MAX_BEAT_SECONDS = 2.3
TRANSITION_FRAMES = 7
FAL_VEED_MODEL = "veed/video-background-removal"
# Speech cleanup chain shared by the V1 mixer and the Remotion audio extract.
VOICE_CLEANUP_AUDIO_FILTER = "highpass=f=80,lowpass=f=12000,afftdn,loudnorm=I=-16:LRA=11:TP=-1.5"


def job_dir(job_id: str) -> Path:
    path = MONTAGE_ROOT / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_static_url(path: Path) -> str:
    try:
        relative = path.relative_to(STATIC_ROOT)
    except ValueError:
        return path.as_uri()
    return f"/static/{relative.as_posix()}"


def publish_montage_media(job_id: str, local_url: str | None) -> str | None:
    """Rewrite a worker-local /static URL to a public R2 URL.

    The montage worker and the API run in separate containers, so files left
    under the worker's static dir are unreachable through the API's /static.
    """
    url = str(local_url or "")
    if not url.startswith("/static/"):
        return local_url
    path = STATIC_ROOT / url.removeprefix("/static/")
    if not path.exists() or not r2_configured():
        return local_url
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        stored = upload_bytes(f"video_montage/{job_id}/{path.name}", path.read_bytes(), content_type)
        return stored.url
    except Exception:
        log.exception("Failed to publish montage media %s to R2; leaving local URL", path)
        return local_url


def normalize_montage_source(source_path: Path, output_dir: Path) -> Path | None:
    """Downscale/transcode the source to fit 1080x1920 H.264 before provider processing.

    The output montage is 1080x1920 anyway, and the container's libvpx decoder
    rejects VP9 frames beyond 5120x3200 — 4K portrait sources (2160x3840) from
    VEED were undecodable without this.
    """
    target = output_dir / "normalized-source.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    width, height = probe_video_dimensions(source_path)
    if (
        source_path.suffix.lower() == ".mp4"
        and 0 < width <= 1080
        and 0 < height <= 1920
        and probe_video_codec(source_path) == "h264"
    ):
        # Already provider-compliant (e.g. a pre-staged preview source) —
        # re-encoding it would only burn minutes.
        return source_path
    try:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-vf",
                "scale=w=1080:h=1920:force_original_aspect_ratio=decrease:force_divisible_by=2",
                # 24fps: VEED bills per frame — 20% off with no visible cost.
                "-r",
                "24",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(target),
            ]
        )
    except Exception:
        log.exception("Failed to normalize montage source %s", source_path)
        return None
    return target if target.exists() and target.stat().st_size > 0 else None


def publish_veed_source(job_id: str, source_path: Path) -> str | None:
    """Upload the normalized source to R2 and return a public URL for VEED/fal."""
    if not r2_configured():
        return None
    try:
        stored = upload_bytes(
            f"video_montage/{job_id}/{source_path.name}",
            source_path.read_bytes(),
            "video/mp4",
        )
        return stored.url
    except Exception:
        log.exception("Failed to publish normalized montage source %s to R2", source_path)
        return None


def remotion_public_asset_path(storage_url: str, work_dir: Path, asset_id: str | None = None) -> str | None:
    if storage_url.startswith("http://") or storage_url.startswith("https://"):
        return storage_url
    if not storage_url.startswith("/static/"):
        return storage_url or None
    source = STATIC_ROOT / storage_url.removeprefix("/static/")
    if not source.exists():
        log.warning("Skipping missing local Remotion creative asset %s at %s", asset_id or storage_url, source)
        return None
    target_dir = work_dir / "public" / "remotion" / "creative-assets"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = safe_filename(f"{asset_id or source.stem}{source.suffix}", source.name)
    target = target_dir / target_name
    try:
        if not target.exists():
            # 4K library clips (e.g. HEVC transitions) blow up the compositor's
            # decode memory; bring anything above 1080x1920 down before render.
            if is_video_file(source) and max(probe_video_dimensions(source)) > 1920:
                try:
                    run_command(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(source),
                            "-vf",
                            "scale=w=1080:h=1920:force_original_aspect_ratio=decrease:force_divisible_by=2",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-crf",
                            "22",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "128k",
                            str(target),
                        ]
                    )
                except Exception:
                    target.unlink(missing_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)
        if is_video_file(target) and probe_duration_seconds(target) <= 0:
            log.warning(
                "Skipping unreadable Remotion creative asset %s at %s (ffprobe found no duration)",
                asset_id or storage_url,
                target,
            )
            return None
        return f"/remotion/creative-assets/{target.name}"
    except OSError:
        log.exception("Failed to prepare Remotion creative asset %s", asset_id or source.name)
        return None


def creative_asset_file_available(asset: Any) -> bool:
    storage_url = str(getattr(asset, "storage_url", "") or "")
    if storage_url.startswith("http://") or storage_url.startswith("https://"):
        return True
    if not storage_url.startswith("/static/"):
        return bool(storage_url)
    return (STATIC_ROOT / storage_url.removeprefix("/static/")).exists()


def safe_filename(filename: str | None, fallback: str = "source.mp4") -> str:
    name = (filename or fallback).split("/")[-1].split("\\")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def google_drive_direct_url(url: str) -> str:
    match = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        # CalledProcessError's message only carries the argv; surface the
        # actual tool output so remote failures are diagnosable from logs.
        # Keep the head too: Remotion prints the actual error message before
        # several repeated stack traces, so a tail-only excerpt loses it.
        output = (exc.stderr or exc.stdout or "").strip() or "no output"
        excerpt = output if len(output) <= 4000 else f"{output[:2000]}\n[... truncated ...]\n{output[-2000:]}"
        log.error(
            "Command failed (%s, exit %s): %s",
            command[0] if command else "?",
            exc.returncode,
            excerpt,
        )
        raise


def remove_background_with_veed_fal(
    *,
    source_url: str,
    output_path: Path,
    fal_key: str,
    poll_seconds: int = 10,
    max_wait_seconds: int = 900,
) -> dict[str, Any]:
    """Remove a person's video background using the VEED/fal provider.

    Wraps the actual provider exchange so every attempt lands in the logs with
    success/failure and duration, regardless of which internal path returned.
    """
    with external_call("veed-fal", "background_removal", model=FAL_VEED_MODEL) as call:
        result = _remove_background_with_veed_fal_impl(
            source_url=source_url,
            output_path=output_path,
            fal_key=fal_key,
            poll_seconds=poll_seconds,
            max_wait_seconds=max_wait_seconds,
        )
        result.setdefault("elapsed_seconds", call.elapsed_seconds)
        call.note(request_id=result.get("request_id"))
        if not result.get("ok"):
            call.fail(result.get("error") or "unknown error")
    return result


def _remove_background_with_veed_fal_impl(
    *,
    source_url: str,
    output_path: Path,
    fal_key: str,
    poll_seconds: int = 10,
    max_wait_seconds: int = 900,
) -> dict[str, Any]:
    if not fal_key:
        return {"ok": False, "provider": "veed-fal", "error": "FAL_KEY is missing."}
    if not source_url:
        return {"ok": False, "provider": "veed-fal", "error": "A public source URL is required for fal/VEED."}

    normalized_url = google_drive_direct_url(source_url)
    headers = {"Authorization": f"Key {fal_key}"}
    submit_url = f"https://queue.fal.run/{FAL_VEED_MODEL}"
    payload = {
        "video_url": normalized_url,
        "output_codec": "vp9",
        "refine_foreground_edges": True,
        "subject_is_person": True,
    }
    try:
        submit = requests.post(submit_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        submit.raise_for_status()
        request_id = str(submit.json().get("request_id") or "")
        if not request_id:
            return {"ok": False, "provider": "veed-fal", "error": "fal did not return a request_id."}

        status_url = f"{submit_url}/requests/{request_id}/status"
        response_url = f"{submit_url}/requests/{request_id}"
        started = time.monotonic()
        last_status: dict[str, Any] = {}
        while time.monotonic() - started <= max_wait_seconds:
            status_response = requests.get(status_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            status_response.raise_for_status()
            last_status = status_response.json()
            status = str(last_status.get("status") or "").upper()
            if status in {"COMPLETED", "DONE"}:
                break
            if status in {"FAILED", "ERROR", "CANCELED", "CANCELLED"}:
                return {
                    "ok": False,
                    "provider": "veed-fal",
                    "request_id": request_id,
                    "error": f"fal/VEED failed with status {status}.",
                    "raw_status": last_status,
                }
            time.sleep(max(0, poll_seconds))
        else:
            return {
                "ok": False,
                "provider": "veed-fal",
                "request_id": request_id,
                "error": "fal/VEED background removal timed out.",
                "raw_status": last_status,
            }

        result_response = requests.get(response_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        result_response.raise_for_status()
        result = result_response.json()
        videos = result.get("video") or []
        output_url = ""
        if isinstance(videos, list) and videos:
            output_url = str((videos[0] or {}).get("url") or "")
        if not output_url:
            output_urls = result.get("output_urls")
            if isinstance(output_urls, list) and output_urls:
                output_url = str(output_urls[0])
        if not output_url:
            return {
                "ok": False,
                "provider": "veed-fal",
                "request_id": request_id,
                "error": "fal/VEED completed but did not return a video URL.",
                "raw_result": result,
            }

        media_response = requests.get(output_url, timeout=max(REQUEST_TIMEOUT_SECONDS, 180))
        media_response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(media_response.content)
        if output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            return {"ok": False, "provider": "veed-fal", "request_id": request_id, "error": "Downloaded transparent video was empty."}
        return {
            "ok": True,
            "provider": "veed-fal",
            "request_id": request_id,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "output_url": output_url,
            "output_path": str(output_path),
        }
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        return {"ok": False, "provider": "veed-fal", "error": str(exc)}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ffmpeg_filter_available(name: str) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    try:
        result = run_command(["ffmpeg", "-hide_banner", "-filters"])
    except Exception:
        return False
    return any(f" {name} " in line or line.rstrip().endswith(f" {name}") for line in result.stdout.splitlines())


def ffprobe_has_audio(path: Path) -> bool:
    try:
        result = run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def probe_duration_seconds(path: Path) -> float:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return max(0.1, float(result.stdout.strip()))


def probe_video_dimensions(path: Path) -> tuple[int, int]:
    try:
        result = run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(path),
            ]
        )
        raw = (result.stdout.strip().splitlines() or ["0x0"])[0]
        width, height = (raw.split("x") + ["0", "0"])[:2]
        return int(width or 0), int(height or 0)
    except Exception:
        return 0, 0


def drive_confirm_download_url(html: str) -> str | None:
    """Build the confirmed download URL from Drive's virus-scan interstitial."""
    action = re.search(r'action="(https://drive\.usercontent\.google\.com/download[^"]*)"', html)
    if not action:
        return None
    base = action.group(1).replace("&amp;", "&")
    params = re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html)
    if not params:
        return base
    from urllib.parse import urlencode

    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode(dict(params))}"


def green_border_fraction(image_path: Path) -> float:
    """Fraction of the frame's top/side border pixels that read as chroma green."""
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            pixels = rgb.load()
            samples = 0
            green = 0
            xs = range(0, width, max(1, width // 60))
            for x in xs:
                for y in (2, height // 8, height // 4):
                    r, g, b = pixels[x, min(y, height - 1)][:3]
                    samples += 1
                    if g > 90 and g > r * 1.25 and g > b * 1.25:
                        green += 1
            for y in range(0, height // 2, max(1, height // 40)):
                for x in (2, width - 3):
                    r, g, b = pixels[x, y][:3]
                    samples += 1
                    if g > 90 and g > r * 1.25 and g > b * 1.25:
                        green += 1
            return green / samples if samples else 0.0
    except Exception:
        log.exception("Green-screen probe failed for %s", image_path)
        return 0.0


def detect_green_screen(source_path: Path) -> bool:
    """True when the source looks like studio green screen (border mostly green).

    Green sources get the FREE local chromakey instead of the paid VEED
    provider — VEED bills per frame and adds nothing over chroma keying here.
    """
    probe_frame = source_path.parent / f"{source_path.stem}-green-probe.png"
    try:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "1",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-2",
                str(probe_frame),
            ]
        )
        return green_border_fraction(probe_frame) >= 0.35
    except Exception:
        return False
    finally:
        probe_frame.unlink(missing_ok=True)


def probe_video_codec(path: Path) -> str:
    try:
        result = run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )
        return (result.stdout.strip().splitlines() or [""])[0].strip()
    except Exception:
        return ""


async def download_source(source_url: str, destination: Path) -> tuple[Path | None, str | None]:
    is_drive = "drive.google.com" in (source_url or "") or "drive.usercontent.google.com" in (source_url or "")
    provider = "google-drive" if is_drive else "remote-url"
    async with external_call(provider, "download_source_video") as call:
        path, warning = await _download_source_impl(source_url, destination)
        if path is not None:
            call.note(size_bytes=path.stat().st_size if path.exists() else None)
        if warning:
            call.fail(warning)
    return path, warning


async def _download_source_impl(source_url: str, destination: Path) -> tuple[Path | None, str | None]:
    if not source_url:
        return None, "No source URL was provided."

    url = google_drive_direct_url(source_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            for attempt in range(2):
                total = 0
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = (response.headers.get("content-type") or "").lower()
                    if "text/html" in content_type:
                        is_drive = "drive.google.com" in url or "drive.usercontent.google.com" in url
                        if is_drive and attempt == 0:
                            # Large Drive files return a virus-scan interstitial
                            # page; extract its confirm form and retry once.
                            html = (await response.aread()).decode("utf-8", errors="ignore")
                            confirm_url = drive_confirm_download_url(html)
                            if confirm_url:
                                url = confirm_url
                                continue
                        if is_drive:
                            return None, "Google Drive did not return the video file. Share a direct-download link or upload the file."
                        return None, "The URL returned a web page instead of a video file."

                    with destination.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_REMOTE_BYTES:
                                handle.close()
                                destination.unlink(missing_ok=True)
                                return None, "The remote video is larger than the 500 MB V1 limit."
                            handle.write(chunk)
                    break
    except Exception as exc:
        destination.unlink(missing_ok=True)
        return None, f"Could not download the source video: {exc}"

    if total == 0:
        destination.unlink(missing_ok=True)
        return None, "The remote video download was empty."
    return destination, None


def title_from_suite(suite: Suite) -> str:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    name = str(brand.get("name") or suite.name or "OneShare")
    return name[:80]


def write_text_file(path: Path, text: str) -> Path:
    path.write_text(text.strip() or "OneShare", encoding="utf-8")
    return path


BACKGROUNDS_MODES = {"blend", "user_only"}


def resolve_backgrounds_mode(input_data: dict[str, Any]) -> str:
    """Job option: blend user uploads with generated backgrounds (default) or user-only."""
    mode = str(input_data.get("backgrounds_mode") or "").strip().lower()
    return mode if mode in BACKGROUNDS_MODES else "blend"


# The Arabic result warning shown when a job asked for user_only backgrounds
# but selected zero backgrounds for it — the render falls back to generated.
USER_ONLY_WITHOUT_SELECTION_WARNING = (
    "اخترت وضع خلفياتي فقط بدون اختيار خلفيات — استُخدمت الخلفيات المولّدة"
)


def selected_background_asset_ids(input_data: dict[str, Any], *, max_items: int = 20) -> list[str]:
    """The job's explicitly selected user-background asset ids (possibly [])."""
    raw = input_data.get("background_asset_ids")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw[:max_items]:
        value = str(item or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def resolve_scene_background_video(
    picked: CreativeAsset | None,
    *,
    scene_index: int,
    locked_videos: list[CreativeAsset],
    max_distinct: int = MAX_DISTINCT_BACKGROUND_VIDEOS,
) -> CreativeAsset | None:
    """Cap distinct background videos per render without going static.

    Every distinct background video adds an OffthreadVideo decoder to the
    compositor; renders were OOM-killed at the 8GB container limit. Once
    ``max_distinct`` videos are locked for this render, later scenes ROTATE
    among the locked ones instead of being demoted to a static image — a
    scene only goes static when there are genuinely no usable videos at all.

    Mutates ``locked_videos``: a newly picked video below the cap is appended.
    """
    if len(locked_videos) >= max_distinct:
        return locked_videos[scene_index % len(locked_videos)]
    if picked is None:
        if locked_videos:
            return locked_videos[scene_index % len(locked_videos)]
        return None
    if all(asset.id != picked.id for asset in locked_videos):
        locked_videos.append(picked)
    return picked


def requested_options(input_data: dict[str, Any]) -> set[str]:
    options = input_data.get("options")
    if not isinstance(options, list):
        return set()
    return {str(option) for option in options}


def brand_primary_color(suite: Suite) -> tuple[int, int, int]:
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    colors = brand.get("colors") if isinstance(brand.get("colors"), dict) else {}
    value = str(colors.get("primary") or "#2f80ff").strip()
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value)
    if not match:
        return (47, 128, 255)
    raw = match.group(1)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def stage_tone(input_data: dict[str, Any]) -> str:
    """Magic stage tone: "light" only when the job explicitly asks for it."""
    value = str((input_data or {}).get("stage_tone") or "").strip().lower()
    return "light" if value == "light" else "dark"


def brand_background_color(suite: Suite) -> str:
    """The brand's light canvas color (used by the light Magic stage)."""
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    colors = brand.get("colors") if isinstance(brand.get("colors"), dict) else {}
    value = str(colors.get("background") or "").strip()
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else "#faf8f4"


def font_path() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "fonts" / "NotoSansArabic-Regular.ttf",
        Path(__file__).resolve().parent.parent / "engine" / "assets" / "fonts" / "Cairo-ExtraBold.ttf",
        Path(__file__).resolve().parent.parent / "engine" / "assets" / "fonts" / "Cairo-Black.ttf",
        Path(__file__).resolve().parent.parent / "engine" / "assets" / "fonts" / "Cairo-Bold.ttf",
        Path(__file__).resolve().parent.parent / "fonts" / "Cairo-Regular.ttf",
        Path(__file__).resolve().parent.parent / "engine" / "assets" / "fonts" / "Cairo-Regular.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    return next((path for path in candidates if path.exists()), None)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = font_path()
    if path:
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def rtl_display(text: str) -> str:
    clean = re.sub(r"[\u2066-\u2069\u200e\u200f]", "", str(text or "")).strip()
    if not clean:
        return ""
    return get_display(reshape(clean))


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def wrap_rtl_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = re.split(r"\s+", text.strip())
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and text_width(draw, rtl_display(candidate), font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:4]


def render_rtl_overlay_image(
    *,
    text: str,
    path: Path,
    width: int,
    height: int,
    font_size: int,
    fill: tuple[int, int, int, int] = (255, 255, 255, 245),
    box_fill: tuple[int, int, int, int] | None = (7, 12, 24, 170),
    shadow_fill: tuple[int, int, int, int] = (0, 0, 0, 210),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = load_font(font_size)
    margin = 34
    lines = wrap_rtl_text(draw, text, font, width - (margin * 2))
    if not lines:
        lines = ["OneShare"]
    line_height = int(font_size * 1.35)
    total_height = (len(lines) * line_height) + margin
    y = max(16, (height - total_height) // 2)
    if box_fill:
        draw.rounded_rectangle((14, 10, width - 14, height - 10), radius=28, fill=box_fill)
    for line in lines:
        display = rtl_display(line)
        line_w = text_width(draw, display, font)
        x = (width - line_w) / 2
        draw.text((x + 4, y + 4), display, font=font, fill=shadow_fill)
        draw.text((x, y), display, font=font, fill=fill)
        y += line_height
    image.save(path)
    return path


def create_montage_background(path: Path, suite: Suite) -> Path:
    primary = brand_primary_color(suite)
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (8, 15, 31))
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        for x in range(width):
            radial = 1 - min(1, math.hypot((x - width * 0.5) / width, (y - height * 0.38) / height) * 1.45)
            glow = max(0, radial) * 0.42
            r = int(8 + primary[0] * glow + 8 * ratio)
            g = int(15 + primary[1] * glow + 12 * (1 - ratio))
            b = int(31 + primary[2] * glow + 22 * (1 - ratio))
            pixels[x, y] = (min(255, r), min(255, g), min(255, b))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((72, 112, 1008, 1808), radius=54, outline=(*primary, 130), width=5)
    draw.ellipse((760, 90, 1200, 530), fill=(*primary, 28))
    image.save(path)
    return path


def foreground_filter_chain(*, include_despill: bool) -> str:
    filters = [
        "format=rgba",
        "chromakey=0x00b050:0.18:0.03",
    ]
    if include_despill:
        filters.append("despill=green")
    filters.extend(
        [
            "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos",
            "setsar=1",
        ]
    )
    return ",".join(filters)


def create_local_transparent_subject(
    *,
    source_path: Path,
    output_path: Path,
    duration: float,
) -> dict[str, Any]:
    """Create a transparent VP9 subject video from a local green-screen source.

    Logged like the provider path so background-removal attempts are always
    visible with success/failure and processing time.
    """
    started = time.monotonic()
    result = _create_local_transparent_subject_impl(
        source_path=source_path,
        output_path=output_path,
        duration=duration,
    )
    elapsed = round(time.monotonic() - started, 2)
    result.setdefault("elapsed_seconds", elapsed)
    log_event(
        log,
        logging.INFO if result.get("ok") else logging.ERROR,
        "Local chromakey background removal finished." if result.get("ok") else "Local chromakey background removal failed.",
        event="montage_background_removal",
        provider="local-chromakey",
        ok=bool(result.get("ok")),
        duration_seconds=elapsed,
        error=(str(result.get("error"))[:500] if result.get("error") else None),
    )
    return result


def _create_local_transparent_subject_impl(
    *,
    source_path: Path,
    output_path: Path,
    duration: float,
) -> dict[str, Any]:
    if not ffmpeg_available():
        return {"ok": False, "provider": "local-chromakey", "error": "FFmpeg/FFprobe are not installed."}
    if not ffmpeg_filter_available("chromakey"):
        return {"ok": False, "provider": "local-chromakey", "error": "FFmpeg chromakey filter is unavailable."}
    if not source_path.exists():
        return {"ok": False, "provider": "local-chromakey", "error": "Source file was not found."}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_filter = foreground_filter_chain(include_despill=ffmpeg_filter_available("despill")) + ",format=yuva420p"
    command = [
        "ffmpeg",
        "-y",
        "-t",
        str(max(0.1, duration)),
        "-i",
        str(source_path),
        "-filter_complex",
        f"[0:v]{video_filter}[fg]",
        "-map",
        "[fg]",
        "-map",
        "0:a?",
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-auto-alt-ref",
        "0",
        "-b:v",
        "0",
        "-crf",
        "28",
        "-c:a",
        "libopus",
        str(output_path),
    ]
    try:
        run_command(command)
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        return {
            "ok": False,
            "provider": "local-chromakey",
            "error": (exc.stderr or exc.stdout or str(exc))[-1200:],
        }

    if not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return {"ok": False, "provider": "local-chromakey", "error": "Transparent local subject video was empty."}

    return {
        "ok": True,
        "provider": "local-chromakey",
        "output_path": str(output_path),
        "duration_seconds": round(duration, 3),
    }


def detect_silences(path: Path) -> list[tuple[float, float]]:
    if not ffprobe_has_audio(path):
        return []
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                "silencedetect=noise=-35dB:d=0.45",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    output = f"{result.stderr}\n{result.stdout}"
    starts = [float(item) for item in re.findall(r"silence_start:\s*([0-9.]+)", output)]
    ends = [float(item) for item in re.findall(r"silence_end:\s*([0-9.]+)", output)]
    return list(zip(starts, ends))


def non_silent_segments(path: Path, duration: float) -> list[tuple[float, float]]:
    silences = detect_silences(path)
    if not silences:
        return [(0.0, duration)]
    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in silences:
        if start - cursor > 0.35:
            segments.append((max(0.0, cursor - 0.08), min(duration, start + 0.08)))
        cursor = max(cursor, end)
    if duration - cursor > 0.35:
        segments.append((max(0.0, cursor - 0.08), duration))
    return segments[:28] or [(0.0, duration)]


def dead_air_join_times(segments: list[tuple[float, float]]) -> list[float]:
    """Cumulative tightened-timeline offsets at each internal segment join.

    After concatenating the retained non-silent segments, the k-th internal
    boundary sits at the sum of the first k segment durations. The final
    segment's end is the clip end, not a join, so it is excluded.
    """
    if len(segments) <= 1:
        return []
    joins: list[float] = []
    cursor = 0.0
    for start, end in segments[:-1]:
        cursor += max(0.0, end - start)
        joins.append(round(cursor, 3))
    return joins


def extract_audio_for_transcription(video_path: Path, audio_path: Path) -> Path | None:
    if not ffprobe_has_audio(video_path):
        return None
    try:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                # Whisper expects mono 16 kHz. Handing it stereo 44.1 kHz makes
                # it hallucinate/collapse the whole track to a single canned
                # phrase (e.g. "اشتركوا في القناة") on some sources; downmixing
                # to mono 16 kHz transcribes the real speech reliably.
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(audio_path),
            ]
        )
    except subprocess.CalledProcessError:
        return None
    return audio_path if audio_path.exists() else None


def transcribe_video_segments(video_path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not settings.openai_api_key:
        return [], "OPENAI_API_KEY is missing; captions use notes fallback."
    audio_path = extract_audio_for_transcription(video_path, output_dir / "transcription.m4a")
    if not audio_path:
        return [], "No audio stream was available for transcription."
    try:
        with audio_path.open("rb") as audio_file:
            data = [
                ("model", "whisper-1"),
                ("response_format", "verbose_json"),
                ("timestamp_granularities[]", "segment"),
                ("timestamp_granularities[]", "word"),
                ("prompt", "The video is likely spoken in Arabic or Hebrew. Preserve the spoken language."),
            ]
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": (audio_path.name, audio_file, "audio/mp4")},
                data=data,
                timeout=180,
            )
        if response.status_code >= 400:
            return [], f"OpenAI transcription failed: {response.status_code}"
        data = response.json()
    except Exception as exc:
        return [], f"OpenAI transcription failed: {exc}"
    segments: list[dict[str, Any]] = []
    for segment in data.get("segments") or []:
        text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        start = segment.get("start")
        end = segment.get("end")
        if text and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            segments.append({"start": float(start), "end": float(end), "text": text})
    words: list[dict[str, Any]] = []
    for word in data.get("words") or []:
        text = str(word.get("word") or "").strip()
        start = word.get("start")
        end = word.get("end")
        if text and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            words.append({"text": text, "start": float(start), "end": float(end)})
    for segment in segments:
        segment["words"] = [
            w for w in words if segment["start"] - 0.05 <= w["start"] < segment["end"]
        ]
    transcript_path = output_dir / "transcript.json"
    transcript_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    return segments[:64], None


def pad_subject_frames(frames_dir: Path, min_count: int) -> int:
    """Hold the final subject frame so indices up to ``min_count`` all exist.

    ffmpeg's ``fps=`` filter can emit one or two fewer frames than the Remotion
    composition requests at the tail (it maps scene ends with ``round(t*fps)``).
    A single missing ``frame_%05d.png`` 404s the compositor and collapses the
    whole render to the basic ``ffmpeg_local_fallback`` engine, so we duplicate
    the last real frame to cover the rounding gap. Returns the number added.
    """
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        return 0
    last = frames[-1]
    try:
        last_index = int(last.stem.split("_")[-1])
    except ValueError:
        return 0
    padded = 0
    for index in range(last_index + 1, min_count):
        target = frames_dir / f"frame_{index:05d}.png"
        if not target.exists():
            shutil.copy2(last, target)
            padded += 1
    return padded


def detect_subject_top_rel(frames_dir: Path) -> float | None:
    """Top edge of the transparent subject (0..1 of frame height) from alpha."""
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        return None
    sample = frames[min(len(frames) - 1, len(frames) // 4)]
    try:
        with Image.open(sample) as img:
            alpha = img.convert("RGBA").getchannel("A")
            width, height = alpha.size
            pixels = alpha.load()
            for y in range(0, height, 3):
                for x in range(0, width, 6):
                    if pixels[x, y] > 24:
                        return round(y / height, 4)
    except Exception:
        log.exception("Failed to detect subject top from %s", sample)
    return None


def detect_subject_head_width_rel(frames_dir: Path) -> float | None:
    """Widest alpha extent in the head band (0..1 of frame width).

    Used to cap the subject zoom so the head never exceeds ~90% of the frame
    width. Measures the head band just below the detected subject top — the
    face/hair is the widest thing there and drives the safe max zoom.
    """
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        return None
    sample = frames[min(len(frames) - 1, len(frames) // 4)]
    try:
        with Image.open(sample) as img:
            alpha = img.convert("RGBA").getchannel("A")
            width, height = alpha.size
            pixels = alpha.load()
            # Find the subject top row first.
            top_y = None
            for y in range(0, height, 3):
                if any(pixels[x, y] > 24 for x in range(0, width, 6)):
                    top_y = y
                    break
            if top_y is None:
                return None
            # Scan the head band (top ~13% of the frame below the crown) for the
            # widest run of opaque pixels.
            band_end = min(height, top_y + int(height * 0.13))
            widest = 0
            for y in range(top_y, band_end, 3):
                xs = [x for x in range(0, width, 4) if pixels[x, y] > 24]
                if xs:
                    widest = max(widest, xs[-1] - xs[0])
            if widest <= 0:
                return None
            return round(widest / width, 4)
    except Exception:
        log.exception("Failed to detect subject head width from %s", sample)
    return None


def build_caption_chunks(
    caption: str,
    scene_start: float,
    scene_end: float,
    segment_words: list[dict[str, Any]] | None,
    chunk_size: int = 4,
) -> list[dict[str, Any]]:
    """Split a scene caption into 3-4 word chunks timed to the spoken words.

    Times are relative to the scene start. Falls back to an even distribution
    when no word-level timestamps are available (overrides, notes fallback).
    """
    scene_duration = max(0.4, scene_end - scene_start)
    timed_words: list[dict[str, Any]] = []
    for word in segment_words or []:
        text = str(word.get("text") or "").strip()
        start = word.get("start")
        if not text or not isinstance(start, (int, float)):
            continue
        rel = min(max(0.0, float(start) - scene_start), scene_duration)
        timed_words.append({"text": text, "start": round(rel, 3)})
    if not timed_words:
        plain = [w for w in re.sub(r"\s+", " ", str(caption or "")).strip().split(" ") if w]
        if not plain:
            return []
        per_word = scene_duration / len(plain)
        timed_words = [{"text": w, "start": round(i * per_word, 3)} for i, w in enumerate(plain)]
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(timed_words), chunk_size):
        group = timed_words[i:i + chunk_size]
        next_start = timed_words[i + chunk_size]["start"] if i + chunk_size < len(timed_words) else scene_duration
        chunks.append(
            {
                "start": 0.0 if i == 0 else group[0]["start"],
                "end": round(max(group[0]["start"] + 0.35, next_start), 3),
                "words": group,
            }
        )
    return chunks


def title_from_caption(text: str, fallback: str) -> str:
    stopwords = {"و", "في", "من", "على", "عن", "مع", "كل", "هيك", "اللي", "رح", "هذا", "هاي"}
    words = [
        re.sub(r"^[^\w\u0600-\u06FF]+|[^\w\u0600-\u06FF]+$", "", word)
        for word in str(text or "").split()
    ]
    words = [word for word in words if word and word not in stopwords]
    return " ".join(words[:2]) or fallback


def fallback_caption_segments(duration: float, caption_text: str) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"[.؟!،]\s*", caption_text) if chunk.strip()]
    if not chunks:
        chunks = [caption_text or "مونتاج أولي جاهز للمراجعة"]
    segment_len = max(1.5, duration / max(1, len(chunks)))
    segments = []
    for index, chunk in enumerate(chunks[:8]):
        start = round(index * segment_len, 3)
        end = round(min(duration, start + segment_len + 0.15), 3)
        segments.append({"start": start, "end": end, "text": chunk})
    return segments


def split_text_into_caption_chunks(text: str, count: int) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        clean = "مونتاج تسويقي جاهز"
    sentences = [chunk.strip() for chunk in re.split(r"[.؟!،]\s*", clean) if chunk.strip()]
    if len(sentences) >= count:
        return sentences[:count]
    words = clean.split()
    if len(words) >= count * 3:
        chunk_size = max(3, math.ceil(len(words) / count))
        chunks = [" ".join(words[index : index + chunk_size]).strip() for index in range(0, len(words), chunk_size)]
    else:
        chunks = sentences or [clean]
    while len(chunks) < count:
        chunks.append(chunks[len(chunks) % max(1, len(chunks))])
    return chunks[:count]


def normalize_scene_segments(
    *,
    duration: float,
    transcript_segments: list[dict[str, Any]],
    fallback_text: str,
    timing_segments: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    valid_segments = [
        {
            "start": max(0.0, float(segment.get("start") or 0)),
            "end": min(duration, float(segment.get("end") or duration)),
            "text": re.sub(r"\s+", " ", str(segment.get("text") or fallback_text)).strip(),
        }
        for segment in transcript_segments
        if float(segment.get("end") or 0) > float(segment.get("start") or 0)
    ]
    if len(valid_segments) >= 2:
        return valid_segments[:MAX_MONTAGE_SCENES]

    base_timings = [
        (max(0.0, start), min(duration, end))
        for start, end in (timing_segments or [])
        if end - start >= 0.45
    ]
    if len(base_timings) < 2:
        target_count = max(2, min(8, math.ceil(duration / 4.2)))
        segment_len = duration / target_count
        base_timings = [
            (round(index * segment_len, 3), round(min(duration, (index + 1) * segment_len), 3))
            for index in range(target_count)
        ]

    text_seed = valid_segments[0]["text"] if valid_segments else fallback_text
    chunks = split_text_into_caption_chunks(text_seed, len(base_timings))
    return [
        {"start": round(start, 3), "end": round(end, 3), "text": chunks[index]}
        for index, (start, end) in enumerate(base_timings[:MAX_MONTAGE_SCENES])
        if end > start
    ]


def beat_scene_segments(
    shot_list_beats: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    *,
    duration: float,
) -> list[dict[str, Any]]:
    """Scene units from LLM shot-list beats.

    Each beat becomes one scene segment; the transcript's word-level
    timestamps are re-attached by time window so karaoke captions keep their
    real timing. Returns [] when the beats cannot form at least two scenes
    (the caller then falls back to sentence scenes).
    """
    words = [
        word
        for segment in transcript_segments
        for word in (segment.get("words") or [])
        if isinstance(word, dict) and isinstance(word.get("start"), (int, float))
    ]
    segments: list[dict[str, Any]] = []
    for beat in shot_list_beats or []:
        if not isinstance(beat, dict):
            continue
        try:
            start = max(0.0, float(beat.get("start")))
            end = min(duration, float(beat.get("end")))
        except (TypeError, ValueError):
            continue
        text = re.sub(r"\s+", " ", str(beat.get("text") or "")).strip()
        visual_prompt = re.sub(r"\s+", " ", str(beat.get("visual_prompt") or "")).strip()
        if end - start < 0.2 or not text or not visual_prompt:
            continue
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "words": [word for word in words if start - 0.05 <= float(word["start"]) < end],
                "beat": beat,
            }
        )
    return segments if len(segments) >= 2 else []


def resolve_magic_scene_video(
    picked: CreativeAsset | None,
    *,
    locked_videos: list[CreativeAsset],
    max_distinct: int,
) -> CreativeAsset | None:
    """Magic never repeats a background video across frames.

    The default template's rotation backfill ("no scene goes static") is
    exactly the repetition Magic exists to kill: it silently filled every
    video-directed frame with the same hero clip, so the per-frame image
    generation never fired. A Magic frame either locks a NEW distinct video
    (below the decoder cap) or returns None so the caller mints the frame's
    own generated image instead. Mutates ``locked_videos``.
    """
    if picked is None:
        return None
    if any(asset.id == picked.id for asset in locked_videos):
        return None
    if len(locked_videos) >= max_distinct:
        return None
    locked_videos.append(picked)
    return picked


def split_long_beat_segments(
    segments: list[dict[str, Any]],
    *,
    max_seconds: float = MAGIC_MAX_BEAT_SECONDS,
) -> list[dict[str, Any]]:
    """Magic safety net: mechanically split any beat segment still longer
    than ``max_seconds`` into even micro-frames.

    The micro-beat shot list should already cut this fine; this guarantees it
    when the LLM returns lazy long beats. Word timestamps are re-windowed so
    karaoke captions keep real timing and each piece's text is its own words.
    Only the first piece keeps the staged camera/sfx/icons — repeating a
    zoom or a sound on every sub-frame would spam the cut.
    """
    result: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        seconds = end - start
        if seconds <= max_seconds:
            result.append(segment)
            continue
        pieces = int(math.ceil(seconds / max_seconds))
        piece_seconds = seconds / pieces
        words = [word for word in (segment.get("words") or []) if isinstance(word, dict)]
        beat = segment.get("beat") if isinstance(segment.get("beat"), dict) else None
        for piece_index in range(pieces):
            piece_start = start + piece_index * piece_seconds
            piece_end = end if piece_index == pieces - 1 else piece_start + piece_seconds
            piece_words = [
                word for word in words if piece_start - 0.05 <= float(word.get("start") or 0) < piece_end
            ]
            piece_text = " ".join(str(word.get("text") or word.get("word") or "").strip() for word in piece_words).strip()
            piece_beat = beat
            if beat is not None and piece_index > 0:
                magic = beat.get("magic") if isinstance(beat.get("magic"), dict) else None
                piece_beat = dict(beat)
                if magic:
                    piece_beat["magic"] = {**magic, "camera": "none", "sfx": None, "icons": []}
            piece = dict(segment)
            piece["start"] = round(piece_start, 3)
            piece["end"] = round(piece_end, 3)
            piece["words"] = piece_words
            piece["text"] = piece_text or str(segment.get("text") or "")
            if piece_beat is not None:
                piece["beat"] = piece_beat
            result.append(piece)
    return result


def _scene_is_high_energy(scene: dict[str, Any]) -> bool:
    beat_type = str(scene.get("beatType") or "").lower()
    duration = float(scene.get("sourceEnd") or 0) - float(scene.get("sourceStart") or 0)
    return beat_type == "enumeration" or duration < 1.5


def pick_scene_transition(
    from_scene: dict[str, Any],
    to_scene: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Choose a geometric transition for one scene boundary by energy.

    High-energy boundaries (fast enumeration beats or a short incoming scene)
    get flip/zoom; a closing cta gets zoom for emphasis; calm narrative
    boundaries get fade/slide. Within a tier the seed parity alternates the two
    choices so the same transition never repeats back-to-back.
    """
    incoming_beat = str(to_scene.get("beatType") or "").lower()
    parity = seed % 2
    if incoming_beat == "cta":
        transition_type = "zoom"
    elif _scene_is_high_energy(to_scene) or _scene_is_high_energy(from_scene):
        transition_type = ("flip", "zoom")[parity]
    else:
        transition_type = ("fade", "slide")[parity]
    direction = "from-left" if parity == 0 else "from-right"
    return {
        "type": transition_type,
        "durationInFrames": TRANSITION_FRAMES,
        "direction": direction if transition_type == "slide" else None,
    }


def split_scenes_at_joins(
    scenes: list[dict[str, Any]],
    joins: list[float],
    fps: int,
) -> list[dict[str, Any]]:
    """Split any scene that strictly contains a dead-air join into two scenes.

    Sub-scenes inherit every non-timing field (palette, caption, beatType,
    background) from the parent; only sourceStart/sourceEnd change and
    captionChunks are recomputed for each half's time window. Joins that land
    on an existing scene boundary (within one frame) are ignored. Ids are
    re-sequenced scene-01.. after all splits.
    """
    if not joins:
        return scenes
    epsilon = 1.0 / max(1, fps)
    result: list[dict[str, Any]] = []
    for scene in scenes:
        start = float(scene["sourceStart"])
        end = float(scene["sourceEnd"])
        inner = sorted(t for t in joins if start + epsilon < t < end - epsilon)
        if not inner:
            result.append(scene)
            continue
        cut_points = [start, *inner, end]
        for lo, hi in zip(cut_points, cut_points[1:]):
            piece = dict(scene)
            piece["sourceStart"] = round(lo, 3)
            piece["sourceEnd"] = round(hi, 3)
            piece["captionChunks"] = build_caption_chunks(
                scene.get("caption") or "", lo, hi, None
            )
            result.append(piece)
    for index, scene in enumerate(result):
        scene["id"] = f"scene-{index + 1:02d}"
    return result


MAGIC_TRANSITION_FRAMES = 9


def build_scene_transitions(
    scenes: list[dict[str, Any]], seed: int, *, magic: bool = False
) -> list[dict[str, Any]]:
    """One transition per interior boundary, chosen by energy (seeded).

    OneShare Magic overrides the geometric grammar: every cut is a smooth
    cross-dissolve ("mix") so the end of one clip melts into the start of the
    next instead of flipping/sliding.
    """
    if magic:
        return [
            {"type": "fade", "durationInFrames": MAGIC_TRANSITION_FRAMES, "direction": None}
            for _ in range(len(scenes) - 1)
        ]
    return [
        pick_scene_transition(scenes[i], scenes[i + 1], seed=seed + i)
        for i in range(len(scenes) - 1)
    ]


def enforce_short_beat_video_rule(
    visual_video_asset: CreativeAsset | None,
    *,
    scene_seconds: float,
    is_beat_scene: bool,
    locked_videos: list[CreativeAsset],
) -> CreativeAsset | None:
    """Short shot-list beats (<2s) never introduce a NEW distinct video.

    Every distinct background video costs an OffthreadVideo decoder; rapid
    enumeration beats would blow the decoder cap in seconds. A short beat may
    still reuse an already-locked video (resolve_scene_background_video then
    rotates it in) but never locks a fresh one.
    """
    if not is_beat_scene or scene_seconds >= 2.0 or visual_video_asset is None:
        return visual_video_asset
    if any(asset.id == visual_video_asset.id for asset in locked_videos):
        return visual_video_asset
    return None


_AR_NOISE_RE = re.compile(r"[ً-ْٰـ]")


def _normalize_title_token(token: str) -> str:
    """Normalize an Arabic/Latin token for spoken-word matching."""
    text = _AR_NOISE_RE.sub("", str(token or ""))
    text = re.sub(r"[^\w؀-ۿ]+", "", text, flags=re.UNICODE)
    return (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ة", "ه")
        .replace("ى", "ي")
        .lower()
    )


def _tokens_match(spoken: str, wanted: str) -> bool:
    if not spoken or not wanted:
        return False
    if spoken == wanted:
        return True
    # Stem-ish prefix match ("قرر" ↔ "قررت", "تستمر" ↔ "تستمري").
    if min(len(spoken), len(wanted)) >= 2 and (
        spoken.startswith(wanted) or wanted.startswith(spoken)
    ):
        return True
    return False


def _title_spoken_at(title: str, caption_chunks: Any) -> float | None:
    """Scene-relative second the title's lead word is actually spoken."""
    tokens = [_normalize_title_token(part) for part in str(title or "").split()]
    tokens = [token for token in tokens if token][:2]
    if not tokens:
        return None
    for chunk in caption_chunks if isinstance(caption_chunks, list) else []:
        for word in (chunk.get("words") or []) if isinstance(chunk, dict) else []:
            spoken = _normalize_title_token(word.get("text"))
            if any(_tokens_match(spoken, token) for token in tokens):
                try:
                    return float(word.get("start") or 0.0)
                except (TypeError, ValueError):
                    return 0.0
    return None


def align_magic_titles(scenes: list[dict[str, Any]]) -> dict[str, int]:
    """Sync every Magic title to the moment its word is actually spoken.

    The director titles a BEAT, but the render pops the title at scene start —
    so a title whose word lands late (or in the neighbouring scene after beat
    splitting) appears seconds before it is spoken. This pass stamps
    magic["titleAt"] (scene-relative seconds) from the caption word
    timestamps, migrates a title to the adjacent scene that actually speaks
    it, and drops adjacent duplicate titles left by scene splitting.
    """
    stats = {"aligned": 0, "moved": 0, "deduped": 0}
    for index, scene in enumerate(scenes):
        magic = scene.get("magic")
        if not isinstance(magic, dict):
            continue
        magic.setdefault("titleAt", 0.0)
        title = str(magic.get("title") or "").strip()
        if not title:
            continue
        previous = scenes[index - 1].get("magic") if index > 0 else None
        if isinstance(previous, dict) and str(previous.get("title") or "").strip() == title:
            # Scene splitting duplicated the beat's title — keep the first only.
            magic["title"] = ""
            magic["titleAt"] = 0.0
            stats["deduped"] += 1
            continue
        spoken_at = _title_spoken_at(title, scene.get("captionChunks"))
        if spoken_at is not None:
            scene_duration = max(
                0.1, float(scene.get("sourceEnd") or 0) - float(scene.get("sourceStart") or 0)
            )
            next_magic = (
                scenes[index + 1].get("magic") if index + 1 < len(scenes) else None
            )
            if (
                spoken_at > scene_duration - 0.6
                and isinstance(next_magic, dict)
                and not str(next_magic.get("title") or "").strip()
            ):
                # The word lands in the scene's dying frames — the title would
                # blink for a beat and vanish. Hand it to the next scene, which
                # continues the same spoken phrase.
                next_magic["title"] = title
                next_magic["titleAt"] = 0.0
                magic["title"] = ""
                magic["titleAt"] = 0.0
                stats["moved"] += 1
                continue
            # Guarantee ≥0.9s on screen even when the word lands late.
            magic["titleAt"] = round(
                min(max(0.0, spoken_at - 0.12), max(0.0, scene_duration - 0.9)), 3
            )
            stats["aligned"] += 1
            continue
        migrated = False
        for neighbour_index in (index + 1, index - 1):
            if not 0 <= neighbour_index < len(scenes):
                continue
            neighbour = scenes[neighbour_index]
            neighbour_magic = neighbour.get("magic")
            if not isinstance(neighbour_magic, dict):
                continue
            if str(neighbour_magic.get("title") or "").strip():
                continue
            neighbour_at = _title_spoken_at(title, neighbour.get("captionChunks"))
            if neighbour_at is None:
                continue
            neighbour_magic["title"] = title
            neighbour_magic["titleAt"] = round(max(0.0, neighbour_at - 0.12), 3)
            magic["title"] = ""
            magic["titleAt"] = 0.0
            stats["moved"] += 1
            migrated = True
            break
        if not migrated:
            # Conceptual title (e.g. the brand name never literally spoken):
            # keep it at the scene start — legacy behaviour.
            magic["titleAt"] = 0.0
    return stats


def text_override_at(input_data: dict[str, Any], key: str, index: int) -> str | None:
    values = input_data.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    value = re.sub(r"\s+", " ", str(values[index] or "")).strip()
    return value or None


def remotion_work_dir(output_path: Path) -> Path:
    path = output_path.parent / "remotion-work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def remotion_public_asset(path: Path) -> str:
    public_root = path.parents[2] / "public"
    try:
        return f"/{path.relative_to(public_root).as_posix()}"
    except ValueError:
        return f"/remotion/inputs/{path.name}"


def copy_remotion_runtime(work_dir: Path) -> tuple[Path, Path]:
    src_dir = work_dir / "src" / "remotion"
    public_dir = work_dir / "public" / "remotion"
    src_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("AiMontage.tsx", "Root.tsx", "index.ts"):
        shutil.copy2(WEB_ROOT / "src" / "remotion" / filename, src_dir / filename)

    # Copy every module AiMontage imports via relative paths (resolved next to
    # AiMontage.tsx): transition presentations, and the per-template scene
    # components. Copy whatever directories exist rather than naming them — a
    # hardcoded list silently drops a new template's directory, the bundler then
    # fails to resolve its import, and the whole Remotion render falls back to
    # the bare ffmpeg montage. That is how the Classic/Minimal templates shipped
    # broken: they were added without being added here.
    remotion_root = WEB_ROOT / "src" / "remotion"
    for source_module in sorted(p for p in remotion_root.iterdir() if p.is_dir()):
        target_module = src_dir / source_module.name
        target_module.mkdir(parents=True, exist_ok=True)
        for tsx in source_module.iterdir():
            if tsx.is_file():
                shutil.copy2(tsx, target_module / tsx.name)

    # The Remotion bundler resolves bare imports (e.g. `@remotion/transitions`)
    # by walking up from the entry file's dir for a node_modules. This isolated
    # work dir has none, so link web/node_modules in — otherwise
    # `@remotion/transitions` fails to resolve and the WHOLE Remotion render
    # errors out, silently falling back to the bare ffmpeg montage (no captions,
    # titles, backgrounds, or transitions). `remotion` core alone resolved before
    # because the bundler injects it itself; a separate package like
    # @remotion/transitions must be reachable on disk from the entry.
    node_modules_link = work_dir / "node_modules"
    if not node_modules_link.exists():
        try:
            node_modules_link.symlink_to(WEB_ROOT / "node_modules", target_is_directory=True)
        except (OSError, NotImplementedError):
            log.warning(
                "Could not link node_modules into montage work dir %s; "
                "@remotion/transitions may not resolve and the render will fall back.",
                work_dir,
            )

    source_fonts = WEB_ROOT / "public" / "remotion" / "fonts"
    target_fonts = public_dir / "fonts"
    target_fonts.mkdir(parents=True, exist_ok=True)
    if source_fonts.exists():
        for font_file in source_fonts.iterdir():
            if font_file.is_file():
                shutil.copy2(font_file, target_fonts / font_file.name)
    fallback_fonts = Path(__file__).resolve().parent.parent / "engine" / "assets" / "fonts"
    if fallback_fonts.exists():
        for name in ("Cairo-Regular.ttf", "Cairo-Bold.ttf", "Cairo-Black.ttf"):
            source = fallback_fonts / name
            target = target_fonts / name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)
    return src_dir, public_dir


def write_mono_pcm_wav(path: Path, samples: list[float], sample_rate: int = 48000) -> None:
    peak = max(0.001, max(abs(sample) for sample in samples))
    rms = math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
    target_rms = 10 ** (-16 / 20)
    gain = min(0.92 / peak, target_rms / max(0.001, rms))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for sample in samples:
            value = int(max(-0.92, min(0.92, sample * gain)) * 32767)
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        handle.writeframes(bytes(frames))


def generate_marketing_music_bed(path: Path, duration: float) -> None:
    """Create a present but light local music bed without external services."""

    sample_rate = 48000
    total = max(sample_rate, int(duration * sample_rate))
    audio = [0.0] * total
    rng = random.Random(7)
    bpm = 124
    beat = 60 / bpm

    def add_signal(start: float, length: float, fn: Callable[[float], float], gain: float) -> None:
        start_index = max(0, int(start * sample_rate))
        length_samples = max(1, int(length * sample_rate))
        end_index = min(total, start_index + length_samples)
        if end_index <= start_index:
            return
        attack = max(1, int(0.012 * sample_rate))
        release = max(1, int(0.09 * sample_rate))
        for index in range(start_index, end_index):
            local = index - start_index
            t = local / sample_rate
            env = 1.0
            if local < attack:
                env *= local / attack
            tail = end_index - index
            if tail < release:
                env *= tail / release
            audio[index] += fn(t) * gain * env

    def tone(freq: float, harmonic: float = 0.25) -> Callable[[float], float]:
        return lambda t: math.sin(2 * math.pi * freq * t) + harmonic * math.sin(2 * math.pi * freq * 2 * t)

    chords = [(55, 82.41, 110), (49, 73.42, 98), (43.65, 65.41, 87.31), (46.25, 69.3, 92.5)]
    bars = int(math.ceil(duration / (beat * 4)))
    for bar in range(bars):
        start = bar * beat * 4
        chord = chords[bar % len(chords)]
        for step in range(4):
            step_start = start + step * beat
            bass = chord[0] if step != 3 else chord[0] * 1.5
            add_signal(step_start, beat * 0.86, tone(bass, 0.18), 0.22)
            for freq in chord[1:]:
                add_signal(step_start, beat * 0.58, tone(freq, 0.08), 0.045)
        for step in (0, 2, 3.5):
            def kick(t: float) -> float:
                freq = 120 * math.exp(-8 * t) + 42
                return math.sin(2 * math.pi * freq * t) * math.exp(-8.5 * t)

            add_signal(start + step * beat, 0.34, kick, 0.82)
        for step in (1, 3):
            def snare(t: float) -> float:
                return (rng.uniform(-1, 1) * 0.72 + math.sin(2 * math.pi * 190 * t) * 0.25) * math.exp(-15 * t)

            add_signal(start + step * beat, 0.22, snare, 0.26)
        for step in range(8):
            def hat(t: float) -> float:
                return rng.uniform(-1, 1) * math.exp(-42 * t)

            add_signal(start + step * beat / 2, 0.075, hat, 0.055 if step % 2 else 0.082)

    fade_in = min(total, int(0.45 * sample_rate))
    fade_out = min(total, int(1.0 * sample_rate))
    for index in range(fade_in):
        audio[index] *= index / max(1, fade_in)
    for index in range(fade_out):
        audio[total - 1 - index] *= index / max(1, fade_out)
    write_mono_pcm_wav(path, audio, sample_rate)


def generate_soft_whoosh(path: Path) -> None:
    sample_rate = 48000
    duration = 0.48
    total = int(duration * sample_rate)
    rng = random.Random(11)
    previous = 0.0
    samples: list[float] = []
    for index in range(total):
        t = index / sample_rate
        progress = t / duration
        noise = rng.uniform(-1, 1)
        high = noise - previous
        previous = noise
        sweep = math.sin(2 * math.pi * (320 + 2900 * progress) * t)
        env = math.sin(math.pi * progress) ** 1.8
        samples.append((high * 0.55 + sweep * 0.35) * env)
    write_mono_pcm_wav(path, samples, sample_rate)


# Tags that read as a scene-cut accent rather than a mid-scene ping. Boundaries
# prefer these; a camera-shutter or notification at a hard cut feels off.
TRANSITION_SFX_TAGS = {"transition", "whoosh", "swoosh", "impact", "pop", "energy", "hit"}


def transition_sound_pool(sfx_assets: list) -> list:
    """Scene-boundary accents drawn from the sfx library.

    There is no dedicated audio ``transition`` asset kind in the library (only
    visual ``transition_video``), so boundary sounds come from ``sfx``. Prefer
    transition-flavoured sfx, but fall back to the whole library when fewer than
    two are tagged that way — anything beats replaying one whoosh forever.
    """
    flavoured = [
        asset
        for asset in sfx_assets
        if TRANSITION_SFX_TAGS & {str(tag).lower() for tag in (getattr(asset, "tags", None) or [])}
    ]
    return flavoured if len(flavoured) >= 2 else list(sfx_assets)


def varied_index_sequence(count: int, length: int, seed: int) -> list[int]:
    """A seed-shuffled walk over ``range(length)`` repeated to ``count`` items.

    Consecutive picks differ (within a cycle) and the whole order changes with
    the render seed, so boundary sounds vary both within a video and between
    renders. Returns ``[]`` for degenerate inputs.
    """
    if count <= 0 or length <= 0:
        return []
    order = list(range(length))
    random.Random(seed).shuffle(order)
    return [order[position % length] for position in range(count)]


async def build_remotion_scene_manifest(
    *,
    db: AsyncSession | None,
    transparent_source_path: Path,
    work_dir: Path,
    suite: Suite,
    input_data: dict[str, Any],
    duration: float,
    transcript_segments: list[dict[str, Any]],
    fps: int = 30,
    subject_has_alpha: bool = True,
    shot_list_beats: list[dict[str, Any]] | None = None,
    dead_air_joins: list[float] | None = None,
    magic_direction_source: str | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    src_dir, public_dir = copy_remotion_runtime(work_dir)
    inputs_dir = public_dir / "inputs"
    backgrounds_dir = public_dir / "backgrounds"
    sound_dir = public_dir / "sound"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    backgrounds_dir.mkdir(parents=True, exist_ok=True)
    sound_dir.mkdir(parents=True, exist_ok=True)

    options = requested_options(input_data)
    template = montage_template(input_data)
    is_magic = template in MAGIC_TEMPLATES
    # Honest options: a toggle the user switched off must leave zero trace in
    # the manifest, so the render cannot silently apply it anyway.
    show_captions = "captions" in options
    show_titles = "titles" in options
    music_enabled = "music" in options
    voice_cleanup = "voice_cleanup" in options

    source_copy = inputs_dir / transparent_source_path.name
    if transparent_source_path.resolve() != source_copy.resolve():
        shutil.copy2(transparent_source_path, source_copy)

    frames_dir = inputs_dir / f"{transparent_source_path.stem}-frames"
    if subject_has_alpha:
        # Transparent VP9 subjects are pre-split into RGBA frames; opaque
        # full-frame sources play directly through OffthreadVideo instead.
        frames_dir.mkdir(parents=True, exist_ok=True)
        if not any(frames_dir.glob("frame_*.png")):
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-c:v",
                    "libvpx-vp9",
                    "-i",
                    str(transparent_source_path),
                    "-vf",
                    f"fps={fps},scale=1080:1920:flags=lanczos",
                    "-start_number",
                    "0",
                    str(frames_dir / "frame_%05d.png"),
                ]
            )
        # The composition runs to ceil(duration*fps) frames; ffmpeg's fps filter
        # can land a couple short, AND cross-dissolve transitions make the tail
        # sequence request a few source frames past the scene end. Pad generously
        # (hold the last frame) so a single 404 never collapses the render to the
        # ffmpeg fallback. The manifest also ships subjectFrameCount so the
        # compositor clamps the index as a belt-and-suspenders guard.
        pad_subject_frames(frames_dir, int(math.ceil(duration * fps)) + 12)

    has_source_audio = ffprobe_has_audio(transparent_source_path)
    audio_path = inputs_dir / f"{transparent_source_path.stem}-audio.m4a"
    if not audio_path.exists() and has_source_audio:
        audio_command = ["ffmpeg", "-y", "-i", str(transparent_source_path), "-vn"]
        if voice_cleanup:
            audio_command.extend(["-af", VOICE_CLEANUP_AUDIO_FILTER])
        audio_command.extend(["-c:a", "aac", "-b:a", "192k", str(audio_path)])
        run_command(audio_command)
    if not audio_path.exists():
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration:.3f}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(audio_path),
            ]
        )

    notes = str(input_data.get("notes") or "").strip()
    if not transcript_segments:
        transcript_segments = fallback_caption_segments(duration, notes or "مونتاج تسويقي جاهز")
    timing_segments = non_silent_segments(transparent_source_path, duration) if "dead_spaces" in options else None
    # LLM shot-list beats (when available) replace sentence granularity as the
    # scene units; any failure keeps exactly the previous behaviour.
    scene_source = "sentence_segments"
    if shot_list_beats:
        beat_segments = beat_scene_segments(shot_list_beats, transcript_segments, duration=duration)
        if beat_segments and is_magic:
            # Magic works in micro-frames: any beat the LLM left long is
            # mechanically split so no frame exceeds ~MAGIC_MAX_BEAT_SECONDS.
            beat_segments = split_long_beat_segments(beat_segments)
        if beat_segments:
            transcript_segments = beat_segments
            scene_source = "shot_list_beats"
        else:
            log.warning("Shot-list beats could not form scene segments; falling back to sentence scenes.")
    if scene_source != "shot_list_beats":
        transcript_segments = normalize_scene_segments(
            duration=duration,
            transcript_segments=transcript_segments,
            fallback_text=notes or title_from_suite(suite),
            timing_segments=timing_segments,
        )

    wanted_kinds: set[str] = set(VIDEO_TRANSITION_KINDS)
    if subject_has_alpha:
        # Background layers are invisible behind an opaque full-frame subject.
        wanted_kinds |= VISUAL_KINDS
    if music_enabled:
        wanted_kinds |= AUDIO_KINDS
    active_assets = await list_active_assets(db, kinds=wanted_kinds) if db else []
    if active_assets:
        available_assets = [asset for asset in active_assets if creative_asset_file_available(asset)]
        skipped_assets = [asset for asset in active_assets if asset not in available_assets]
        if skipped_assets:
            log.warning(
                "Skipped %s missing local creative assets while building Remotion manifest: %s",
                len(skipped_assets),
                ", ".join(f"{asset.kind}:{asset.id}" for asset in skipped_assets[:50]),
            )
        active_assets = available_assets
    backgrounds_mode = resolve_backgrounds_mode(input_data)
    background_asset_ids = selected_background_asset_ids(input_data)
    active_assets, allow_generated_backgrounds = filter_assets_for_backgrounds_mode(
        active_assets,
        mode=backgrounds_mode,
        suite_id=suite.id,
        selected_ids=background_asset_ids,
    )
    if not allow_generated_backgrounds:
        log_event(
            log,
            logging.INFO,
            "Montage backgrounds restricted to the job's selected user uploads (user_only mode).",
            event="montage_backgrounds_mode",
            suite_id=suite.id,
            backgrounds_mode=backgrounds_mode,
            selected_background_ids=background_asset_ids,
            user_asset_count=len([asset for asset in active_assets if asset.kind in VISUAL_KINDS]),
        )
    selected_asset_ids: list[str] = []
    # OneShare Magic bottom stage: ONE clean, uncluttered brand image behind
    # the speaker and the bottom captions, constant across the whole video
    # (the reference keeps a single designed stage under every scene). The
    # TOP zone carries the per-frame video/animation.
    magic_stage_public_path: str | None = None
    if is_magic and subject_has_alpha and db and allow_generated_backgrounds:
        try:
            stage_asset = await generate_visual_asset_for_scene(
                db,
                suite=suite,
                scene_text=f"{suite.name} brand stage backdrop",
                kind="visual_image",
                visual_prompt=(
                    (
                        "a flat seamless empty studio backdrop: one smooth bright "
                        "airy wall in a very light pastel tint of the brand color, "
                        "soft warm daylight, cream white floor, high-key bright "
                        "lighting, nothing dark anywhere — absolutely minimal, no "
                        "furniture, no room, no objects, no decorations, just the "
                        "clean bright wall"
                    )
                    if stage_tone(input_data) == "light"
                    else (
                        "a flat seamless empty studio backdrop: one smooth solid wall "
                        "in the brand color with a soft vertical gradient and a dark "
                        "reflective floor line — absolutely minimal, no furniture, no "
                        "room, no objects, no decorations, just the clean wall"
                    )
                ),
            )
            if stage_asset:
                stage_path = remotion_public_asset_path(stage_asset.storage_url, work_dir, stage_asset.id)
                if stage_path:
                    magic_stage_public_path = stage_path
                    selected_asset_ids.append(stage_asset.id)
        except Exception:
            log.exception("Magic stage image generation failed; falling back to the gradient stage.")
    locked_background_videos: list[CreativeAsset] = []
    generated_image_count = 0
    max_generated_images = max(0, int(settings.montage_max_generated_images_per_render))
    scenes: list[dict[str, Any]] = []
    # Never drop the tail of long videos: segments beyond the scene cap are
    # merged into the last scene instead of being cut from the montage.
    scene_cap = MAGIC_MAX_MONTAGE_SCENES if is_magic else MAX_MONTAGE_SCENES
    capped_segments = list(transcript_segments)
    if len(capped_segments) > scene_cap:
        tail = capped_segments[scene_cap - 1 :]
        merged = dict(tail[0])
        merged["end"] = tail[-1].get("end", merged.get("end"))
        merged["text"] = " ".join(str(seg.get("text") or "").strip() for seg in tail).strip()
        merged["words"] = [word for seg in tail for word in (seg.get("words") or [])]
        capped_segments = capped_segments[: scene_cap - 1] + [merged]
    if is_magic:
        # Magic stages EVERY frame with its own visual ("منتج كل فريم"): the
        # image budget scales with the frame count. Per-frame generated
        # IMAGES are the safe way to cover micro-beats (each distinct
        # background VIDEO costs an OffthreadVideo decoder).
        max_generated_images = max(max_generated_images, min(32, len(capped_segments)))
    for index, segment in enumerate(capped_segments):
        beat = segment.get("beat") if isinstance(segment.get("beat"), dict) else None
        # OneShare Magic: every scene carries its own staging. Beats the
        # director staged keep their LLM direction; sentence scenes (or a
        # failed director) get the heuristic grammar so Magic never renders
        # as a plain default montage.
        magic: dict[str, Any] | None = None
        if is_magic:
            candidate = beat.get("magic") if beat else None
            magic = (
                candidate
                if isinstance(candidate, dict)
                else heuristic_magic_direction(index=index, beat=beat, scene_count=len(capped_segments))
            )
        # Solid scenes let the 3D typography carry the frame: no background
        # media is picked or generated for them; image scenes skip video.
        magic_background = str(magic.get("background")) if magic else None
        allow_scene_video = magic_background in (None, "video")
        allow_scene_image = magic_background != "solid"
        segment_seconds = max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0))
        start = max(0.0, float(segment.get("start") or 0) - 0.12)
        end = min(duration, float(segment.get("end") or duration) + 0.12)
        if end <= start:
            end = min(duration, start + 1.5)
        generated_caption = re.sub(r"\s+", " ", str(segment.get("text") or notes or title_from_suite(suite))).strip()
        caption = text_override_at(input_data, "caption_overrides", index) or generated_caption
        generated_title = title_from_caption(caption, title_from_suite(suite))
        if beat and str(beat.get("keyword") or "").strip():
            generated_title = str(beat.get("keyword")).strip()
        behind_text = text_override_at(input_data, "title_overrides", index) or generated_title
        # Background picking scores against the beat's literal visual prompt +
        # spoken words; sentence scenes keep scoring against the caption.
        scene_match_text = f"{beat['visual_prompt']} {beat['text']}" if beat else caption
        palette = [
            ["#07111f", "#2f80ed", "#e8f3ff"],
            ["#15120f", "#e6aa3b", "#fff2cf"],
            ["#102018", "#28c76f", "#e6fff1"],
            ["#201225", "#d85cff", "#ffe9ff"],
            ["#1c1d21", "#ff5f45", "#fff0ec"],
        ][index % 5]
        variety_seed = zlib.crc32(str(work_dir).encode("utf-8")) + index
        # Short beats never mint a fresh Veo video: the clip could not even
        # register before the cut, and each distinct video costs a decoder.
        # Exception: the Magic hero frame — its top-zone video IS the hook.
        beat_allows_new_video = not (beat and segment_seconds < 2.0) or (is_magic and index == 0)
        visual_video_asset = None
        if (
            subject_has_alpha
            and allow_scene_video
            and db
            and index == 0
            and allow_generated_backgrounds
            and beat_allows_new_video
            # In blend mode a matching user upload wins the hero scene;
            # generation only fills gaps the user's own media doesn't cover.
            and not has_user_background_match(active_assets, scene_text=scene_match_text, suite_id=suite.id)
        ):
            # The hero scene always gets a freshly generated background tied to
            # the spoken line, so consecutive renders don't open identically.
            try:
                visual_video_asset = await generate_visual_asset_for_scene(
                    db,
                    suite=suite,
                    scene_text=scene_match_text,
                    kind="visual_video",
                    visual_prompt=(beat.get("visual_prompt") if beat else None),
                    # Magic top-zone video: expressive, brand-aware, 16:9,
                    # people/logos allowed (the default template stays literal).
                    magic_top_zone=is_magic,
                )
                if visual_video_asset:
                    active_assets.append(visual_video_asset)
            except Exception:
                visual_video_asset = None
        if subject_has_alpha and allow_scene_video and not visual_video_asset:
            visual_video_asset = pick_asset(
                active_assets,
                kind="visual_video",
                scene_text=scene_match_text,
                suite_id=suite.id,
                variety_seed=variety_seed,
                user_match_required=allow_generated_backgrounds,
            )
        if (
            subject_has_alpha
            and allow_scene_video
            and not visual_video_asset
            and db
            and index < 2
            and allow_generated_backgrounds
            and beat_allows_new_video
        ):
            try:
                visual_video_asset = await generate_visual_asset_for_scene(
                    db,
                    suite=suite,
                    scene_text=scene_match_text,
                    kind="visual_video",
                    visual_prompt=(beat.get("visual_prompt") if beat else None),
                    # Magic top-zone video: expressive, brand-aware, 16:9,
                    # people/logos allowed (the default template stays literal).
                    magic_top_zone=is_magic,
                )
                if visual_video_asset:
                    active_assets.append(visual_video_asset)
            except Exception:
                visual_video_asset = None
        # Cap distinct background-video decoders; past the cap, scenes rotate
        # among the locked videos instead of dropping to a static image.
        if subject_has_alpha and allow_scene_video:
            # The Magic hero keeps its freshly minted video even under 2s —
            # stripping it here discarded a paid Veo clip before it ever aired.
            if not (is_magic and index == 0):
                visual_video_asset = enforce_short_beat_video_rule(
                    visual_video_asset,
                    scene_seconds=segment_seconds,
                    is_beat_scene=bool(beat),
                    locked_videos=locked_background_videos,
                )
            if is_magic:
                # No rotation backfill: a repeated video frame becomes a
                # freshly generated image frame instead.
                visual_video_asset = resolve_magic_scene_video(
                    visual_video_asset,
                    locked_videos=locked_background_videos,
                    # Magic leans harder on motion; one extra decoder stays
                    # inside the 8GB container's budget.
                    max_distinct=MAX_DISTINCT_BACKGROUND_VIDEOS + 1,
                )
            else:
                visual_video_asset = resolve_scene_background_video(
                    visual_video_asset,
                    scene_index=index,
                    locked_videos=locked_background_videos,
                    max_distinct=MAX_DISTINCT_BACKGROUND_VIDEOS,
                )
        visual_asset = None
        if subject_has_alpha and allow_scene_image:
            # Magic image frames mint their OWN literal visual FIRST — a
            # library pick would return the same old suite asset for every
            # frame and the whole montage collapses into one look. The pick
            # is only the fallback when generation fails or the budget is out.
            if (
                magic
                # A video frame the decoder cap left dry still deserves its
                # own literal image instead of a recycled library asset.
                and magic_background in ("image", "video")
                and not visual_video_asset
                and db
                and allow_generated_backgrounds
                and generated_image_count < max_generated_images
            ):
                try:
                    visual_asset = await generate_visual_asset_for_scene(
                        db,
                        suite=suite,
                        scene_text=scene_match_text,
                        visual_prompt=(beat.get("visual_prompt") if beat else None),
                    )
                    if visual_asset:
                        generated_image_count += 1
                        active_assets.append(visual_asset)
                except Exception:
                    # Loud, not silent: a whole render of failed generations
                    # otherwise looks identical to "decided not to generate".
                    log.exception("Magic frame %s image generation failed; falling back to library pick.", index + 1)
                    visual_asset = None
            if not visual_asset:
                visual_asset = pick_asset(
                    active_assets,
                    kind="visual_image",
                    scene_text=scene_match_text,
                    suite_id=suite.id,
                    variety_seed=variety_seed,
                    user_match_required=allow_generated_backgrounds,
                )
            # Generation fill: beats that prefer an image get one from their
            # literal visual prompt (cost-capped per render); sentence scenes
            # keep the previous first-4-scenes behaviour.
            should_generate_image = (
                str(beat.get("prefer") or "image") == "image" and generated_image_count < max_generated_images
                if beat
                else index < 4
            ) and not magic
            if not visual_asset and db and allow_generated_backgrounds and should_generate_image:
                try:
                    visual_asset = await generate_visual_asset_for_scene(
                        db,
                        suite=suite,
                        scene_text=scene_match_text,
                        visual_prompt=(beat.get("visual_prompt") if beat else None),
                    )
                    if visual_asset:
                        generated_image_count += 1
                        active_assets.append(visual_asset)
                except Exception:
                    visual_asset = None
        background_path = backgrounds_dir / f"scene-{index + 1:02d}.png"
        # An opaque full-frame subject covers the whole canvas, so scene
        # backgrounds are skipped entirely (no generation, no assets). Magic
        # solid scenes draw their stage in the compositor — no PNG either.
        background_public_path = (
            f"/remotion/backgrounds/{background_path.name}" if subject_has_alpha and allow_scene_image else None
        )
        background_video_public_path = None
        background_asset_id = None
        background_video_asset_id = None
        background_image_asset_id = None
        if visual_video_asset:
            prepared_video_path = remotion_public_asset_path(visual_video_asset.storage_url, work_dir, visual_video_asset.id)
            if prepared_video_path:
                background_video_public_path = prepared_video_path
                background_asset_id = visual_video_asset.id
                background_video_asset_id = visual_video_asset.id
                selected_asset_ids.append(visual_video_asset.id)
        if visual_asset:
            prepared_image_path = remotion_public_asset_path(visual_asset.storage_url, work_dir, visual_asset.id)
            if prepared_image_path:
                background_public_path = prepared_image_path
                background_image_asset_id = visual_asset.id
                background_asset_id = background_asset_id or visual_asset.id
                selected_asset_ids.append(visual_asset.id)
        if subject_has_alpha and allow_scene_image and not background_image_asset_id and not background_path.exists():
            create_montage_background(background_path, suite)
        scenes.append(
            {
                "id": f"scene-{index + 1:02d}",
                "sourceStart": round(start, 3),
                "sourceEnd": round(end, 3),
                "caption": caption,
                "captionChunks": build_caption_chunks(
                    caption,
                    start,
                    end,
                    segment.get("words") if caption == generated_caption else None,
                ),
                "behindText": behind_text,
                "generatedCaption": generated_caption,
                "generatedBehindText": generated_title,
                "beatType": (str(beat.get("beat_type")) if beat else None),
                "beatKeyword": (str(beat.get("keyword") or "") or None) if beat else None,
                "beatPrefer": (str(beat.get("prefer")) if beat else None),
                "backgroundPrompt": (
                    f"Literal visual beat: {beat['visual_prompt']}"
                    if beat
                    else f"Vertical editorial background inspired by this spoken line: {caption}"
                ),
                "palette": palette,
                "backgroundImagePublicPath": background_public_path,
                "backgroundVideoPublicPath": background_video_public_path,
                "backgroundAssetId": background_asset_id,
                "backgroundVideoAssetId": background_video_asset_id,
                "backgroundImageAssetId": background_image_asset_id,
                "backgroundAssetKind": "visual_video" if background_video_public_path else ("visual_image" if background_asset_id else ("generated_static" if subject_has_alpha and allow_scene_image else "none")),
                **({"magic": magic} if magic else {}),
            }
        )

    for index in range(len(scenes) - 1):
        if scenes[index]["sourceEnd"] > scenes[index + 1]["sourceStart"]:
            boundary = round((scenes[index]["sourceEnd"] + scenes[index + 1]["sourceStart"]) / 2, 3)
            scenes[index]["sourceEnd"] = boundary
            scenes[index + 1]["sourceStart"] = boundary

    scenes = split_scenes_at_joins(scenes, dead_air_joins or [], fps)

    if is_magic:
        title_sync = align_magic_titles(scenes)
        # One glance answers "did every frame get its own background?".
        log_event(
            log,
            logging.INFO,
            "Magic frame backgrounds resolved.",
            event="montage_magic_backgrounds",
            suite_id=suite.id,
            frames=len(scenes),
            generated_images=generated_image_count,
            distinct_videos=len(locked_background_videos),
            solid_frames=sum(1 for scene in scenes if (scene.get("magic") or {}).get("background") == "solid"),
            stage_image=bool(magic_stage_public_path),
            title_sync=title_sync,
        )

    edited_duration = sum(max(0.1, scene["sourceEnd"] - scene["sourceStart"]) for scene in scenes)
    music_asset = None
    if music_enabled:
        # Notes analysis can bias the library pick with a mood keyword
        # (e.g. "هادئة") that outranks the generic suite/caption text.
        music_mood = re.sub(r"\s+", " ", str(input_data.get("music_mood") or "")).strip()
        music_query = f"{music_mood} {suite.name} {' '.join(scene['caption'] for scene in scenes[:3])}".strip()
        music_asset = pick_asset(active_assets, kind="music", scene_text=music_query)
    # Deterministic per-render shuffle: without it every video walks the same
    # usage-ordered transition sequence and reads as "the same transition".
    render_shuffle_seed = zlib.crc32(str(work_dir).encode("utf-8"))
    sfx_assets = [asset for asset in active_assets if asset.kind == "sfx"] if music_enabled else []
    music_path = sound_dir / "marketing-upbeat-bed.wav"
    whoosh_path = sound_dir / "soft-whoosh.wav"
    if music_enabled:
        try:
            if not music_path.exists():
                generate_marketing_music_bed(music_path, edited_duration + 1)
            if not whoosh_path.exists():
                generate_soft_whoosh(whoosh_path)
        except Exception:
            pass

    starts: list[float] = []
    cursor = 0.0
    for scene in scenes:
        starts.append(cursor)
        cursor += scene["sourceEnd"] - scene["sourceStart"]

    sound_effects: list[dict[str, Any]] = []
    boundary_starts = starts[1:]
    # Boundary accents come from the sfx library (there is no audio "transition"
    # kind), shuffled per render so each scene cut gets a different sound instead
    # of the same whoosh every time.
    transition_pool = transition_sound_pool(sfx_assets) if music_enabled else []
    boundary_indices = varied_index_sequence(len(boundary_starts), len(transition_pool), render_shuffle_seed ^ 0x9E3779B9)
    for index, start in enumerate(boundary_starts):
        # Magic cuts are smooth cross-dissolves ("mix"); the generic boundary
        # whoosh/swoosh just repeats over every cut, so drop it entirely and
        # let the per-scene director sfx + music carry the audio.
        if not music_enabled or is_magic:
            continue
        # A Magic scene that stages its own sound owns its cut — the generic
        # boundary transition sfx would double up on the same instant.
        next_magic = scenes[index + 1].get("magic") if index + 1 < len(scenes) else None
        if isinstance(next_magic, dict) and next_magic.get("sfx") in MAGIC_SFX_QUERIES:
            continue
        asset = transition_pool[boundary_indices[index]] if transition_pool else None
        public_path = remotion_public_asset_path(asset.storage_url, work_dir, asset.id) if asset else None
        if asset and public_path:
            selected_asset_ids.append(asset.id)
            sound_effects.append({"publicPath": public_path, "at": round(start, 3), "volume": 0.3, "assetId": asset.id, "kind": "transition"})
        elif whoosh_path.exists():
            sound_effects.append({"publicPath": "/remotion/sound/soft-whoosh.wav", "at": round(start, 3), "volume": 0.3, "kind": "transition"})

    beat_cursor = 0.0
    for scene_index, scene in enumerate(scenes):
        duration_for_scene = max(0.1, scene["sourceEnd"] - scene["sourceStart"])
        # Magic staged sound: the director's per-scene sfx keyword picks a
        # matching library sound at the scene's first frame.
        magic_sfx_key = str((scene.get("magic") or {}).get("sfx") or "")
        if music_enabled and magic_sfx_key in MAGIC_SFX_QUERIES:
            magic_sfx_asset = pick_asset(
                active_assets,
                kind="sfx",
                scene_text=MAGIC_SFX_QUERIES[magic_sfx_key],
                variety_seed=render_shuffle_seed + scene_index,
            )
            magic_sfx_path = (
                remotion_public_asset_path(magic_sfx_asset.storage_url, work_dir, magic_sfx_asset.id)
                if magic_sfx_asset
                else None
            )
            if magic_sfx_asset and magic_sfx_path:
                selected_asset_ids.append(magic_sfx_asset.id)
                sound_effects.append(
                    {
                        "publicPath": magic_sfx_path,
                        "at": round(beat_cursor + 0.04, 3),
                        "volume": 0.34,
                        "assetId": magic_sfx_asset.id,
                        "kind": "magic_sfx",
                    }
                )
        beat_count = max(1, int(duration_for_scene // 2.7))
        for beat_index in range(beat_count):
            if not sfx_assets:
                continue
            # Magic micro-frames already get a boundary sound per cut; the
            # generic in-scene rhythm sfx on sub-second frames is just spam.
            if is_magic and duration_for_scene < 1.2:
                continue
            asset = sfx_assets[(scene_index + beat_index) % len(sfx_assets)]
            public_path = remotion_public_asset_path(asset.storage_url, work_dir, asset.id)
            if public_path:
                selected_asset_ids.append(asset.id)
                sound_effects.append(
                    {
                        "publicPath": public_path,
                        "at": round(beat_cursor + min(duration_for_scene - 0.2, 0.7 + beat_index * 2.8), 3),
                        "volume": 0.2,
                        "assetId": asset.id,
                        "kind": "sfx",
                    }
                )
        scene["attentionBeats"] = [
            {
                "at": round(min(duration_for_scene - 0.2, 0.55 + beat_index * 2.8), 3),
                "type": ["zoom", "flash", "overlay", "parallax"][beat_index % 4],
            }
            for beat_index in range(beat_count)
        ]
        beat_cursor += duration_for_scene

    background_music = (
        {"publicPath": "/remotion/sound/marketing-upbeat-bed.wav", "volume": 0.14}
        if music_enabled and music_path.exists()
        else None
    )
    if music_asset:
        public_path = remotion_public_asset_path(music_asset.storage_url, work_dir, music_asset.id)
        if public_path:
            selected_asset_ids.append(music_asset.id)
            background_music = {"publicPath": public_path, "volume": 0.14, "assetId": music_asset.id}

    serialized_creative_assets = [serialize_creative_asset(asset) for asset in active_assets]

    if db:
        try:
            await record_asset_usage(db, selected_asset_ids)
        except Exception:
            log.exception("Failed to record creative asset usage for video montage job")

    caption_style = str(input_data.get("caption_style") or "").strip().lower()
    caption_scale = {"large": 1.3, "small": 0.85}.get(caption_style, 1.0)
    source_manifest: dict[str, Any] = {
        "publicPath": f"/remotion/inputs/{source_copy.name}",
        "originalPath": str(transparent_source_path),
        "durationSeconds": round(duration, 3),
        "hasAlpha": subject_has_alpha,
    }
    if subject_has_alpha:
        # Opaque sources omit framesPublicPath on purpose: the component then
        # falls back to a full-frame OffthreadVideo of the source itself.
        source_manifest.update(
            {
                "framesPublicPath": f"/remotion/inputs/{frames_dir.name}",
                "framePattern": "frame_%05d.png",
                "subjectFrameCount": len(list(frames_dir.glob("frame_*.png"))),
                "subjectTopRel": detect_subject_top_rel(frames_dir),
                "subjectHeadWidthRel": detect_subject_head_width_rel(frames_dir),
            }
        )
    manifest = {
        "fps": fps,
        "width": 1080,
        "height": 1920,
        "template": template,
        "magicStagePublicPath": magic_stage_public_path,
        "showCaptions": show_captions,
        "showTitles": show_titles,
        "source": source_manifest,
        "audio": {
            "sourcePublicPath": f"/remotion/inputs/{audio_path.name}",
            "backgroundMusic": background_music,
            "soundEffects": sound_effects,
        },
        "sceneTransitions": build_scene_transitions(
            scenes, seed=render_shuffle_seed, magic=is_magic or template in CLASSIC_TEMPLATES
        ),
        "creativeAssets": serialized_creative_assets,
        "selectedCreativeAssetIds": sorted(set(selected_asset_ids)),
        "style": {
            "fontFamily": "ConnecAssistant",
            "arabicFontFamily": "ConnecCairo",
            "subjectZoom": max(1.0, min(3.0, float(input_data.get("zoom") or 1.0))),
            "brandColor": "#%02x%02x%02x" % brand_primary_color(suite),
            # Opt-in bright Magic stage: light washes + dark ink typography.
            # Defaults to the classic dark stage for every existing client.
            "stageTone": stage_tone(input_data),
            "stageColor": brand_background_color(suite),
            "subjectOffsetXPct": max(-40.0, min(40.0, float(input_data.get("subject_offset_x") or 0.0))),
            "subjectOffsetYPct": max(-40.0, min(40.0, float(input_data.get("subject_offset_y") or 0.0))),
            "captionScale": caption_scale,
        },
        "scenes": scenes,
        "durationSeconds": round(edited_duration, 3),
        "diagnostics": {
            "sceneCount": len(scenes),
            "sceneSource": scene_source,
            "template": template,
            "magicDirectionSource": (magic_direction_source or "heuristic") if is_magic else None,
            "magicLayouts": (
                {
                    layout: sum(1 for scene in scenes if (scene.get("magic") or {}).get("layout") == layout)
                    for layout in sorted({(scene.get("magic") or {}).get("layout") for scene in scenes if scene.get("magic")})
                }
                if is_magic
                else None
            ),
            "shotListBeatTypes": (
                {
                    beat_type: sum(1 for scene in scenes if scene.get("beatType") == beat_type)
                    for beat_type in sorted({scene.get("beatType") for scene in scenes if scene.get("beatType")})
                }
                if scene_source == "shot_list_beats"
                else None
            ),
            "generatedImageCount": generated_image_count,
            "soundEffectCount": len(sound_effects),
            "musicBed": bool(background_music),
            "musicEnabled": music_enabled,
            "showCaptions": show_captions,
            "showTitles": show_titles,
            "subjectHasAlpha": subject_has_alpha,
            "backgroundsMode": backgrounds_mode,
            "selectedBackgroundAssetIds": background_asset_ids,
            "generatedBackgroundsAllowed": allow_generated_backgrounds,
            "voiceCleanupApplied": bool(voice_cleanup and has_source_audio),
            "timingSource": "non_silent_segments" if timing_segments and len(timing_segments) > 1 else "transcript_or_timed_split",
        },
    }
    manifest_path = src_dir / "manifest.generated.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return manifest_path, scenes


async def render_remotion_montage(
    *,
    db: AsyncSession | None,
    transparent_source_path: Path,
    output_path: Path,
    suite: Suite,
    input_data: dict[str, Any],
    transcript: tuple[list[dict[str, Any]], str | None] | None = None,
    subject_has_alpha: bool = True,
    dead_air_joins: list[float] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    result = await _render_remotion_montage_impl(
        db=db,
        transparent_source_path=transparent_source_path,
        output_path=output_path,
        suite=suite,
        input_data=input_data,
        transcript=transcript,
        subject_has_alpha=subject_has_alpha,
        dead_air_joins=dead_air_joins,
    )
    elapsed = round(time.monotonic() - started, 2)
    result["render_duration_seconds"] = elapsed
    rendered = bool(result.get("rendered"))
    log_event(
        log,
        logging.INFO if rendered else logging.ERROR,
        "Remotion montage render finished." if rendered else "Remotion montage render failed.",
        event="montage_engine_render",
        engine="remotion",
        suite_id=suite.id,
        rendered=rendered,
        duration_seconds=elapsed,
        video_duration_seconds=result.get("duration_seconds"),
        scene_count=result.get("scene_count"),
        reason=(str(result.get("reason"))[:500] if result.get("reason") else None),
    )
    return result


async def _render_remotion_montage_impl(
    *,
    db: AsyncSession | None,
    transparent_source_path: Path,
    output_path: Path,
    suite: Suite,
    input_data: dict[str, Any],
    transcript: tuple[list[dict[str, Any]], str | None] | None = None,
    subject_has_alpha: bool = True,
    dead_air_joins: list[float] | None = None,
) -> dict[str, Any]:
    if not ffmpeg_available():
        return {"rendered": False, "reason": "FFmpeg/FFprobe are not installed in this runtime."}
    if not transparent_source_path.exists():
        return {"rendered": False, "reason": "Subject video was not found."}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = min(probe_duration_seconds(transparent_source_path), float(settings.montage_max_duration_seconds))
    transcript_segments, transcript_warning = (
        transcript
        if transcript is not None
        else await asyncio.to_thread(transcribe_video_segments, transparent_source_path, output_path.parent)
    )
    warnings = [transcript_warning] if transcript_warning else []
    # LLM shot list: the transcript becomes literal visual beats that replace
    # sentence granularity. Any failure logs and keeps the previous behaviour.
    template = montage_template(input_data)
    shot_list_beats = await generate_shot_list(
        transcript_segments,
        suite=suite,
        notes=str(input_data.get("notes") or ""),
        max_beats=MAGIC_MAX_MONTAGE_SCENES if template in MAGIC_TEMPLATES else MAX_MONTAGE_SCENES,
        style=template,
    )
    # OneShare Magic: a second LLM pass stages every beat individually
    # (layout, solid/video background, 3D title, icons, camera, sfx). Scenes
    # without a staged beat get heuristic directions in the manifest loop.
    magic_direction_source: str | None = None
    if template in MAGIC_TEMPLATES and shot_list_beats:
        magic_direction_source = await apply_magic_directions(
            shot_list_beats, suite=suite, notes=str(input_data.get("notes") or "")
        )
    work_dir = remotion_work_dir(output_path)
    manifest_path, scenes = await build_remotion_scene_manifest(
        db=db,
        transparent_source_path=transparent_source_path,
        work_dir=work_dir,
        suite=suite,
        input_data=input_data,
        duration=duration,
        transcript_segments=transcript_segments,
        subject_has_alpha=subject_has_alpha,
        shot_list_beats=shot_list_beats,
        dead_air_joins=dead_air_joins,
        magic_direction_source=magic_direction_source,
    )
    public_dir = work_dir / "public"
    entry = work_dir / "src" / "remotion" / "index.ts"
    try:
        run_command(
            [
                "npm",
                "exec",
                "--prefix",
                str(WEB_ROOT),
                "remotion",
                "--",
                "render",
                str(entry),
                "AiMontage",
                str(output_path),
                "--public-dir",
                str(public_dir),
                # Rendering 4K-sourced scenes with default concurrency exhausts
                # the container's memory (compositor gets SIGKILLed at 8GB).
                "--concurrency",
                str(max(1, settings.remotion_render_concurrency)),
                # Remotion sizes this cache to half the *host* memory by
                # default; on an 8GB-capped container the kernel OOM-kills the
                # compositor once scenes stack several OffthreadVideo layers.
                "--offthreadvideo-cache-size-in-bytes",
                str(max(64, settings.remotion_offthread_cache_mb) * 1024 * 1024),
            ]
        )
    except subprocess.CalledProcessError as exc:
        return {
            "rendered": False,
            "reason": (exc.stderr or exc.stdout or str(exc))[-1200:],
            "manifest_path": str(manifest_path),
            "warnings": warnings,
        }

    # Honest capability reporting: only claim what this render actually did,
    # derived from the manifest the compositor consumed.
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest_data = {}
    manifest_audio = manifest_data.get("audio") or {}
    manifest_diagnostics = manifest_data.get("diagnostics") or {}
    capabilities = ["remotion_layered_render", "mp4_delivery"]
    if subject_has_alpha:
        capabilities.extend(["background_removal", "transparent_subject_frames", "animated_background"])
    else:
        capabilities.append("full_frame_subject")
    if manifest_data.get("showTitles"):
        capabilities.append("behind_person_3d_title")
    if manifest_data.get("showCaptions"):
        capabilities.append("rtl_text_overlay")
    if manifest_data.get("sceneTransitions"):
        capabilities.append("visual_transitions")
    if manifest_audio.get("backgroundMusic"):
        capabilities.append("music_bed")
    if manifest_audio.get("soundEffects"):
        capabilities.append("sound_effect_transitions")
    if manifest_diagnostics.get("voiceCleanupApplied"):
        capabilities.append("audio_cleanup")
    if manifest_diagnostics.get("sceneSource") == "shot_list_beats":
        capabilities.append("llm_shot_list_beats")
    if manifest_data.get("template") in MAGIC_TEMPLATES:
        capabilities.append(f"{manifest_data.get('template')}_template")
        if manifest_diagnostics.get("magicDirectionSource") == "llm":
            capabilities.append("magic_scene_direction")

    return {
        "rendered": output_path.exists(),
        "duration_seconds": duration,
        "output_url": public_static_url(output_path),
        "template": str(manifest_data.get("template") or "default"),
        "capabilities_applied": capabilities,
        "warnings": warnings,
        "manifest_path": str(manifest_path),
        "scene_count": len(scenes),
        "scenes": [
            {
                "id": scene.get("id"),
                "start": scene.get("sourceStart"),
                "end": scene.get("sourceEnd"),
                "caption": scene.get("caption"),
                "behindText": scene.get("behindText"),
                "beatType": scene.get("beatType"),
            }
            for scene in scenes
        ],
    }


def cut_dead_spaces(
    source_path: Path, output_path: Path, duration: float
) -> tuple[Path, bool, str | None, list[float]]:
    if not ffprobe_has_audio(source_path):
        return source_path, False, "No audio stream was found, so silence cutting was skipped.", []
    segments = non_silent_segments(source_path, duration)
    if len(segments) <= 1:
        return source_path, False, None, []
    parts: list[str] = []
    concat_inputs: list[str] = []
    for index, (start, end) in enumerate(segments):
        parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
        concat_inputs.append(f"[v{index}][a{index}]")
    filter_complex = ";".join(parts + [f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[v][a]"])
    try:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                str(output_path),
            ]
        )
    except subprocess.CalledProcessError as exc:
        return source_path, False, (exc.stderr or exc.stdout or str(exc))[-500:], []
    return output_path, True, None, dead_air_join_times(segments)


def finalise_audio(
    *,
    video_path: Path,
    output_path: Path,
    duration: float,
    add_music: bool,
    cleanup_voice: bool,
    sfx_times: list[float] | None = None,
) -> tuple[Path, list[str], list[str]]:
    capabilities: list[str] = []
    warnings: list[str] = []
    if not ffprobe_has_audio(video_path):
        shutil.move(str(video_path), str(output_path))
        return output_path, capabilities, ["No audio stream was found, so audio cleanup and music mix were skipped."]
    if not add_music and not cleanup_voice:
        shutil.move(str(video_path), str(output_path))
        return output_path, capabilities, warnings

    audio_chain = "anull"
    if cleanup_voice:
        audio_chain = VOICE_CLEANUP_AUDIO_FILTER
        capabilities.append("audio_cleanup")

    if add_music:
        music_path = output_path.with_suffix(".music.wav")
        sfx_path = output_path.with_suffix(".sfx.wav")
        fade_out_start = max(0.2, duration - 0.8)
        sfx_times = [time for time in (sfx_times or [0.26]) if 0 <= time < duration]
        if not sfx_times:
            sfx_times = [0.26]
        try:
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=98:duration={duration:.3f}:sample_rate=44100",
                    "-af",
                    f"volume=0.045,afade=t=in:st=0:d=0.6,afade=t=out:st={fade_out_start:.3f}:d=0.7",
                    str(music_path),
                ]
            )
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anoisesrc=color=pink:duration=0.32:sample_rate=44100",
                    "-af",
                    "highpass=f=900,lowpass=f=4200,volume=0.03,afade=t=in:st=0:d=0.03,afade=t=out:st=0.18:d=0.14",
                    str(sfx_path),
                ]
            )
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-i",
                    str(music_path),
                    "-i",
                    str(sfx_path),
                    "-filter_complex",
                    f"[0:a]{audio_chain}[speech];[1:a]volume=0.9[music];"
                    + "".join(
                        f"[2:a]adelay={int(time * 1000)}:all=1,volume={0.20 if index else 0.10}[sfx{index}];"
                        for index, time in enumerate(sfx_times[:14])
                    )
                    + f"[speech][music]{''.join(f'[sfx{index}]' for index in range(min(len(sfx_times), 14)))}"
                    + f"amix=inputs={2 + min(len(sfx_times), 14)}:duration=first:dropout_transition=0[a]",
                    "-map",
                    "0:v",
                    "-map",
                    "[a]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            )
            capabilities.append("music_bed")
            capabilities.append("sound_effect_intro")
            if len(sfx_times) > 1:
                capabilities.append("sound_effect_transitions")
            else:
                capabilities.append("sound_effect_transitions")
            return output_path, capabilities, warnings
        except subprocess.CalledProcessError as exc:
            warnings.append(f"Music mix failed: {(exc.stderr or exc.stdout or str(exc))[-300:]}")

    try:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-af",
                audio_chain,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    except subprocess.CalledProcessError as exc:
        warnings.append(f"Audio cleanup failed: {(exc.stderr or exc.stdout or str(exc))[-300:]}")
        shutil.move(str(video_path), str(output_path))
    return output_path, capabilities, warnings


def render_v1_video(*, source_path: Path, output_path: Path, suite: Suite, input_data: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    result = _render_v1_video_impl(
        source_path=source_path,
        output_path=output_path,
        suite=suite,
        input_data=input_data,
    )
    elapsed = round(time.monotonic() - started, 2)
    result["render_duration_seconds"] = elapsed
    rendered = bool(result.get("rendered"))
    log_event(
        log,
        logging.INFO if rendered else logging.ERROR,
        "V1 FFmpeg montage render finished." if rendered else "V1 FFmpeg montage render failed.",
        event="montage_engine_render",
        engine="ffmpeg_local_fallback",
        suite_id=suite.id,
        rendered=rendered,
        duration_seconds=elapsed,
        video_duration_seconds=result.get("duration_seconds"),
        reason=(str(result.get("reason"))[:500] if result.get("reason") else None),
    )
    return result


def _render_v1_video_impl(*, source_path: Path, output_path: Path, suite: Suite, input_data: dict[str, Any]) -> dict[str, Any]:
    if not ffmpeg_available():
        return {
            "rendered": False,
            "reason": "FFmpeg/FFprobe are not installed in this runtime.",
        }
    if not source_path.exists() or not is_video_file(source_path):
        return {
            "rendered": False,
            "reason": "No supported video source is available for rendering.",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = min(probe_duration_seconds(source_path), float(settings.montage_max_duration_seconds))
    options = requested_options(input_data)
    capabilities = ["video_fit_vertical", "mp4_delivery"]
    warnings: list[str] = []

    working_source = source_path
    timing_segments: list[tuple[float, float]] | None = None
    if "dead_spaces" in options:
        timing_segments = non_silent_segments(source_path, duration)
        working_source, cut_applied, cut_warning, _dead_air_joins = cut_dead_spaces(
            source_path,
            output_path.with_name("cut-source.mp4"),
            duration,
        )
        if cut_applied:
            capabilities.append("silence_cutting")
            duration = min(probe_duration_seconds(working_source), float(settings.montage_max_duration_seconds))
        if cut_warning:
            warnings.append(cut_warning)

    overlay_inputs: list[tuple[Path, str, float | None, float | None]] = []
    title_text = title_from_suite(suite)
    notes = str(input_data.get("notes") or "").strip()
    caption_text = notes[:180] if notes else "مونتاج أولي جاهز للمراجعة"
    transcript_segments: list[dict[str, Any]] = []
    if "captions" in options:
        transcript_segments, transcript_warning = transcribe_video_segments(working_source, output_path.parent)
        if transcript_warning:
            warnings.append(transcript_warning)
        if transcript_segments:
            capabilities.append("transcribed_captions")
        else:
            transcript_segments = fallback_caption_segments(duration, caption_text)
        transcript_segments = normalize_scene_segments(
            duration=duration,
            transcript_segments=transcript_segments,
            fallback_text=caption_text,
            timing_segments=timing_segments,
        )
    if "titles" in options:
        behind_title = title_from_caption(
            transcript_segments[0]["text"] if transcript_segments else title_text,
            title_text,
        )
        overlay_inputs.append(
            (
                render_rtl_overlay_image(
                    text=behind_title,
                    path=output_path.with_suffix(".behind-title.png"),
                    width=1080,
                    height=280,
                    font_size=96,
                    box_fill=None,
                    fill=(255, 255, 255, 235),
                    shadow_fill=(0, 0, 0, 235),
                ),
                "behind_title",
                0.0,
                min(duration, 2.7),
            )
        )
        capabilities.append("behind_person_title")
    if "captions" in options:
        for index, segment in enumerate(transcript_segments[:12]):
            overlay_inputs.append(
                (
                    render_rtl_overlay_image(
                        text=str(segment["text"])[:160],
                        path=output_path.with_suffix(f".caption-{index}.png"),
                        width=980,
                        height=230,
                        font_size=42,
                        box_fill=(7, 12, 24, 185),
                    ),
                    "caption",
                    float(segment["start"]),
                    float(segment["end"]),
                )
            )
        capabilities.append("rtl_text_overlay")

    visual_output = output_path.with_name("visual-pass.mp4")
    command = ["ffmpeg", "-y", "-t", str(duration)]
    filter_parts: list[str] = []
    overlay_start_index = 1
    if "background" in options and ffmpeg_filter_available("chromakey"):
        bg_path = create_montage_background(output_path.with_suffix(".background.png"), suite)
        command.extend(["-loop", "1", "-i", str(bg_path), "-i", str(working_source)])
        overlay_start_index = 2
        filter_parts.append(
            "[0:v]scale=1220:2169,"
            "zoompan=z='1+0.018*sin(on/24)':"
            "x='iw/2-(iw/zoom/2)+18*sin(on/31)':"
            "y='ih/2-(ih/zoom/2)+22*cos(on/37)':d=1:s=1080x1920:fps=30,"
            "setsar=1[bgbase]"
        )
        filter_parts.append(
            "[bgbase]format=rgba,"
            "drawbox=x=70:y=105:w=940:h=1710:color=white@0.06:t=3[bg]"
        )
        filter_parts.append(
            f"[1:v]{foreground_filter_chain(include_despill=ffmpeg_filter_available('despill'))}[fg]"
        )
        last_label = "bg"
        capabilities.append("green_screen_background_removal")
        capabilities.append("animated_background")
        capabilities.append("person_camera_motion")
    else:
        if "background" in options:
            warnings.append("FFmpeg chromakey filter is unavailable; background removal was skipped.")
        command.extend(["-i", str(working_source)])
        filter_parts.append(
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=#101828,"
            "scale=w='iw*(1+0.018*sin(t*0.75))':h='ih*(1+0.018*sin(t*0.75))':eval=frame,"
            "crop=1080:1920,setsar=1[vbase]"
        )
        last_label = "vbase"
        capabilities.append("person_camera_motion")

    for overlay, _kind, _start, _end in overlay_inputs:
        command.extend(["-i", str(overlay)])

    foreground_applied = False
    for index, (_overlay, kind, start, end) in enumerate(overlay_inputs):
        input_index = overlay_start_index + index
        next_label = f"vov{index}"
        if kind == "caption" and not foreground_applied and "background" in options and ffmpeg_filter_available("chromakey"):
            fg_label = f"fgon{index}"
            filter_parts.append(f"[{last_label}][fg]overlay=(W-w)/2:(H-h)/2:format=auto[{fg_label}]")
            last_label = fg_label
            foreground_applied = True
        y_expr = "150" if kind == "behind_title" else "H-h-122"
        enable = ""
        if start is not None and end is not None:
            enable = f":enable='between(t,{start:.3f},{end:.3f})'"
        filter_parts.append(f"[{last_label}][{input_index}:v]overlay=(W-w)/2:{y_expr}{enable}[{next_label}]")
        last_label = next_label
    if not foreground_applied and "background" in options and ffmpeg_filter_available("chromakey"):
        filter_parts.append(f"[{last_label}][fg]overlay=(W-w)/2:(H-h)/2:format=auto[vfg]")
        last_label = "vfg"

    transition_times = [float(segment["start"]) for segment in transcript_segments[1:8] if float(segment["start"]) > 0.25]
    for index, start in enumerate(transition_times):
        next_label = f"vtr{index}"
        filter_parts.append(
            f"[{last_label}]drawbox="
            f"x='-220+((t-{start:.3f})/0.34)*1520':y=0:w=135:h=ih:"
            "color=white@0.13:t=fill:"
            f"enable='between(t,{start:.3f},{start + 0.34:.3f})'[{next_label}]"
        )
        last_label = next_label
    if transition_times:
        capabilities.append("visual_transitions")

    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{last_label}]",
            "-map",
            f"{1 if 'background' in options and ffmpeg_filter_available('chromakey') else 0}:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(visual_output),
        ]
    )
    try:
        run_command(command)
    except subprocess.CalledProcessError as exc:
        return {
            "rendered": False,
            "reason": (exc.stderr or exc.stdout or str(exc))[-1200:],
        }

    _final_path, audio_caps, audio_warnings = finalise_audio(
        video_path=visual_output,
        output_path=output_path,
        duration=duration,
        add_music="music" in options,
        cleanup_voice="voice_cleanup" in options,
        sfx_times=[float(segment["start"]) for segment in transcript_segments[1:]],
    )
    capabilities.extend(audio_caps)
    warnings.extend(audio_warnings)

    return {
        "rendered": output_path.exists(),
        "duration_seconds": duration,
        "output_url": public_static_url(output_path),
        "capabilities_applied": capabilities,
        "warnings": warnings,
    }


def build_render_package(
    *,
    suite: Suite,
    input_data: dict[str, Any],
    output_dir: Path,
    source_path: Path | None,
    render_result: dict[str, Any],
    source_warning: str | None,
) -> dict[str, Any]:
    options = input_data.get("options")
    if not isinstance(options, list):
        options = []
    engine = str(render_result.get("engine") or "")
    package = {
        "version": "video_montage_remotion_v1" if engine in {"remotion_veed_fal", "remotion_local_chromakey", "remotion_fullframe"} else "video_montage_v1",
        "suite_id": suite.id,
        "mode": input_data.get("mode") or "talking_head",
        "source_url": input_data.get("source_url"),
        "source_file_url": public_static_url(source_path) if source_path and source_path.exists() else None,
        "notes": input_data.get("notes") or "",
        "requested_options": options,
        "render": render_result,
        "source_warning": source_warning,
        "next_engine_steps": [
            "store_outputs_in_cloud_storage",
            "enable_customer_uploaded_files_for_provider_via_r2",
            "add_final_audio_sidechain_mix_for_delivery",
        ],
    }
    manifest_path = output_dir / "render-package.json"
    manifest_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    package["package_url"] = public_static_url(manifest_path)
    return package


async def generate_video_montage_for_suite(
    *,
    db: AsyncSession | None = None,
    suite: Suite,
    job_id: str,
    input_data: dict[str, Any],
    progress: ProgressWriter | None = None,
) -> dict[str, Any]:
    """Run the montage pipeline with one start and one finish log line.

    The finish line always carries rendered yes/no, the engine used, and the
    total wall-clock time so an admin can read render outcomes straight from
    the logs.
    """
    pipeline_started = time.monotonic()
    # Free-text notes win over the toggles: an LLM maps every request in the
    # notes to a supported capability (or reports it as unsupported) before
    # anything renders. Analysis failures never fail the job.
    input_data, notes_analysis = await analyze_and_apply_montage_notes(
        job_id=job_id,
        suite_id=suite.id,
        input_data=input_data,
    )
    log_event(
        log,
        logging.INFO,
        "Video montage render started.",
        event="video_montage_render_started",
        job_id=job_id,
        suite_id=suite.id,
        mode=str(input_data.get("mode") or "talking_head"),
        options=sorted(requested_options(input_data)),
        has_uploaded_file=bool(input_data.get("source_file_path")),
        has_source_url=bool(str(input_data.get("source_url") or "").strip()),
        notes_analyzed=notes_analysis is not None,
    )
    try:
        result = await _generate_video_montage_impl(
            db=db,
            suite=suite,
            job_id=job_id,
            input_data=input_data,
            progress=progress,
        )
        if notes_analysis is not None:
            result["notes_analysis"] = notes_analysis
        if resolve_backgrounds_mode(input_data) == "user_only" and not selected_background_asset_ids(input_data):
            # user_only without an explicit selection: the render already fell
            # back to generated backgrounds, and the result must say so.
            log_event(
                log,
                logging.WARNING,
                "Video montage pipeline fell back.",
                event="video_montage_fallback",
                job_id=job_id,
                suite_id=suite.id,
                reason=USER_ONLY_WITHOUT_SELECTION_WARNING,
            )
            result["backgrounds_warning"] = USER_ONLY_WITHOUT_SELECTION_WARNING
    except Exception as exc:
        log_event(
            log,
            logging.ERROR,
            "Video montage render crashed.",
            event="video_montage_render_finished",
            job_id=job_id,
            suite_id=suite.id,
            rendered=False,
            duration_seconds=round(time.monotonic() - pipeline_started, 2),
            error=str(exc)[:500],
        )
        raise

    total_seconds = round(time.monotonic() - pipeline_started, 2)
    result["total_pipeline_seconds"] = total_seconds
    render = (result.get("video_montage") or {}).get("render") or {}
    background_removal = render.get("background_removal") or {}
    rendered = bool(result.get("rendered"))
    log_event(
        log,
        logging.INFO if rendered else logging.ERROR,
        "Video montage render finished." if rendered else "Video montage render did not produce output.",
        event="video_montage_render_finished",
        job_id=job_id,
        suite_id=suite.id,
        rendered=rendered,
        engine=render.get("engine"),
        duration_seconds=total_seconds,
        render_seconds=render.get("render_duration_seconds"),
        background_removal_seconds=background_removal.get("elapsed_seconds"),
        background_removal_provider=background_removal.get("provider"),
        output_url=result.get("output_url"),
        warning=(str(result.get("source_warning"))[:500] if result.get("source_warning") else None),
    )
    return result


async def _generate_video_montage_impl(
    *,
    db: AsyncSession | None = None,
    suite: Suite,
    job_id: str,
    input_data: dict[str, Any],
    progress: ProgressWriter | None = None,
) -> dict[str, Any]:
    output_dir = job_dir(job_id)

    def emit(stage: str, message: str, percent: int, partial: dict[str, Any] | None = None) -> None:
        if progress:
            progress(
                {
                    "stage": stage,
                    "message": message,
                    "progress": percent,
                    "result": partial or {},
                }
            )

    emit("preparing_source", "Preparing video source.", 15)

    def note_fallback(reason: str) -> str:
        log_event(
            log,
            logging.WARNING,
            "Video montage pipeline fell back.",
            event="video_montage_fallback",
            job_id=job_id,
            suite_id=suite.id,
            reason=reason[:500],
        )
        return reason

    source_warning = None
    source_path = None
    provider_result: dict[str, Any] | None = None
    uploaded_path = input_data.get("source_file_path")

    source_url = str(input_data.get("source_url") or "").strip()
    options = requested_options(input_data)

    def chain_warning(reason: str) -> str:
        """Log a fallback and append it to the running source warning.

        Reassigning `source_warning` outright used to erase the original
        failure (e.g. the download error) from the final result.
        """
        note_fallback(reason)
        return f"{source_warning} {reason}".strip() if source_warning else reason

    if uploaded_path:
        candidate = Path(str(uploaded_path))
        if candidate.exists():
            source_path = candidate
        else:
            source_warning = note_fallback("Uploaded source file was not found on disk.")
    elif source_url:
        source_path, source_warning = await download_source(
            source_url,
            output_dir / "source_from_url.mp4",
        )
        if source_warning:
            note_fallback(source_warning)
    else:
        # A montage job without any source must fail loudly, never complete
        # silently: the warning below survives into the final result.
        source_warning = note_fallback("No source video URL or uploaded file was provided to this job.")

    # Dead-space cutting happens BEFORE background removal so the whole
    # downstream pipeline (VEED, transcription, Remotion render) works on the
    # tightened video. Previously only the V1 fallback ever cut silences.
    dead_space_seconds_cut: float | None = None
    dead_air_joins: list[float] = []
    if source_path and "dead_spaces" in options and ffmpeg_available():
        emit("preparing_source", "Cutting silent gaps from the source.", 22)
        normalized_for_cut = await asyncio.to_thread(normalize_montage_source, source_path, output_dir)
        if normalized_for_cut:
            pre_cut_duration = await asyncio.to_thread(probe_duration_seconds, normalized_for_cut)
            tight_path, cut_applied, cut_warning, dead_air_joins = await asyncio.to_thread(
                cut_dead_spaces,
                normalized_for_cut,
                output_dir / "tight-source.mp4",
                pre_cut_duration,
            )
            if cut_applied:
                tight_duration = await asyncio.to_thread(probe_duration_seconds, tight_path)
                dead_space_seconds_cut = round(max(0.0, pre_cut_duration - tight_duration), 2)
                # Replace the cached normalized source so every downstream
                # normalize_montage_source() call reuses the tightened video.
                normalized_target = output_dir / "normalized-source.mp4"
                shutil.move(str(tight_path), str(normalized_target))
                source_path = normalized_target
                log_event(
                    log,
                    logging.INFO,
                    "Cut dead spaces from montage source.",
                    event="montage_dead_space_cut",
                    job_id=job_id,
                    suite_id=suite.id,
                    seconds_cut=dead_space_seconds_cut,
                    source_seconds=round(pre_cut_duration, 2),
                    tightened_seconds=round(tight_duration, 2),
                )
            elif cut_warning:
                note_fallback(f"Dead-space cutting skipped: {cut_warning}")

    def annotate_render(render_result: dict[str, Any]) -> dict[str, Any]:
        """Attach the pre-render silence cut to the engine's capability report."""
        if dead_space_seconds_cut is not None:
            capabilities = render_result.setdefault("capabilities_applied", [])
            if "silence_cutting" not in capabilities:
                capabilities.append("silence_cutting")
            render_result["dead_space_seconds_cut"] = dead_space_seconds_cut
        return render_result

    veed_source_url = None
    veed_stage_path: Path | None = None
    green_screen_detected = False
    force_ai_removal = str(input_data.get("bg_removal_quality") or "auto").strip().lower() == "ai"
    if (
        settings.montage_smart_bg_routing
        and not force_ai_removal
        and "background" in options
        and source_path
        and ffmpeg_filter_available("chromakey")
    ):
        green_screen_detected = await asyncio.to_thread(detect_green_screen, source_path)
        if green_screen_detected:
            log_event(
                log,
                logging.INFO,
                "Green-screen source detected; using free local chromakey instead of VEED.",
                event="montage_green_screen_routing",
                job_id=job_id,
                suite_id=suite.id,
            )
    if "background" in options and settings.fal_key and (source_path or source_url) and not green_screen_detected:
        if source_path and r2_configured():
            normalized_path = await asyncio.to_thread(normalize_montage_source, source_path, output_dir)
            if normalized_path:
                veed_stage_path = normalized_path
                veed_source_url = await asyncio.to_thread(publish_veed_source, job_id, normalized_path)
        if not veed_source_url and source_url and not uploaded_path and not r2_configured():
            # Self-hosted/dev without R2: trust the user's URL as-is.
            veed_source_url = source_url
            note_fallback("R2 staging is unavailable; sending the original URL to VEED/fal.")
        if not veed_source_url:
            source_warning = chain_warning(
                "Could not stage a normalized source for VEED/fal; falling back to local chromakey preview."
            )
    elif "background" in options and not settings.fal_key:
        source_warning = chain_warning("FAL_KEY is missing; falling back to local FFmpeg chromakey preview.")

    if veed_source_url:
        emit("background_removal", "Removing video background with VEED/fal.", 35)
        transparent_path = output_dir / "transparent-subject.webm"
        veed_call = asyncio.to_thread(
            remove_background_with_veed_fal,
            source_url=veed_source_url,
            output_path=transparent_path,
            fal_key=settings.fal_key,
        )
        pretranscribed: tuple[list[dict[str, Any]], str | None] | None = None
        transcription_source = veed_stage_path or source_path
        if transcription_source:
            # Transcription only needs the audio track, which VEED does not
            # touch — run both provider calls concurrently instead of
            # back-to-back (saves the full Whisper wait on every render).
            provider_result, pretranscribed = await asyncio.gather(
                veed_call,
                asyncio.to_thread(transcribe_video_segments, transcription_source, output_dir),
            )
        else:
            provider_result = await veed_call
        if provider_result.get("ok") and transparent_path.exists():
            emit("rendering", "Rendering layered Remotion montage.", 68)
            output_path = output_dir / "render.mp4"
            render_result = annotate_render(
                await render_remotion_montage(
                    db=db,
                    transparent_source_path=transparent_path,
                    output_path=output_path,
                    suite=suite,
                    input_data=input_data,
                    transcript=pretranscribed,
                    dead_air_joins=dead_air_joins,
                )
            )
            render_result["engine"] = "remotion_veed_fal"
            render_result["background_removal"] = provider_result
            if render_result.get("rendered"):
                emit("packaging", "Packaging montage output.", 88)
                render_result["output_url"] = publish_montage_media(job_id, render_result.get("output_url"))
                package = build_render_package(
                    suite=suite,
                    input_data=input_data,
                    output_dir=output_dir,
                    source_path=transparent_path,
                    render_result=render_result,
                    source_warning=None,
                )
                package["version"] = "video_montage_remotion_v1"
                package["background_removal"] = provider_result
                package["package_url"] = publish_montage_media(job_id, package.get("package_url"))
                return {
                    "video_montage": package,
                    "output_url": render_result.get("output_url"),
                    "package_url": package.get("package_url"),
                    "rendered": True,
                    "source_warning": None,
                }
            source_warning = chain_warning(
                f"Remotion render failed after VEED/fal background removal: {render_result.get('reason') or 'unknown error'}"
            )
        else:
            source_warning = chain_warning(
                f"VEED/fal background removal failed: {provider_result.get('error') or 'unknown error'}"
            )

    if source_path and "background" in options and ffmpeg_filter_available("chromakey"):
        emit("background_removal", "Preparing transparent subject locally.", 48)
        transparent_path = output_dir / "transparent-local-subject.webm"
        local_duration = min(probe_duration_seconds(source_path), float(settings.montage_max_duration_seconds))
        provider_result = create_local_transparent_subject(
            source_path=source_path,
            output_path=transparent_path,
            duration=local_duration,
        )
        if provider_result.get("ok") and transparent_path.exists():
            emit("rendering", "Rendering layered Remotion montage.", 68)
            output_path = output_dir / "render.mp4"
            render_result = annotate_render(
                await render_remotion_montage(
                    db=db,
                    transparent_source_path=transparent_path,
                    output_path=output_path,
                    suite=suite,
                    input_data=input_data,
                    dead_air_joins=dead_air_joins,
                )
            )
            render_result["engine"] = "remotion_local_chromakey"
            render_result["background_removal"] = provider_result
            if source_warning:
                render_result["provider_note"] = source_warning
            if render_result.get("rendered"):
                emit("packaging", "Packaging montage output.", 88)
                render_result["output_url"] = publish_montage_media(job_id, render_result.get("output_url"))
                package = build_render_package(
                    suite=suite,
                    input_data=input_data,
                    output_dir=output_dir,
                    source_path=source_path,
                    render_result=render_result,
                    source_warning=None,
                )
                package["version"] = "video_montage_remotion_v1"
                package["background_removal"] = provider_result
                package["package_url"] = publish_montage_media(job_id, package.get("package_url"))
                return {
                    "video_montage": package,
                    "output_url": render_result.get("output_url"),
                    "package_url": package.get("package_url"),
                    "rendered": True,
                    "source_warning": None,
                }
            source_warning = chain_warning(
                f"Remotion render failed after local chromakey: {render_result.get('reason') or 'unknown error'}"
            )
        else:
            source_warning = chain_warning(
                f"Local chromakey background removal failed: {provider_result.get('error') or 'unknown error'}"
            )
    elif source_path and "background" in options:
        source_warning = chain_warning("FFmpeg chromakey filter is unavailable; falling back to local FFmpeg preview.")

    if source_path and "background" not in options and ffmpeg_available():
        # Honest "no background isolation" montage: the normalized source
        # plays as an opaque full-frame subject inside the same Remotion
        # composition, so captions/titles/music still work without VEED.
        emit("rendering", "Rendering full-frame Remotion montage.", 62)
        normalized_path = await asyncio.to_thread(normalize_montage_source, source_path, output_dir)
        if normalized_path:
            output_path = output_dir / "render.mp4"
            render_result = annotate_render(
                await render_remotion_montage(
                    db=db,
                    transparent_source_path=normalized_path,
                    output_path=output_path,
                    suite=suite,
                    input_data=input_data,
                    subject_has_alpha=False,
                    dead_air_joins=dead_air_joins,
                )
            )
            render_result["engine"] = "remotion_fullframe"
            if source_warning:
                render_result["provider_note"] = source_warning
            if render_result.get("rendered"):
                emit("packaging", "Packaging montage output.", 88)
                render_result["output_url"] = publish_montage_media(job_id, render_result.get("output_url"))
                package = build_render_package(
                    suite=suite,
                    input_data=input_data,
                    output_dir=output_dir,
                    source_path=normalized_path,
                    render_result=render_result,
                    source_warning=None,
                )
                package["version"] = "video_montage_remotion_v1"
                package["package_url"] = publish_montage_media(job_id, package.get("package_url"))
                return {
                    "video_montage": package,
                    "output_url": render_result.get("output_url"),
                    "package_url": package.get("package_url"),
                    "rendered": True,
                    "source_warning": None,
                }
            source_warning = chain_warning(
                f"Full-frame Remotion render failed: {render_result.get('reason') or 'unknown error'}"
            )
        else:
            source_warning = chain_warning(
                "Could not normalize the source for the full-frame Remotion render; falling back to local FFmpeg preview."
            )

    emit("rendering", "Rendering V1 montage preview.", 60)
    # Belt and braces: reaching this point without a source must always carry
    # an explanation into the final result, never a silent null warning.
    if not source_path and not source_warning:
        source_warning = note_fallback("No usable source video was available for rendering.")
    output_path = output_dir / "render.mp4"
    render_result = (
        annotate_render(
            render_v1_video(
                source_path=source_path,
                output_path=output_path,
                suite=suite,
                input_data=input_data,
            )
        )
        if source_path
        else {"rendered": False, "reason": source_warning or "No source video was provided."}
    )
    render_result.setdefault("engine", "ffmpeg_local_fallback")
    if provider_result:
        render_result["background_removal"] = provider_result

    emit("packaging", "Packaging montage output.", 88)
    render_result["output_url"] = publish_montage_media(job_id, render_result.get("output_url"))
    package = build_render_package(
        suite=suite,
        input_data=input_data,
        output_dir=output_dir,
        source_path=source_path,
        render_result=render_result,
        source_warning=source_warning,
    )
    package["package_url"] = publish_montage_media(job_id, package.get("package_url"))
    return {
        "video_montage": package,
        "output_url": render_result.get("output_url"),
        "package_url": package.get("package_url"),
        "rendered": bool(render_result.get("rendered")),
        "source_warning": source_warning,
    }
