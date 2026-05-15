"""SQLite-backed posts bank — tracks every post's lifecycle."""
import json
import sqlite3
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, PENDING_DIR, APPROVED_DIR, PUBLISHED_DIR, REJECTED_DIR


STATUSES = (
    "PENDING_VO",      # video idea awaiting voiceover-text approval
    "VO_APPROVED",     # voiceover approved, Veo 3 generation pending
    "PENDING",         # media generated, awaiting final approval on Telegram
    "APPROVED",
    "SCHEDULED",
    "REJECTED",
    "PUBLISHED",
    "PUBLISH_FAILED",
    "FAILED",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    division TEXT NOT NULL,
    goal TEXT NOT NULL,
    format TEXT NOT NULL,
    topic TEXT,
    caption TEXT,
    hashtags TEXT,
    image_prompt TEXT,
    video_prompt TEXT,
    aspect_ratio TEXT,
    folder TEXT NOT NULL,
    media_path TEXT,
    cost_usd REAL DEFAULT 0,
    telegram_message_id INTEGER,
    notes TEXT,
    scheduled_publish_at TEXT,
    published_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_created ON posts(created_at);
"""

# Additive migrations for DBs created before the columns existed.
# Run BEFORE any CREATE INDEX that references these columns.
_MIGRATIONS = [
    "ALTER TABLE posts ADD COLUMN scheduled_publish_at TEXT",
    "ALTER TABLE posts ADD COLUMN published_at TEXT",
]

# Indexes that depend on columns added in migrations:
_POST_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_scheduled ON posts(scheduled_publish_at)",
]


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        conn.executescript(SCHEMA)
        # Apply additive migrations idempotently (skip "duplicate column" errors)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        # Indexes that depend on migrated columns (run AFTER migrations)
        for stmt in _POST_MIGRATION_INDEXES:
            conn.execute(stmt)


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def new_post_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]


def create_pending_post(idea: dict, post_id: str | None = None) -> dict:
    """Create a new post entry in PENDING status with its folder."""
    post_id = post_id or new_post_id()
    folder = PENDING_DIR / post_id
    folder.mkdir(parents=True, exist_ok=True)

    record = {
        "id": post_id,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "PENDING",
        "division": idea.get("division", ""),
        "goal": idea.get("goal", ""),
        "format": idea.get("format", "image"),
        "topic": idea.get("topic", ""),
        "caption": idea.get("caption", ""),
        "hashtags": json.dumps(idea.get("hashtags", []), ensure_ascii=False),
        "image_prompt": idea.get("image_prompt", ""),
        "video_prompt": idea.get("video_prompt", ""),
        "aspect_ratio": idea.get("aspect_ratio", "1:1"),
        "folder": str(folder),
        "media_path": None,
        "cost_usd": 0,
        "telegram_message_id": None,
        "notes": None,
    }

    # Save the full idea as meta.json next to the media
    with open(folder / "meta.json", "w", encoding="utf-8") as f:
        json.dump(idea, f, ensure_ascii=False, indent=2)

    with _db() as conn:
        conn.execute(
            """INSERT INTO posts
               (id, created_at, updated_at, status, division, goal, format,
                topic, caption, hashtags, image_prompt, video_prompt,
                aspect_ratio, folder, media_path, cost_usd, telegram_message_id, notes)
               VALUES (:id, :created_at, :updated_at, :status, :division, :goal, :format,
                       :topic, :caption, :hashtags, :image_prompt, :video_prompt,
                       :aspect_ratio, :folder, :media_path, :cost_usd, :telegram_message_id, :notes)""",
            record,
        )
    return record


def update_post(post_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    placeholders = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = post_id
    with _db() as conn:
        conn.execute(f"UPDATE posts SET {placeholders} WHERE id = :id", fields)


def set_media_path(post_id: str, path: Path | str) -> None:
    update_post(post_id, media_path=str(path))


def set_media_paths(post_id: str, paths: list[Path] | list[str]) -> None:
    """For carousels — store a JSON array of paths in media_path."""
    update_post(post_id, media_path=json.dumps([str(p) for p in paths]))


def get_media_paths(post: dict) -> list[Path]:
    """Return all media paths for a post (single or carousel)."""
    raw = post.get("media_path")
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return [Path(p) for p in json.loads(raw)]
        except json.JSONDecodeError:
            return []
    return [Path(raw)]


def add_cost(post_id: str, usd: float) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE posts SET cost_usd = COALESCE(cost_usd,0) + ?, updated_at = ? WHERE id = ?",
            (usd, _now(), post_id),
        )


def get_post(post_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return dict(row) if row else None


def recent_topics(limit: int = 30) -> list[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT topic FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["topic"] for r in rows if r["topic"]]


def todays_video_cost() -> float:
    with _db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) AS total
               FROM posts
               WHERE format = 'video' AND date(created_at) = date('now')"""
        ).fetchone()
    return float(row["total"]) if row else 0.0


