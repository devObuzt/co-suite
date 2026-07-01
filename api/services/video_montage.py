from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
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
MAX_REMOTE_BYTES = 500 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 45
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


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
            "[1:v]chromakey=0x00b050:0.22:0.10,"
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "scale=w='iw*(1+0.025*sin(t*0.75))':h='ih*(1+0.025*sin(t*0.75))':eval=frame,"
            "setsar=1[fg]"
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
