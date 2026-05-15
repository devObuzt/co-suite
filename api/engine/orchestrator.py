"""End-to-end orchestrator: ideas → media → approval queue.

Run this once per day (cron). For each idea:
  1. Generate the image or video.
  2. Save to data/pending/<post_id>/.
  3. Send to Telegram for approval.

Budget guard: stop generating videos once the daily video cost limit is reached;
fall back to images for the remaining slots.
"""
import logging
from pathlib import Path

from . import posts_bank
from .config import (
    CAROUSELS_PER_DAY,
    DAILY_VIDEO_BUDGET_USD,
    LOGS_DIR,
    POSTS_PER_DAY,
    VIDEOS_PER_DAY,
)
from .idea_generator import generate_ideas
from .image_generator import generate_carousel, generate_image
from .telegram_bot import send_for_approval, send_voiceover_for_approval
from .video_generator import generate_video


def _setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    # Add a file handler if one doesn't already point at pipeline.log
    log_path = LOGS_DIR / "pipeline.log"
    have_file = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(log_path)
        for h in root.handlers
    )
    if not have_file:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # Ensure at least one stream handler is present
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


log = logging.getLogger("orchestrator")


def run_daily(
    count: int = POSTS_PER_DAY,
    video_count: int = VIDEOS_PER_DAY,
    carousel_count: int = CAROUSELS_PER_DAY,
) -> None:
    _setup_logging()
    posts_bank.init_db()

    spent_today = posts_bank.todays_video_cost()
    log.info("Budget — already spent today: $%.2f / $%.2f", spent_today, DAILY_VIDEO_BUDGET_USD)

    recent = posts_bank.recent_topics(limit=30)
    ideas = generate_ideas(
        count=count,
        video_count=video_count,
        carousel_count=carousel_count,
        recent_topics=recent,
    )

    for idea in ideas:
        try:
            _process_idea(idea, spent_today_ref=[spent_today])
        except Exception as e:
            log.exception("Failed to process idea %s: %s", idea.get("topic"), e)


def _process_idea(idea: dict, spent_today_ref: list[float]) -> None:
    record = posts_bank.create_pending_post(idea)
    post_id = record["id"]
    folder = Path(record["folder"])
    log.info(
        "Processing %s — %s [%s/%s]",
        post_id, idea.get("topic"), idea["division"], idea["format"],
    )

    fmt = idea["format"]

    # Budget guard for videos: downgrade to image if we'd exceed daily budget.
    if fmt == "video":
        projected = 8 * 0.15  # 8s of Veo Fast — worst-case projected
        if (spent_today_ref[0] + projected) > DAILY_VIDEO_BUDGET_USD:
            log.warning(
                "Budget guard — downgrading %s from video to image (spent=$%.2f / $%.2f)",
                post_id, spent_today_ref[0], DAILY_VIDEO_BUDGET_USD,
            )
            fmt = "image"
            idea["format"] = "image"
            posts_bank.update_post(post_id, format="image")

    if fmt == "video":
        # Voiceover approval is only relevant when use_voiceover is True (TTS pipeline).
        # For our current three subtypes (animation / english_hook / video_with_titles),
        # we ship without spoken voiceover, so we generate directly.
        if idea.get("use_voiceover") and (
            idea.get("voiceover_ar") or idea.get("voiceover_ar_tashkeel")
        ):
            posts_bank.update_post(post_id, status="PENDING_VO")
            send_voiceover_for_approval(post_id)
            return
        media_path, cost = generate_video(idea, folder)
        posts_bank.set_media_path(post_id, media_path)
    elif fmt == "carousel":
        media_paths, cost = generate_carousel(idea, folder)
        posts_bank.set_media_paths(post_id, media_paths)
    else:
        media_path, cost = generate_image(idea, folder)
        posts_bank.set_media_path(post_id, media_path)

    posts_bank.add_cost(post_id, cost)
    spent_today_ref[0] += cost

    send_for_approval(post_id)


if __name__ == "__main__":
    run_daily()
