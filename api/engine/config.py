"""Centralized configuration loader."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
# override=True so values in .env always win over any (possibly empty) shell vars
load_dotenv(PROJECT_ROOT / ".env", override=True)


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value or ""


# API keys
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", required=True)
GOOGLE_API_KEY = _env("GOOGLE_API_KEY", required=True)
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

# Cloudflare R2 (optional — required only for social publishing)
R2_ACCOUNT_ID = _env("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = _env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _env("R2_SECRET_ACCESS_KEY")
R2_API_TOKEN = _env("R2_API_TOKEN")
R2_BUCKET = _env("R2_BUCKET", "connec-media")
R2_PUBLIC_URL_PREFIX = _env("R2_PUBLIC_URL_PREFIX")  # e.g. https://pub-XXXX.r2.dev

# ElevenLabs TTS (for Arabic voiceover)
ELEVENLABS_API_KEY = _env("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _env("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL = _env("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_SPEED = float(_env("ELEVENLABS_SPEED", "1.0"))

# Meta (Facebook + Instagram)
META_APP_ID = _env("META_APP_ID")
META_APP_SECRET = _env("META_APP_SECRET")
META_USER_TOKEN_SHORT_LIVED = _env("META_USER_TOKEN_SHORT_LIVED")
META_USER_TOKEN_LONG_LIVED = _env("META_USER_TOKEN_LONG_LIVED")
META_PAGE_ID = _env("META_PAGE_ID")
META_PAGE_NAME = _env("META_PAGE_NAME")
META_PAGE_ACCESS_TOKEN = _env("META_PAGE_ACCESS_TOKEN")
META_IG_USER_ID = _env("META_IG_USER_ID")

# Scheduling
PUBLISH_WINDOWS = _env("PUBLISH_WINDOWS", "11:00-13:00,15:00-17:00,19:00-22:00")
PUBLISH_MIN_GAP_MINUTES = int(_env("PUBLISH_MIN_GAP_MINUTES", "90"))
TIMEZONE = _env("TIMEZONE", "Asia/Amman")

# Budget & quotas
DAILY_VIDEO_BUDGET_USD = float(_env("DAILY_VIDEO_BUDGET_USD", "5.0"))
POSTS_PER_DAY = int(_env("POSTS_PER_DAY", "5"))
VIDEOS_PER_DAY = int(_env("VIDEOS_PER_DAY", "2"))
CAROUSELS_PER_DAY = int(_env("CAROUSELS_PER_DAY", "2"))

# Models
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-opus-4-7")
IMAGE_MODEL = _env("IMAGE_MODEL", "gemini-2.5-flash-image")
VIDEO_MODEL = _env("VIDEO_MODEL", _env("GOOGLE_VIDEO_MODEL", "veo-3.1-fast-generate-preview"))

# Paths
DATA_DIR = PROJECT_ROOT / "data"
PENDING_DIR = DATA_DIR / "pending"
APPROVED_DIR = DATA_DIR / "approved"
PUBLISHED_DIR = DATA_DIR / "published"
REJECTED_DIR = DATA_DIR / "rejected"
DB_PATH = DATA_DIR / "posts.db"
LOGS_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = ENGINE_DIR / "assets"
CONFIG_DIR = ENGINE_DIR / "config"

for d in (PENDING_DIR, APPROVED_DIR, PUBLISHED_DIR, REJECTED_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Load brand and prompts
with open(CONFIG_DIR / "brand.json", "r", encoding="utf-8") as f:
    BRAND = json.load(f)

with open(CONFIG_DIR / "prompts.json", "r", encoding="utf-8") as f:
    PROMPTS = json.load(f)


def brand_summary_for_claude() -> str:
    """Short brand description fed to Claude as system context."""
    divs = "\n".join(
        f"- {d['name_ar']} ({key}) — لون: {d['color_name']} {d['color']}"
        for key, d in BRAND["divisions"].items()
    )
    aud = BRAND.get("audience", {})
    audience_block = ""
    if aud:
        audience_block = (
            f"\n\nالجمهور المستهدف: {aud.get('primary', '')}\n"
            f"الموقع: {aud.get('location', '')}\n"
            f"اللهجة: {aud.get('dialect', '')}\n"
            f"ملاحظات النبرة: {aud.get('voice_notes', '')}"
        )
    return (
        f"الاسم: {BRAND['name_ar']} ({BRAND['name']})\n"
        f"الشعار: {BRAND['tagline_ar']}\n"
        f"الوصف: {BRAND['description_ar']}\n\n"
        f"الأقسام:\n{divs}\n\n"
        f"نبرة الصوت: {BRAND['tone']['personality']}"
        f"{audience_block}"
    )
