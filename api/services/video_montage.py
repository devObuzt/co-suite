from __future__ import annotations

import json
import math
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
from arabic_reshaper import reshape
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from ..core.config import settings
from ..models.suite import Suite

ProgressWriter = Callable[[dict[str, Any]], None]

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MONTAGE_ROOT = STATIC_ROOT / "video_montage"
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
MAX_REMOTE_BYTES = 500 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 45
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
FAL_VEED_MODEL = "veed/video-background-removal"


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


def remove_background_with_veed_fal(
    *,
    source_url: str,
    output_path: Path,
    fal_key: str,
    poll_seconds: int = 10,
    max_wait_seconds: int = 900,
) -> dict[str, Any]:
    """Remove a person's video background using the VEED/fal provider.

    The old successful montage POC started from this transparent WebM output.
    Keeping this as a focused function makes it testable and lets the local
    chromakey path remain a fallback instead of the main production path.
    """
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
    transcript_path = output_dir / "transcript.json"
    transcript_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    return segments[:18], None


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


def build_remotion_scene_manifest(
    *,
    transparent_source_path: Path,
    work_dir: Path,
    suite: Suite,
    input_data: dict[str, Any],
    duration: float,
    transcript_segments: list[dict[str, Any]],
    fps: int = 30,
) -> tuple[Path, list[dict[str, Any]]]:
    src_dir, public_dir = copy_remotion_runtime(work_dir)
    inputs_dir = public_dir / "inputs"
    backgrounds_dir = public_dir / "backgrounds"
    sound_dir = public_dir / "sound"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    backgrounds_dir.mkdir(parents=True, exist_ok=True)
    sound_dir.mkdir(parents=True, exist_ok=True)

    source_copy = inputs_dir / transparent_source_path.name
    if transparent_source_path.resolve() != source_copy.resolve():
        shutil.copy2(transparent_source_path, source_copy)

    frames_dir = inputs_dir / f"{transparent_source_path.stem}-frames"
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
                "scale=1080:1920",
                "-start_number",
                "0",
                str(frames_dir / "frame_%05d.png"),
            ]
        )

    audio_path = inputs_dir / f"{transparent_source_path.stem}-audio.m4a"
    if not audio_path.exists() and ffprobe_has_audio(transparent_source_path):
        run_command(["ffmpeg", "-y", "-i", str(transparent_source_path), "-vn", "-c:a", "aac", "-b:a", "192k", str(audio_path)])
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

    scenes: list[dict[str, Any]] = []
    for index, segment in enumerate(transcript_segments[:18]):
        start = max(0.0, float(segment.get("start") or 0) - 0.12)
        end = min(duration, float(segment.get("end") or duration) + 0.12)
        if end <= start:
            end = min(duration, start + 1.5)
        caption = re.sub(r"\s+", " ", str(segment.get("text") or notes or title_from_suite(suite))).strip()
        palette = [
            ["#07111f", "#2f80ed", "#e8f3ff"],
            ["#15120f", "#e6aa3b", "#fff2cf"],
            ["#102018", "#28c76f", "#e6fff1"],
            ["#201225", "#d85cff", "#ffe9ff"],
            ["#1c1d21", "#ff5f45", "#fff0ec"],
        ][index % 5]
        background_path = backgrounds_dir / f"scene-{index + 1:02d}.png"
        if not background_path.exists():
            create_montage_background(background_path, suite)
        scenes.append(
            {
                "id": f"scene-{index + 1:02d}",
                "sourceStart": round(start, 3),
                "sourceEnd": round(end, 3),
                "caption": caption,
                "behindText": title_from_caption(caption, title_from_suite(suite)),
                "backgroundPrompt": f"Vertical editorial background inspired by this spoken line: {caption}",
                "palette": palette,
                "backgroundImagePublicPath": f"/remotion/backgrounds/{background_path.name}",
            }
        )

    for index in range(len(scenes) - 1):
        if scenes[index]["sourceEnd"] > scenes[index + 1]["sourceStart"]:
            boundary = round((scenes[index]["sourceEnd"] + scenes[index + 1]["sourceStart"]) / 2, 3)
            scenes[index]["sourceEnd"] = boundary
            scenes[index + 1]["sourceStart"] = boundary

    edited_duration = sum(max(0.1, scene["sourceEnd"] - scene["sourceStart"]) for scene in scenes)
    music_path = sound_dir / "marketing-upbeat-bed.wav"
    whoosh_path = sound_dir / "soft-whoosh.wav"
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

    manifest = {
        "fps": fps,
        "width": 1080,
        "height": 1920,
        "source": {
            "publicPath": f"/remotion/inputs/{source_copy.name}",
            "originalPath": str(transparent_source_path),
            "durationSeconds": round(duration, 3),
            "hasAlpha": True,
            "framesPublicPath": f"/remotion/inputs/{frames_dir.name}",
            "framePattern": "frame_%05d.png",
        },
        "audio": {
            "sourcePublicPath": f"/remotion/inputs/{audio_path.name}",
            "backgroundMusic": {"publicPath": "/remotion/sound/marketing-upbeat-bed.wav", "volume": 0.32} if music_path.exists() else None,
            "soundEffects": [
                {"publicPath": "/remotion/sound/soft-whoosh.wav", "at": round(start, 3), "volume": 0.58}
                for start in starts[1:]
                if whoosh_path.exists()
            ],
        },
        "style": {"fontFamily": "ConnecAssistant", "arabicFontFamily": "ConnecCairo"},
        "scenes": scenes,
        "durationSeconds": round(edited_duration, 3),
    }
    manifest_path = src_dir / "manifest.generated.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, scenes