def _move_folder(post_id: str, target_root: Path) -> Path:
    post = get_post(post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")
    src = Path(post["folder"])
    dst = target_root / src.name
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
    update_post(post_id, folder=str(dst))
    # Also update media_path(s) if they were inside the old folder
    if post.get("media_path"):
        raw = post["media_path"]
        if raw.startswith("["):
            try:
                old_paths = json.loads(raw)
                new_paths = [str(dst / Path(p).name) for p in old_paths]
                update_post(post_id, media_path=json.dumps(new_paths))
            except json.JSONDecodeError:
                pass
        else:
            new_media = dst / Path(raw).name
            update_post(post_id, media_path=str(new_media))
    return dst


def approve(post_id: str) -> Path:
    dst = _move_folder(post_id, APPROVED_DIR)
    update_post(post_id, status="APPROVED")
    return dst


def reject(post_id: str, reason: str = "") -> Path:
    dst = _move_folder(post_id, REJECTED_DIR)
    update_post(post_id, status="REJECTED", notes=reason)
    return dst


def mark_published(post_id: str) -> Path:
    dst = _move_folder(post_id, PUBLISHED_DIR)
    update_post(post_id, status="PUBLISHED")
    return dst


def list_pending() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = 'PENDING' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def list_pending_vo() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = 'PENDING_VO' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def find_by_telegram_message_id(message_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM posts WHERE telegram_message_id = ?", (message_id,)
        ).fetchone()
    return dict(row) if row else None


def update_idea_field(post_id: str, key: str, value) -> None:
    """Mutate the idea JSON saved in meta.json (and mirror to relevant DB cols)."""
    post = get_post(post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")
    folder = Path(post["folder"])
    meta_path = folder / "meta.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            idea = json.load(f)
    else:
        idea = {}
    idea[key] = value
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(idea, f, ensure_ascii=False, indent=2)
    # Mirror common fields back into the posts table for visibility
    if key in {"caption", "image_prompt", "video_prompt", "topic"}:
        update_post(post_id, **{key: value})


def list_approved() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = 'APPROVED' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def list_scheduled() -> list[dict]:
    """Posts with a future scheduled_publish_at, in APPROVED/SCHEDULED status."""
    with _db() as conn:
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE status IN ('APPROVED','SCHEDULED')
                 AND scheduled_publish_at IS NOT NULL
               ORDER BY scheduled_publish_at"""
        ).fetchall()
    return [dict(r) for r in rows]


def list_due_for_publishing(now_iso: str) -> list[dict]:
    """Posts whose scheduled time is ≤ now and still APPROVED/SCHEDULED."""
    with _db() as conn:
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE status IN ('APPROVED','SCHEDULED')
                 AND scheduled_publish_at IS NOT NULL
                 AND scheduled_publish_at <= ?
               ORDER BY scheduled_publish_at""",
            (now_iso,),
        ).fetchall()
    return [dict(r) for r in rows]
