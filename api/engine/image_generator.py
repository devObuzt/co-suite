"""Image generator using Nano Banana (Gemini 2.5 Flash Image).

We enhance the user prompt with brand context, then pass the Connec logo as a
reference image so Nano Banana can incorporate it consistently.
"""
import logging
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types as gtypes
from PIL import Image

from .config import (
    ASSETS_DIR,
    BRAND,
    GOOGLE_API_KEY,
    IMAGE_MODEL,
    PROMPTS,
)

log = logging.getLogger(__name__)
_client = genai.Client(api_key=GOOGLE_API_KEY)

# Cost (Google AI Studio pricing, May 2026 — adjust if pricing changes)
COST_PER_IMAGE_USD = 0.039


def _logo_for_division(division: str) -> Path:
    color_map = {
        "design": "connec_logo_yellow.png",
        "marketing": "connec_logo_pink.png",
        "development": "connec_logo_cyan.png",
        "media": "connec_logo_dark.png",
        "academy": "connec_logo_green.png",
    }
    filename = color_map.get(division, "connec_logo_dark.png")
    return ASSETS_DIR / "logos" / filename


def _build_image_prompt(idea: dict) -> str:
    div = BRAND["divisions"].get(idea["division"], BRAND["divisions"]["design"])
    template = PROMPTS["image_enhancement"]
    return template.format(
        division_name=div["name_en"],
        color_name=div["color_name"],
        color_hex=div["color"],
        topic=idea.get("topic", ""),
        aspect_ratio=idea.get("aspect_ratio", "1:1"),
        detailed_prompt=idea.get("image_prompt", ""),
    )


def _build_slide_prompt(idea: dict, slide: dict, total_slides: int) -> str:
    div = BRAND["divisions"].get(idea["division"], BRAND["divisions"]["design"])
    template = PROMPTS["carousel_slide_enhancement"]
    return template.format(
        slide_number=slide.get("slide", 1),
        total_slides=total_slides,
        division_name=div["name_en"],
        color_name=div["color_name"],
        color_hex=div["color"],
        topic=idea.get("topic", ""),
        slide_role=slide.get("role", "content"),
        detailed_prompt=slide.get("image_prompt", ""),
    )


def _call_nano_banana(prompt: str, extra_images: list[Image.Image] | None = None) -> Image.Image:
    """Single Nano Banana call. Returns the produced PIL image."""
    contents: list = [prompt]
    if extra_images:
        contents.extend(extra_images)

    response = _client.models.generate_content(
        model=IMAGE_MODEL,
        contents=contents,
        config=gtypes.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )

    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return Image.open(BytesIO(part.inline_data.data))
    raise RuntimeError(f"Nano Banana returned no image. Response: {response}")


def generate_image(idea: dict, out_dir: Path) -> tuple[Path, float]:
    """Generate a single image, save it to out_dir, return (path, cost_usd).

    If `idea['image_title_ar']` is set, an Arabic hook is overlaid at the
    bottom of the image (same style as carousel hook slides).
    """
    from .text_overlay import overlay_carousel_title

    prompt = _build_image_prompt(idea)
    title_ar = (idea.get("image_title_ar") or "").strip()

    # If we'll be adding a title overlay, reinforce the visual no-text directive
    if title_ar:
        prompt += (
            "\n\nIMPORTANT: This image is a clean visual background. "
            "DO NOT render any text in the image. Leave the bottom 25-30% "
            "relatively clean and uncluttered (we'll add a title text overlay there)."
        )

    logo_path = _logo_for_division(idea["division"])
    extras: list[Image.Image] = []
    if idea.get("include_logo", True) and logo_path.exists() and not title_ar:
        # Skip Veo's logo when we're going to add a title band (the band's
        # accent stripe IS the brand cue; bare logo + band is too busy).
        extras.append(Image.open(logo_path))
        prompt += (
            "\n\nUse the Connec logo image provided as a small overlay in the bottom-right "
            "corner, respecting its colors and proportions. Do not distort it."
        )

    log.info("Generating image for post %s (%s)…", idea.get("id", "?"), idea.get("topic", ""))
    img = _call_nano_banana(prompt, extra_images=extras)

    out_path = out_dir / "image.png"
    img.save(out_path)

    if title_ar:
        try:
            overlay_carousel_title(
                out_path,
                title_ar=title_ar,
                division_key=idea["division"],
                slide_number=1,
                total_slides=1,        # suppresses the "1/N" pill
                is_hook=True,          # bigger band, like the hook slide of a carousel
            )
            log.info("Image hook overlaid: %s", title_ar)
        except Exception as e:
            log.exception("Image title overlay failed; keeping plain image: %s", e)

    log.info("Saved image to %s", out_path)
    return out_path, COST_PER_IMAGE_USD


def generate_carousel(idea: dict, out_dir: Path) -> tuple[list[Path], float]:
    """Generate a multi-slide carousel.

    Each slide uses the previous slide as a visual style reference so the whole
    carousel looks consistent. After generation, an Arabic title overlay is
    rendered on each slide (using brand fonts and division accent colors).
    The Connec logo is left to be added by the overlay style itself (the
    division accent + slide indicator are enough; the bare wordmark on every
    slide is noisy).
    """
    from .text_overlay import overlay_carousel_title

    slides = idea.get("carousel_slides", [])
    if not slides:
        raise ValueError("Carousel idea has no slides")

    log.info(
        "Generating carousel for post %s — %d slides (%s)…",
        idea.get("id", "?"), len(slides), idea.get("topic", ""),
    )

    out_paths: list[Path] = []
    previous_slide_img: Image.Image | None = None

    for i, slide in enumerate(slides, start=1):
        prompt = _build_slide_prompt(idea, slide, total_slides=len(slides))
        # Reinforce no-text directive at the visual level — the title gets added by overlay.
        prompt += (
            "\n\nIMPORTANT: This image is a clean visual background. "
            "DO NOT render any text, letters, words, captions, or readable signs in the image. "
            "Leave the bottom 25-30% of the composition relatively clean and uncluttered "
            "(we'll add a title text overlay there in post-processing)."
        )

        extras: list[Image.Image] = []
        if previous_slide_img is not None:
            extras.append(previous_slide_img)
            prompt += (
                "\n\nThe previous image (provided above) shows the visual style of the "
                "earlier slides in this carousel. Match its color grading, lighting, "
                "composition style, and overall aesthetic exactly."
            )

        log.info("  → slide %d/%d (%s)", i, len(slides), slide.get("role", ""))
        img = _call_nano_banana(prompt, extra_images=extras)

        out_path = out_dir / f"image_{i}.png"
        img.save(out_path)

        # Overlay the Arabic title using brand fonts + division accent
        title_ar = slide.get("title_ar", "")
        if title_ar:
            role = slide.get("role", "content")
            overlay_carousel_title(
                out_path,
                title_ar=title_ar,
                division_key=idea["division"],
                slide_number=i,
                total_slides=len(slides),
                is_hook=(role == "hook"),
                is_cta=(role == "cta"),
            )

        out_paths.append(out_path)
        previous_slide_img = img

    cost = COST_PER_IMAGE_USD * len(slides)
    log.info("Carousel saved (%d slides, cost ≈ $%.2f)", len(slides), cost)
    return out_paths, cost