def render_remotion_montage(
    *,
    transparent_source_path: Path,
    output_path: Path,
    suite: Suite,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    if not ffmpeg_available():
        return {"rendered": False, "reason": "FFmpeg/FFprobe are not installed in this runtime."}
    if not transparent_source_path.exists():
        return {"rendered": False, "reason": "Transparent subject video was not found."}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = min(probe_duration_seconds(transparent_source_path), 45.0)
    transcript_segments, transcript_warning = transcribe_video_segments(transparent_source_path, output_path.parent)
    warnings = [transcript_warning] if transcript_warning else []
    work_dir = remotion_work_dir(output_path)
    manifest_path, scenes = build_remotion_scene_manifest(
        transparent_source_path=transparent_source_path,
        work_dir=work_dir,
        suite=suite,
        input_data=input_data,
        duration=duration,
        transcript_segments=transcript_segments,
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
            ]
        )
    except subprocess.CalledProcessError as exc:
        return {
            "rendered": False,
            "reason": (exc.stderr or exc.stdout or str(exc))[-1200:],
            "manifest_path": str(manifest_path),
            "warnings": warnings,
        }

    return {
        "rendered": output_path.exists(),
        "duration_seconds": duration,
        "output_url": public_static_url(output_path),
        "capabilities_applied": [
            "api_background_removal",
            "transparent_subject_frames",
            "remotion_layered_render",
            "animated_background",
            "behind_person_3d_title",
            "rtl_text_overlay",
            "visual_transitions",
            "sound_effect_transitions",
            "music_bed",
            "mp4_delivery",
        ],
        "warnings": warnings,
        "manifest_path": str(manifest_path),
        "scene_count": len(scenes),
    }


def cut_dead_spaces(source_path: Path, output_path: Path, duration: float) -> tuple[Path, bool, str | None]:
    if not ffprobe_has_audio(source_path):
        return source_path, False, "No audio stream was found, so silence cutting was skipped."
    segments = non_silent_segments(source_path, duration)
    if len(segments) <= 1:
        return source_path, False, None
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
        return source_path, False, (exc.stderr or exc.stdout or str(exc))[-500:]
    return output_path, True, None


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
        audio_chain = "highpass=f=80,lowpass=f=12000,afftdn,loudnorm=I=-16:LRA=11:TP=-1.5"
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
    options = requested_options(input_data)
    capabilities = ["video_fit_vertical", "mp4_delivery"]
    warnings: list[str] = []

    working_source = source_path
    if "dead_spaces" in options:
        working_source, cut_applied, cut_warning = cut_dead_spaces(
            source_path,
            output_path.with_name("cut-source.mp4"),
            duration,
        )
        if cut_applied:
            capabilities.append("silence_cutting")
            duration = min(probe_duration_seconds(working_source), 45.0)
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
        "version": "video_montage_remotion_v1" if engine == "remotion_veed_fal" else "video_montage_v1",
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
    provider_result: dict[str, Any] | None = None
    uploaded_path = input_data.get("source_file_path")

    source_url = str(input_data.get("source_url") or "").strip()
    options = requested_options(input_data)
    if "background" in options and source_url and settings.fal_key:
        emit("background_removal", "Removing video background with VEED/fal.", 35)
        transparent_path = output_dir / "transparent-subject.webm"
        provider_result = remove_background_with_veed_fal(
            source_url=source_url,
            output_path=transparent_path,
            fal_key=settings.fal_key,
        )
        if provider_result.get("ok") and transparent_path.exists():
            emit("rendering", "Rendering layered Remotion montage.", 68)
            output_path = output_dir / "render.mp4"
            render_result = render_remotion_montage(
                transparent_source_path=transparent_path,
                output_path=output_path,
                suite=suite,
                input_data=input_data,
            )
            render_result["engine"] = "remotion_veed_fal"
            render_result["background_removal"] = provider_result
            if render_result.get("rendered"):
                emit("packaging", "Packaging montage output.", 88)
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
                return {
                    "video_montage": package,
                    "output_url": render_result.get("output_url"),
                    "package_url": package.get("package_url"),
                    "rendered": True,
                    "source_warning": None,
                }
            source_warning = f"Remotion render failed after VEED/fal background removal: {render_result.get('reason') or 'unknown error'}"
        else:
            source_warning = f"VEED/fal background removal failed: {provider_result.get('error') or 'unknown error'}"
    elif "background" in options and source_url and not settings.fal_key:
        source_warning = "FAL_KEY is missing; falling back to local FFmpeg chromakey preview."
    elif "background" in options and uploaded_path and not source_url:
        source_warning = "A public source URL is required for VEED/fal background removal; falling back to local FFmpeg chromakey preview."

    if uploaded_path:
        candidate = Path(str(uploaded_path))
        if candidate.exists():
            source_path = candidate
        else:
            source_warning = "Uploaded source file was not found on disk."
    elif source_url:
        source_path, source_warning = await download_source(
            source_url,
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
    render_result.setdefault("engine", "ffmpeg_local_fallback")
    if provider_result:
        render_result["background_removal"] = provider_result

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
