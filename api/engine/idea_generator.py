"""Idea generator — asks Claude for daily post ideas with full prompts and captions."""
import json
import logging
import re

from anthropic import Anthropic

from . import dialect_corpus
from .config import (
    ANTHROPIC_API_KEY,
    BRAND,
    CAROUSELS_PER_DAY,
    CLAUDE_MODEL,
    POSTS_PER_DAY,
    PROMPTS,
    VIDEOS_PER_DAY,
    brand_summary_for_claude,
)

log = logging.getLogger(__name__)
_client = Anthropic(api_key=ANTHROPIC_API_KEY)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    # Remove ```json ... ``` fences if Claude added them
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def generate_ideas(
    count: int = POSTS_PER_DAY,
    video_count: int = VIDEOS_PER_DAY,
    carousel_count: int = CAROUSELS_PER_DAY,
    recent_topics: list[str] | None = None,
) -> list[dict]:
    """Call Claude to produce `count` post ideas (full structured)."""
    image_count = max(0, count - video_count - carousel_count)
    recent = recent_topics or []
    recent_str = (
        "\n".join(f"- {t}" for t in recent[:20]) if recent else "(لا يوجد بوستات سابقة)"
    )

    system = PROMPTS["idea_generator_system"].format(
        brand_summary=brand_summary_for_claude()
    )
    # Append latest user dialect corrections so Claude learns over time
    corpus_block = dialect_corpus.format_for_prompt()
    if corpus_block:
        system += "\n" + corpus_block
    user = PROMPTS["idea_generator_user"].format(
        count=count,
        image_count=image_count,
        carousel_count=carousel_count,
        video_count=video_count,
        recent_ideas=recent_str,
    )

    log.info(
        "Asking Claude for %d ideas (%d image, %d carousel, %d video)…",
        count, image_count, carousel_count, video_count,
    )

    # Try up to 3 times — Claude occasionally returns truncated/invalid JSON.
    # We bump max_tokens generously since each post can be ~1k tokens with
    # the carousel/video fields, and we may produce 4-6 posts at once.
    last_error: Exception | None = None
    data = None
    for attempt in range(3):
        try:
            resp = _client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = "".join(block.text for block in resp.content if hasattr(block, "text"))
            cleaned = _strip_json_fences(raw)
            data = json.loads(cleaned)
            break
        except json.JSONDecodeError as e:
            last_error = e
            log.warning(
                "Attempt %d: Claude returned invalid JSON (%s). Retrying…",
                attempt + 1, e,
            )
            # Snapshot the bad output for forensics
            try:
                from .config import LOGS_DIR
                from datetime import datetime
                stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                (LOGS_DIR / f"bad_ideas_{stamp}.txt").write_text(
                    raw, encoding="utf-8",
                )
            except Exception:
                pass
    if data is None:
        log.error("Claude failed to return valid JSON after 3 attempts")
        raise last_error or RuntimeError("Claude JSON decode failed")

    posts = data.get("posts", [])
    if not posts:
        raise RuntimeError("Claude returned no posts")

    # Validate each post has the required fields
    base_required = {"division", "goal", "format", "topic", "caption"}
    for i, p in enumerate(posts):
        missing = base_required - set(p.keys())
        if missing:
            log.warning("Post %d missing fields: %s — filling defaults", i, missing)
            for f in missing:
                p.setdefault(f, "")
        # Normalize division key
        if p["division"] not in BRAND["divisions"]:
            log.warning("Unknown division '%s' — defaulting to 'design'", p["division"])
            p["division"] = "design"
        # Normalize format
        fmt = p.get("format", "image")
        if fmt not in ("image", "carousel", "video"):
            log.warning("Unknown format '%s' — defaulting to 'image'", fmt)
            p["format"] = "image"
        # Format-specific validation
        if p["format"] == "carousel":
            slides = p.get("carousel_slides", [])
            if not slides or len(slides) < 2:
                log.warning("Carousel post %d has no slides — downgrading to image", i)
                p["format"] = "image"
                p.setdefault("image_prompt", p.get("topic", ""))
            else:
                # Cap at 6 slides for IG limit safety
                p["carousel_slides"] = slides[:6]
                p["aspect_ratio"] = "1:1"
                # Ensure each slide has a title_ar
                for j, s in enumerate(p["carousel_slides"], start=1):
                    if not s.get("title_ar"):
                        s["title_ar"] = p.get("topic", f"سلايد {j}")[:40]
                    s.setdefault("slide", j)
                    s.setdefault("role", "hook" if j == 1 else ("cta" if j == len(slides) else "content"))
                    s.setdefault("image_prompt", p.get("image_prompt", p.get("topic", "")))
        if p["format"] == "image":
            p.setdefault("image_prompt", p.get("topic", ""))
            p.setdefault("aspect_ratio", "1:1")
            # image_title_ar is optional — Claude decides per-image whether to overlay a hook
            p.setdefault("image_title_ar", "")
        if p["format"] == "video":
            p.setdefault("video_prompt", p.get("image_prompt", p.get("topic", "")))
            p.setdefault("aspect_ratio", "9:16")

            # Normalize video_subtype
            valid_subtypes = {"animation", "english_hook", "video_with_titles"}
            subtype = (p.get("video_subtype") or "").strip()
            if subtype not in valid_subtypes:
                log.warning(
                    "Post %d has unknown video_subtype %r — defaulting to 'video_with_titles'",
                    i, subtype,
                )
                subtype = "video_with_titles"
            p["video_subtype"] = subtype

            # Ensure subtype-specific text fields exist
            if subtype == "video_with_titles":
                segs = p.get("video_title_segments") or []
                # Validate segments structure if provided
                clean_segs = []
                for s in segs:
                    if not isinstance(s, dict):
                        continue
                    text = (s.get("text") or "").strip()
                    try:
                        start = float(s.get("start", 0))
                        end = float(s.get("end", 0))
                    except (TypeError, ValueError):
                        continue
                    if text and end > start:
                        clean_segs.append({"start": start, "end": end, "text": text[:60]})
                # Cap at 5 segments
                clean_segs = clean_segs[:5]
                p["video_title_segments"] = clean_segs

                # If no segments AND no single title, synthesize one from hook
                if not clean_segs and not p.get("video_title_ar"):
                    p["video_title_ar"] = p.get("hook", p.get("topic", ""))[:40]
            if subtype == "english_hook" and not p.get("video_hook_en"):
                p["video_hook_en"] = "Built different"  # neutral fallback

            # Voiceover is opt-in only (TTS pipeline is preserved for later)
            p.setdefault("use_voiceover", False)
            p.setdefault("voiceover_ar", "")
            p.setdefault("voiceover_ar_tashkeel", "")
            p.setdefault("voiceover_phonetic_en", "")
            p.setdefault("voiceover_directive_en", "")
        p.setdefault("hashtags", [])
        p.setdefault("include_logo", True)

    log.info("Got %d valid ideas", len(posts))
    return posts
