"""Arabic text overlay for carousel slides.

Renders a slide title in Arabic at the bottom of the image with:
  • A semi-transparent dark band for legibility.
  • A thin division-color stripe above the band as a brand accent.
  • Cairo font, right-to-left correct via arabic-reshaper + python-bidi.
  • A small slide indicator (e.g. "1/5") in the top-right corner.

Designed to be visually consistent across all slides of a carousel.
"""
from __future__ import annotations

import logging
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS_DIR, BRAND

log = logging.getLogger(__name__)

FONT_BOLD = ASSETS_DIR / "fonts" / "Cairo-Bold.ttf"
FONT_EXTRABOLD = ASSETS_DIR / "fonts" / "Cairo-Black.ttf"
FONT_REGULAR = ASSETS_DIR / "fonts" / "Cairo-Regular.ttf"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _shape(text: str) -> str:
    """Reshape Arabic text for correct rendering (RTL + connected letters)."""
    return get_display(arabic_reshaper.reshape(text))


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _wrap_text_to_width(
    text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """Wrap a string into multiple lines so each line fits within max_width."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = current + " " + w
        # measure UNSHAPED text width — shaping doesn't change Arabic char width meaningfully
        bbox = font.getbbox(candidate)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def _best_font_size(
    text: str, font_path: Path, max_width: int, max_height: int,
    initial: int, min_size: int = 28,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Find the largest font size at which text fits within max_width × max_height
    when wrapped. Returns (font, wrapped_lines)."""
    size = initial
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap_text_to_width(text, font, max_width)
        # Compute total height
        line_heights = []
        for ln in lines:
            bbox = font.getbbox(ln)
            line_heights.append(bbox[3] - bbox[1])
        total_h = sum(line_heights) + (len(lines) - 1) * int(size * 0.25)
        if total_h <= max_height:
            return font, lines
        size -= 4
    # Couldn't fit nicely — return the smallest size with whatever wrapping
    font = ImageFont.truetype(str(font_path), min_size)
    return font, _wrap_text_to_width(text, font, max_width)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def overlay_carousel_title(
    image_path: Path | str,
    title_ar: str,
    division_key: str,
    slide_number: int,
    total_slides: int,
    is_hook: bool = False,
    is_cta: bool = False,
) -> Path:
    """Render the slide title onto the image at image_path (in-place).

    The function overwrites the file with the annotated version.
    Returns the same path.
    """
    image_path = Path(image_path)
    div = BRAND["divisions"].get(division_key, BRAND["divisions"]["design"])
    div_color = _hex_to_rgba(div["color"])

    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ----- Bottom dark band (33% for hook/cta, 22% for content slides) -----
    band_ratio = 0.33 if (is_hook or is_cta) else 0.22
    band_height = int(H * band_ratio)
    band_y = H - band_height
    # Gradient via several rectangles to soften the top edge
    gradient_steps = 14
    for i in range(gradient_steps):
        y0 = band_y - int(H * 0.04) + int((H * 0.04 / gradient_steps) * i)
        alpha = int(255 * (i / gradient_steps) * 0.35)
        draw.rectangle([0, y0, W, y0 + 4], fill=(0, 0, 0, alpha))
    draw.rectangle([0, band_y, W, H], fill=(0, 0, 0, 215))

    # ----- Brand color accent stripe above the band -----
    stripe_h = max(4, int(H * 0.006))
    draw.rectangle([0, band_y - stripe_h, W, band_y], fill=div_color)

    # ----- Title text (centered within the band) -----
    padding_x = int(W * 0.06)
    padding_y = int(band_height * 0.15)
    max_text_width = W - 2 * padding_x
    max_text_height = band_height - 2 * padding_y

    initial_size = int(H * (0.085 if (is_hook or is_cta) else 0.062))
    font_path = FONT_EXTRABOLD if (is_hook or is_cta) else FONT_BOLD
    font, lines = _best_font_size(
        title_ar,
        font_path=font_path,
        max_width=max_text_width,
        max_height=max_text_height,
        initial=initial_size,
    )

    # Compute total text block height
    line_gap = int(font.size * 0.25)
    bbox_sample = font.getbbox("ا")
    line_h = bbox_sample[3] - bbox_sample[1]
    block_h = len(lines) * line_h + (len(lines) - 1) * line_gap
    text_y = band_y + (band_height - block_h) // 2

    for ln in lines:
        shaped = _shape(ln)
        bbox = font.getbbox(shaped)
        line_w = bbox[2] - bbox[0]
        x = (W - line_w) // 2 - bbox[0]
        # Soft shadow for depth
        draw.text((x + 2, text_y + 2), shaped, font=font, fill=(0, 0, 0, 180))
        draw.text((x, text_y), shaped, font=font, fill=(255, 255, 255, 255))
        text_y += line_h + line_gap

    # ----- Slide indicator (e.g. "2 / 5") top-right -----
    if total_slides > 1:
        indicator_font_size = max(24, int(H * 0.028))
        ind_font = ImageFont.truetype(str(FONT_REGULAR), indicator_font_size)
        ind_text = f"{slide_number} / {total_slides}"
        ind_bbox = ind_font.getbbox(ind_text)
        ind_w = ind_bbox[2] - ind_bbox[0]
        ind_h = ind_bbox[3] - ind_bbox[1]
        pad = int(H * 0.025)
        pill_pad_x = int(indicator_font_size * 0.6)
        pill_pad_y = int(indicator_font_size * 0.3)
        pill_w = ind_w + 2 * pill_pad_x
        pill_h = ind_h + 2 * pill_pad_y
        pill_x = W - pad - pill_w
        pill_y = pad
        # Rounded pill
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=pill_h // 2,
            fill=(0, 0, 0, 170),
        )
        draw.text(
            (pill_x + pill_pad_x, pill_y + pill_pad_y - ind_bbox[1]),
            ind_text,
            font=ind_font,
            fill=(255, 255, 255, 255),
        )

    final = Image.alpha_composite(img, overlay).convert("RGB")
    final.save(image_path, format="PNG")
    log.info("Overlaid title on %s", image_path.name)
    return image_path
