"""Flexible scheduling — assigns approved posts to peak publishing windows.

Windows from PUBLISH_WINDOWS env var, e.g. "11:00-13:00,15:00-17:00,19:00-22:00".
Within each window, the post gets a random time. Minimum gap between any two
scheduled posts on the same day is PUBLISH_MIN_GAP_MINUTES.

Each window holds up to MAX_POSTS_PER_WINDOW (default 2). If today's windows
are full, scheduling rolls over to the next day.
"""
import logging
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import posts_bank
from .config import PUBLISH_MIN_GAP_MINUTES, PUBLISH_WINDOWS, TIMEZONE

log = logging.getLogger(__name__)

MAX_POSTS_PER_WINDOW = 2
LOOKAHEAD_DAYS = 7
PUBLISH_LEAD_MINUTES = 30  # never schedule sooner than this from now


def _parse_windows() -> list[tuple[time, time]]:
    out = []
    for raw in PUBLISH_WINDOWS.split(","):
        raw = raw.strip()
        if not raw:
            continue
        start_s, end_s = raw.split("-")
        h1, m1 = map(int, start_s.split(":"))
        h2, m2 = map(int, end_s.split(":"))
        out.append((time(h1, m1), time(h2, m2)))
    return out


def _tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def _to_utc_iso(dt_local: datetime) -> str:
    return dt_local.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _scheduled_local_times(day: datetime) -> list[datetime]:
    """Get all already-scheduled local times for a given local day."""
    tz = _tz()
    day_start = datetime.combine(day.date(), time(0, 0, tzinfo=tz))
    day_end = day_start + timedelta(days=1)

    scheduled = posts_bank.list_scheduled()
    out = []
    for p in scheduled:
        sched = p.get("scheduled_publish_at")
        if not sched:
            continue
        dt = _parse_iso(sched).astimezone(tz)
        if day_start <= dt < day_end:
            out.append(dt)
    return sorted(out)


def _try_pick_in_window(
    day_local: datetime,
    win_start: time,
    win_end: time,
    occupied: list[datetime],
) -> datetime | None:
    """Pick a random time within [win_start, win_end] respecting min gap & lead time."""
    tz = _tz()
    win_dt_start = datetime.combine(day_local.date(), win_start, tzinfo=tz)
    win_dt_end = datetime.combine(day_local.date(), win_end, tzinfo=tz)

    now = datetime.now(tz)
    earliest = now + timedelta(minutes=PUBLISH_LEAD_MINUTES)
    start = max(win_dt_start, earliest)
    if start >= win_dt_end:
        return None

    # How many of the occupied posts are inside this window?
    in_window = [d for d in occupied if win_dt_start <= d < win_dt_end]
    if len(in_window) >= MAX_POSTS_PER_WINDOW:
        return None

    # Try a handful of random times; reject any that violate min_gap.
    min_gap = timedelta(minutes=PUBLISH_MIN_GAP_MINUTES)
    total_range = int((win_dt_end - start).total_seconds())
    if total_range <= 0:
        return None

    for _ in range(20):
        offset = random.randint(0, total_range)
        candidate = start + timedelta(seconds=offset)
        # Snap to the nearest minute (cleaner times)
        candidate = candidate.replace(second=0, microsecond=0)
        if all(abs((candidate - d).total_seconds()) >= min_gap.total_seconds() for d in occupied):
            return candidate
    return None


def find_next_slot() -> datetime:
    """Find the next available slot within the next LOOKAHEAD_DAYS."""
    windows = _parse_windows()
    if not windows:
        raise RuntimeError("PUBLISH_WINDOWS is empty or invalid")

    tz = _tz()
    today = datetime.now(tz)

    for day_offset in range(LOOKAHEAD_DAYS):
        day = today + timedelta(days=day_offset)
        occupied = _scheduled_local_times(day)
        for win_start, win_end in windows:
            picked = _try_pick_in_window(day, win_start, win_end, occupied)
            if picked is not None:
                return picked
    raise RuntimeError(
        f"No free slot in the next {LOOKAHEAD_DAYS} days. "
        "Try widening PUBLISH_WINDOWS or raising MAX_POSTS_PER_WINDOW."
    )


def schedule_post(post_id: str) -> datetime:
    """Assign the next available slot to a post; update DB; return local datetime."""
    slot_local = find_next_slot()
    posts_bank.update_post(
        post_id,
        status="SCHEDULED",
        scheduled_publish_at=_to_utc_iso(slot_local),
    )
    log.info("Post %s scheduled for %s (%s)", post_id, slot_local.isoformat(), TIMEZONE)
    return slot_local


def format_local(dt_local: datetime) -> str:
    """Human-friendly local time string."""
    return dt_local.strftime("%a %d %b %Y — %H:%M")
