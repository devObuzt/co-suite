#!/usr/bin/env python3
"""Telegram bridge for the reusable software-company operating system.

The bridge never stores secrets. It reads `TELEGRAM_BOT_TOKEN` and chat/topic
configuration from environment variables at runtime.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import error, parse, request


REPO_ROOT = Path(__file__).resolve().parents[2]
OWNER_REVIEW_DIR = REPO_ROOT / "docs" / "software-company" / "owner review"
OWNER_FEEDBACK_DIR = REPO_ROOT / "docs" / "software-company" / "owner-feedback"
OWNER_FEEDBACK_INBOX = OWNER_FEEDBACK_DIR / "inbox"
OWNER_FEEDBACK_PROCESSED = OWNER_FEEDBACK_DIR / "processed"
OWNER_FEEDBACK_STATE = OWNER_FEEDBACK_DIR / "state.json"

TOPIC_ENV_KEYS = {
    "owner-review": "TELEGRAM_TOPIC_OWNER_REVIEW",
    "project-management": "TELEGRAM_TOPIC_PM",
    "product": "TELEGRAM_TOPIC_PRODUCT",
    "architecture": "TELEGRAM_TOPIC_ARCHITECTURE",
    "design": "TELEGRAM_TOPIC_DESIGN",
    "developers-manager": "TELEGRAM_TOPIC_DEVELOPERS_MANAGER",
    "developers": "TELEGRAM_TOPIC_DEVELOPERS",
    "qa": "TELEGRAM_TOPIC_QA",
    "devops": "TELEGRAM_TOPIC_DEVOPS",
    "incidents": "TELEGRAM_TOPIC_INCIDENTS",
}


class TelegramConfigError(RuntimeError):
    """Raised when required Telegram environment variables are missing."""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value.strip() == "":
        raise TelegramConfigError(f"Missing environment variable: {name}")
    return value.strip()


def telegram_api_url(method: str) -> str:
    token = env("TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{method}"


def telegram_request(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(telegram_api_url(method), data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API {method} failed: {exc.code} {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Telegram API {method} failed: {exc.reason}") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API {method} returned not ok: {body}")
    return parsed


def get_updates(limit: int, offset: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    query = parse.urlencode(params)
    url = f"{telegram_api_url('getUpdates')}?{query}"
    try:
        with request.urlopen(url, timeout=20) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API getUpdates failed: {exc.code} {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Telegram API getUpdates failed: {exc.reason}") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API getUpdates returned not ok: {body}")
    return list(parsed.get("result", []))


def extract_topic_rows(updates: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        thread_id = str(message.get("message_thread_id", ""))
        text = str(message.get("text") or message.get("caption") or "").strip()
        title = str(chat.get("title") or chat.get("username") or "")

        if not chat_id:
            continue

        key = (chat_id, thread_id)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "chat_id": chat_id,
                "topic_id": thread_id or "(main chat)",
                "chat_title": title,
                "sample_text": text[:80],
            }
        )

    return rows


def print_updates(limit: int) -> int:
    rows = extract_topic_rows(get_updates(limit))
    if not rows:
        print(
            "No Telegram messages found. If Bot Privacy Mode is enabled, send a command "
            "inside each topic, for example /topic_owner_review, then rerun this command."
        )
        return 1

    print("Detected Telegram chats/topics:")
    for row in rows:
        print(
            "- "
            f"chat_id={row['chat_id']} "
            f"topic_id={row['topic_id']} "
            f"title={row['chat_title']!r} "
            f"sample={row['sample_text']!r}"
        )
    print("")
    print("Set TELEGRAM_COMPANY_CHAT_ID to the group chat_id.")
    print("Map each topic_id to the matching TELEGRAM_TOPIC_* variable.")
    return 0


def topic_id_for(topic: str | None) -> int | None:
    if not topic:
        return None
    env_key = TOPIC_ENV_KEYS.get(topic, topic)
    value = os.environ.get(env_key)
    if not value:
        raise TelegramConfigError(f"Missing environment variable for topic {topic}: {env_key}")
    return int(value)


def send_message(text: str, topic: str | None = None, dry_run: bool = False) -> int:
    # Telegram sendMessage hard limit is 4096 chars.
    if len(text) > 4000:
        text = text[:3900].rstrip() + "\n\n...trimmed for Telegram..."

    payload: dict[str, Any] = {
        "chat_id": env("TELEGRAM_COMPANY_CHAT_ID"),
        "text": text,
        "disable_web_page_preview": True,
    }

    thread_id = topic_id_for(topic)
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    if dry_run:
        safe_payload = dict(payload)
        safe_payload["chat_id"] = "<configured>"
        print(json.dumps(safe_payload, ensure_ascii=False, indent=2))
        return 0

    telegram_request("sendMessage", payload)
    print("Telegram message sent.")
    return 0


def latest_owner_review(project: str | None = None) -> Path:
    if not OWNER_REVIEW_DIR.exists():
        raise FileNotFoundError(f"Owner review directory not found: {OWNER_REVIEW_DIR}")

    pattern = f"*_{project}*.md" if project else "*.md"
    candidates = sorted(OWNER_REVIEW_DIR.glob(pattern), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No owner review markdown files found for pattern: {pattern}")
    return candidates[-1]


def compact_report(path: Path, max_chars: int = 3500) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 180].rstrip() + f"\n\n...trimmed for Telegram...\n\nLocal file: {path}"


def send_owner_review(project: str | None, dry_run: bool) -> int:
    path = latest_owner_review(project)
    message = f"Owner Review ready\n\n{compact_report(path)}\n\nLocal file: {path}"
    return send_message(message, topic="owner-review", dry_run=dry_run)


def topic_name_for_thread(thread_id: str) -> str:
    if not thread_id:
        return "main-chat"
    for name, env_key in TOPIC_ENV_KEYS.items():
        if os.environ.get(env_key, "").strip() == thread_id:
            return name
    return f"thread-{thread_id}"


def extract_owner_notes(updates: list[dict[str, Any]], chat_id: str) -> list[dict[str, Any]]:
    """Keep human-authored text messages from the company chat.

    Bot messages, other chats, empty messages, and slash commands (topic-setup
    noise like /topic_qa) are dropped.
    """
    notes: list[dict[str, Any]] = []
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}

        if str(chat.get("id", "")) != chat_id:
            continue
        if sender.get("is_bot"):
            continue

        text = str(message.get("text") or message.get("caption") or "").strip()
        if not text or text.startswith("/"):
            continue

        reply = message.get("reply_to_message") or {}
        reply_text = str(reply.get("text") or reply.get("caption") or "").strip()

        notes.append(
            {
                "update_id": int(update.get("update_id", 0)),
                "message_id": int(message.get("message_id", 0)),
                "date": int(message.get("date", 0)),
                "thread_id": str(message.get("message_thread_id") or ""),
                "sender": str(sender.get("username") or sender.get("first_name") or "owner"),
                "text": text,
                "reply_excerpt": reply_text[:300],
            }
        )
    return notes


def note_filename(note: dict[str, Any]) -> str:
    stamp = datetime.fromtimestamp(note["date"]).strftime("%Y-%m-%d_%H-%M-%S")
    return f"{stamp}_update-{note['update_id']}.md"


def format_note(note: dict[str, Any]) -> str:
    stamp = datetime.fromtimestamp(note["date"]).strftime("%Y-%m-%d %H:%M:%S")
    topic = topic_name_for_thread(note["thread_id"])
    lines = [
        f"# Owner note {note['update_id']}",
        "",
        f"- Date: {stamp}",
        f"- Topic: {topic}",
        f"- From: {note['sender']}",
        "- Status: new",
    ]
    if note["reply_excerpt"]:
        lines += ["", "## In reply to", "", "> " + note["reply_excerpt"].replace("\n", "\n> ")]
    lines += ["", "## Note", "", note["text"], ""]
    return "\n".join(lines)


def load_feedback_state() -> dict[str, Any]:
    if OWNER_FEEDBACK_STATE.exists():
        try:
            return dict(json.loads(OWNER_FEEDBACK_STATE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_feedback_state(state: dict[str, Any]) -> None:
    OWNER_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_FEEDBACK_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def known_update_ids() -> set[int]:
    ids: set[int] = set()
    for directory in (OWNER_FEEDBACK_INBOX, OWNER_FEEDBACK_PROCESSED):
        if not directory.exists():
            continue
        for path in directory.glob("*_update-*.md"):
            try:
                ids.add(int(path.stem.rsplit("update-", 1)[1]))
            except (IndexError, ValueError):
                continue
    return ids


def fetch_notes(limit: int, dry_run: bool) -> int:
    chat_id = env("TELEGRAM_COMPANY_CHAT_ID")
    state = load_feedback_state()
    offset = state.get("next_offset")

    updates = get_updates(limit, offset=offset)
    notes = extract_owner_notes(updates, chat_id)
    known = known_update_ids()
    new_notes = [note for note in notes if note["update_id"] not in known]

    if dry_run:
        print(json.dumps(new_notes, ensure_ascii=False, indent=2))
        return 0

    if updates:
        state["next_offset"] = max(int(u.get("update_id", 0)) for u in updates) + 1
        save_feedback_state(state)

    if not new_notes:
        print("No new owner notes.")
        return 0

    OWNER_FEEDBACK_INBOX.mkdir(parents=True, exist_ok=True)
    for note in new_notes:
        path = OWNER_FEEDBACK_INBOX / note_filename(note)
        path.write_text(format_note(note), encoding="utf-8")
        print(f"=== {path} ===")
        print(format_note(note))

    print(f"Saved {len(new_notes)} new owner note(s) to {OWNER_FEEDBACK_INBOX}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    updates = subparsers.add_parser("updates", help="List recent chat and topic IDs from getUpdates")
    updates.add_argument("--limit", type=int, default=100)

    send = subparsers.add_parser("send", help="Send a text message to the company group/topic")
    send.add_argument("text", nargs="?", default=None)
    send.add_argument("--file", default=None, help="Read the message text from a file instead")
    send.add_argument("--topic", choices=sorted(TOPIC_ENV_KEYS), default=None)
    send.add_argument("--dry-run", action="store_true")

    review = subparsers.add_parser("send-owner-review", help="Send the latest owner-review report")
    review.add_argument("--project", default=None)
    review.add_argument("--dry-run", action="store_true")

    fetch = subparsers.add_parser(
        "fetch-notes",
        help="Pull owner replies/notes from Telegram into docs/software-company/owner-feedback/inbox",
    )
    fetch.add_argument("--limit", type=int, default=100)
    fetch.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "updates":
            return print_updates(args.limit)
        if args.command == "send":
            if args.file:
                text = Path(args.file).read_text(encoding="utf-8").strip()
            elif args.text is not None:
                text = args.text
            else:
                print("Provide message text or --file", file=sys.stderr)
                return 2
            return send_message(text, topic=args.topic, dry_run=args.dry_run)
        if args.command == "send-owner-review":
            return send_owner_review(args.project, dry_run=args.dry_run)
        if args.command == "fetch-notes":
            return fetch_notes(args.limit, dry_run=args.dry_run)
    except TelegramConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
