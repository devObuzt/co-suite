from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import httpx

from ..models.suite import Suite

ProgressWriter = Callable[[dict[str, Any]], None]

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MONTAGE_ROOT = STATIC_ROOT / "video_montage"
MAX_REMOTE_BYTES = 500 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 45
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def job_dir(job_id: str) -> Path:
    path = MONTAGE_ROOT / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_static_url(path: Path) -> str:
    relative = path.relative_to(STATIC_ROOT)
    return f"/static/{relative.as_posix()}"


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
    return subprocess.run(command, check=True, capture_output=True, text=True)


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


async def download_source(source_url: str, destination: Path) -> tuple[Path | None, str | None]:
    if not source_url:
        return None, "No source URL was provided."

    url = google_drive_direct_url(source_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if "text/html" in content_type and "drive.google.com" in url:
                    return None, "Google Drive did not return the video file. Share a direct-download link or upload the file."
                if "text/html" in content_type:
                    return None, "The URL returned a web page instead of a video file."

                with destination.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_REMOTE_BYTES:
                            handle.close()
                            destination.unlink(missing_ok=True)
                            return None, "The remote video is larger than the 500 MB V1 limit."
                        handle.write(chunk)
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


def render_v1_video(*, source_path: Path, output_path: Path, suite: Suite, input_data: dict[str, Any]) -> dict[str, Any]:
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
    duration = min(probe_duration_seconds(source_path), 45.0)
    drawtext_enabled = ffmpeg_filter_available("drawtext")
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=#101828,"
        "setsar=1"
    )
    if drawtext_enabled:
        title_path = write_text_file(output_path.with_suffix(".title.txt"), title_from_suite(suite))
        notes = str(input_data.get("notes") or "").strip()
        caption_path = write_text_file(
            output_path.with_suffix(".caption.txt"),
            notes[:140] if notes else "مونتاج أولي جاهز للمراجعة",
        )
        font_path = Path(__file__).resolve().parent.parent / "fonts" / "NotoSansArabic-Regular.ttf"
        font_arg = str(font_path) if font_path.exists() else "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
        vf += (
            f",drawtext=fontfile='{font_arg}':textfile='{title_path}':"
            "x=(w-text_w)/2:y=120:fontsize=64:fontcolor=white:"
            "box=1:boxcolor=black@0.38:boxborderw=22,"
            f"drawtext=fontfile='{font_arg}':textfile='{caption_path}':"
            "x=(w-text_w)/2:y=h-260:fontsize=42:fontcolor=white:"
            "box=1:boxcolor=black@0.42:boxborderw=18"
        )
    command = [
        "ffmpeg",
        "-y",
        "-t",
        str(duration),
        "-i",
        str(source_path),
        "-vf",
        vf,
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
        str(output_path),
    ]
    try:
        run_command(command)
    except subprocess.CalledProcessError as exc:
        return {
            "rendered": False,
            "reason": (exc.stderr or exc.stdout or str(exc))[-1200:],
        }

    return {
        "rendered": output_path.exists(),
        "duration_seconds": duration,
        "output_url": public_static_url(output_path),
        "capabilities_applied": [
            "video_fit_vertical",
            *(["title_overlay", "caption_overlay"] if drawtext_enabled else []),
            "mp4_delivery",
        ],
        "warnings": [] if drawtext_enabled else ["FFmpeg drawtext filter is unavailable; exported without text overlays."],
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
    package = {
        "version": "video_montage_v1",
        "suite_id": suite.id,
        "mode": input_data.get("mode") or "talking_head",
        "source_url": input_data.get("source_url"),
        "source_file_url": public_static_url(source_path) if source_path and source_path.exists() else None,
        "notes": input_data.get("notes") or "",
        "requested_options": options,
        "render": render_result,
        "source_warning": source_warning,
        "next_engine_steps": [
            "wire_remotion_manifest_from_transcript",
            "apply_silence_cutting",
            "mix_music_and_sound_effects",
            "enable_background_removal_provider",
            "store_outputs_in_cloud_storage",
        ],
    }
    manifest_path = output_dir / "render-package.json"
    manifest_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    package["package_url"] = public_static_url(manifest_path)
    return package


async def generate_video_montage_for_suite(
    *,
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
    source_warning = None
    source_path = None
    uploaded_path = input_data.get("source_file_path")
    if uploaded_path:
        candidate = Path(str(uploaded_path))
        if candidate.exists():
            source_path = candidate
        else:
            source_warning = "Uploaded source file was not found on disk."
    elif input_data.get("source_url"):
        source_path, source_warning = await download_source(
            str(input_data.get("source_url") or ""),
            output_dir / "source_from_url.mp4",
        )

    emit("rendering", "Rendering V1 montage preview.", 60)
    output_path = output_dir / "render.mp4"
    render_result = (
        render_v1_video(
            source_path=source_path,
            output_path=output_path,
            suite=suite,
            input_data=input_data,
        )
        if source_path
        else {"rendered": False, "reason": source_warning or "No source video was provided."}
    )

    emit("packaging", "Packaging montage output.", 88)
    package = build_render_package(
        suite=suite,
        input_data=input_data,
        output_dir=output_dir,
        source_path=source_path,
        render_result=render_result,
        source_warning=source_warning,
    )
    return {
        "video_montage": package,
        "output_url": render_result.get("output_url"),
        "package_url": package.get("package_url"),
        "rendered": bool(render_result.get("rendered")),
        "source_warning": source_warning,
    }
