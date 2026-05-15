"""Overlay an Arabic title onto a video.

Strategy:
  1. Render the Arabic title to a transparent PNG at the video's width (using
     PIL + Noto Sans Arabic — same stack as carousel overlays).
  2. Use ffmpeg's `overlay` filter to composite that PNG onto the video at a
     fixed lower-middle position (centered horizontally, ~72% from top).
  3. Fade the overlay in for the first 0.4s and hold it for the rest of the clip.

The title styling matches the carousel overlay so the whole brand feels cohesive:
dark semi-transparent band + division-color accent stripe + bold Arabic text.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS_DIR, BRAND

log = logging.getLogger(__name__)

FONT_EXTRABOLD = ASSETS_DIR / "fonts" / "Cairo-Black.ttf"
FONT_BOLD = ASSETS_DIR / "fonts" / "Cairo-Bold.ttf"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

# Vertical position of the text band, as a fraction of video height
# (0 = top, 1 = bottom). 0.72 puts it in the lower-middle — between the
# horizontal midline and the bottom edge.
DEFAULT_BAND_Y_FRACTION = 0.72


def _shape(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text))


def _hex_to_rgba(hex_str: str, alpha: int = 255):
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _probe_video(path: Path) -> tuple[int, int]:
    """Return (width, height) of a video file via ffprobe."""
    proc = subprocess.run(
        [
            FFPROBE, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    w_str, _, h_str = proc.stdout.strip().partition("x")
    return int(w_str), int(h_str)


def _measured_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    """Width of the SHAPED Arabic string in pixels — what PIL will actually draw."""
    shaped = _shape(text)
    bbox = font.getbbox(shaped)
    return bbox[2] - bbox[0]


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    """Full line height (ascent + descent), enough room for descenders like ج ع م."""
    ascent, descent = font.getmetrics()
    return ascent + descent


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = current + " " + w
        if _measured_width(candidate, font) <= max_w:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def _best_font(text: str, font_path: Path, max_w: int, max_h: int, initial: int):
    """Find the largest font size at which the text fits within max_w × max_h.

    Prefers a single line when possible; falls back to wrapping only if a single
    line would be too small to read.
    """
    # Phase 1: try to keep ALL text on a single line, shrinking font until it fits width
    size = initial
    min_single_line = max(int(initial * 0.55), 36)
    while size >= min_single_line:
        f = ImageFont.truetype(str(font_path), size)
        if _measured_width(text, f) <= max_w and _line_height(f) <= max_h:
            return f, [text]
        size -= 4

    # Phase 2: allow wrapping, but only if each line fits and total height fits
    size = initial
    while size >= 28:
        f = ImageFont.truetype(str(font_path), size)
        lines = _wrap_to_width(text, f, max_w)
        line_h = _line_height(f)
        gap = int(size * 0.18)
        total_h = len(lines) * line_h + (len(lines) - 1) * gap
        all_fit = all(_measured_width(ln, f) <= max_w for ln in lines)
        if all_fit and total_h <= max_h:
            return f, lines
        size -= 4

    f = ImageFont.truetype(str(font_path), 28)
    return f, _wrap_to_width(text, f, max_w)


def render_title_png(
    title_ar: str,
    division_key: str,
    video_width: int,
    video_height: int,
    out_path: Path,
    band_y_fraction: float = DEFAULT_BAND_Y_FRACTION,
) -> Path:
    """Render the Arabic title as a transparent PNG sized to the video frame.

    The PNG matches the video's full WxH. The text and band are positioned at
    band_y_fraction from the top; everything else is transparent.
    """
    div = BRAND["divisions"].get(division_key, BRAND["divisions"]["design"])
    accent = _hex_to_rgba(div["color"])

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Band geometry
    band_height = int(video_height * 0.16)
    band_top = int(video_height * band_y_fraction) - band_height // 2
    band_bottom = band_top + band_height

    # Soft top fade-in to the band (subtle gradient just above the solid block)
    fade_steps = 10
    fade_h = int(video_height * 0.04)
    for i in range(fade_steps):
        y0 = band_top - fade_h + int((fade_h / fade_steps) * i)
        a = int(180 * (i / fade_steps))
        draw.rectangle([0, y0, video_width, y0 + max(2, fade_h // fade_steps)],
                       fill=(0, 0, 0, a))

    # Main band (semi-transparent black)
    draw.rectangle([0, band_top, video_width, band_bottom], fill=(0, 0, 0, 210))

    # Accent stripe above the band (division color)
    stripe_h = max(4, int(video_height * 0.006))
    draw.rectangle([0, band_top - stripe_h, video_width, band_top], fill=accent)

    # Text
    padding_x = int(video_width * 0.06)
    padding_y = int(band_height * 0.15)
    max_text_w = video_width - 2 * padding_x
    max_text_h = band_height - 2 * padding_y

    initial_size = int(video_height * 0.06)
    font, lines = _best_font(title_ar, FONT_EXTRABOLD, max_text_w, max_text_h, initial_size)

    line_gap = int(font.size * 0.18)
    line_h = _line_height(font)
    block_h = len(lines) * line_h + (len(lines) - 1) * line_gap
    text_y = band_top + (band_height - block_h) // 2

    for ln in lines:
        shaped = _shape(ln)
        bbox = font.getbbox(shaped)
        line_w = bbox[2] - bbox[0]
        x = (video_width - line_w) // 2 - bbox[0]
        # Shadow
        draw.text((x + 2, text_y + 2), shaped, font=font, fill=(0, 0, 0, 200))
        # Main text
        draw.text((x, text_y), shaped, font=font, fill=(255, 255, 255, 255))
        text_y += line_h + line_gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path


def overlay_arabic_title(
    video_path: Path | str,
    title_ar: str,
    division_key: str,
    output_path: Path | str,
    band_y_fraction: float = DEFAULT_BAND_Y_FRACTION,
    fade_in_seconds: float = 0.4,
) -> Path:
    """Single-title overlay (full duration).

    Thin wrapper around `overlay_arabic_segments` for the simple case of one
    title spanning the entire clip.
    """
    return overlay_arabic_segments(
        video_path=video_path,
        segments=[{"start": 0.0, "end": 30.0, "text": title_ar}],
        division_key=division_key,
        output_path=output_path,
        band_y_fraction=band_y_fraction,
    )


def overlay_arabic_segments(
    video_path: Path | str,
    segments: list[dict],
    division_key: str,
    output_path: Path | str,
    band_y_fraction: float = DEFAULT_BAND_Y_FRACTION,
) -> Path:
    """Composite multiple time-coded Arabic title overlays onto the video.

    Each segment is a dict {"start": float, "end": float, "text": str}.
    Segments can overlap or be back-to-back; each appears only during its window.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not segments:
        raise ValueError("overlay_arabic_segments called with empty segments")

    w, h = _probe_video(video_path)

    # 1. Render one PNG per segment
    png_paths: list[Path] = []
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        png = output_path.parent / f"_seg_{i:02d}.png"
        render_title_png(text, division_key, w, h, png, band_y_fraction)
        png_paths.append(png)

    if not png_paths:
        raise ValueError("All segments had empty text")

    # 2. Build ffmpeg command — one -loop input per PNG, then a chained
    #    overlay filter graph with `enable` windows.
    inputs: list[str] = ["-i", str(video_path)]
    for p in png_paths:
        inputs += ["-loop", "1", "-t", "30", "-i", str(p)]

    # Filter graph: chain overlays. Each takes [prev][i+1:v] and produces [vN].
    filter_parts: list[str] = []
    current = "[0:v]"
    for idx, seg in enumerate(segments):
        if idx >= len(png_paths):
            break
        start = max(0.0, float(seg.get("start", 0.0)))
        end = float(seg.get("end", start + 8.0))
        out_label = f"[v{idx}]" if idx < len(png_paths) - 1 else "[vout]"
        filter_parts.append(
            f"{current}[{idx + 1}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'{out_label}"
        )
        current = out_label

    filter_complex = ";".join(filter_parts)

    cmd = [FFMPEG, "-y", *inputs,
           "-filter_complex", filter_complex,
           "-map", "[vout]",
           "-map", "0:a?",
           "-c:v", "libx264",
           "-pix_fmt", "yuv420p",
           "-preset", "fast",
           "-crf", "20",
           "-shortest",
           str(output_path)]

    log.info("ffmpeg multi-segment overlay → %s (%d segments)", output_path.name, len(png_paths))
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Tidy: remove intermediate PNGs
    for p in png_paths:
        try:
            p.unlink()
        except OSError:
            pass

    if proc.returncode != 0:
        log.error("ffmpeg overlay failed:\n%s", proc.stderr[-2000:])
        raise RuntimeError(f"ffmpeg overlay failed: {proc.stderr[-500:]}")

    return output_path
