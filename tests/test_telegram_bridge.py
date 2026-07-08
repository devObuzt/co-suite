from __future__ import annotations

import json

from scripts.software_company import telegram_bridge
from scripts.software_company.telegram_bridge import (
    extract_owner_notes,
    extract_topic_rows,
    format_note,
    known_update_ids,
    latest_owner_review,
    note_filename,
    topic_id_for,
    topic_name_for_thread,
)


def test_extract_topic_rows_returns_unique_chat_thread_pairs() -> None:
    updates = [
        {
            "message": {
                "chat": {"id": -100123, "title": "OneShare Software Company"},
                "message_thread_id": 11,
                "text": "product",
            }
        },
        {
            "message": {
                "chat": {"id": -100123, "title": "OneShare Software Company"},
                "message_thread_id": 11,
                "text": "second product message",
            }
        },
        {
            "message": {
                "chat": {"id": -100123, "title": "OneShare Software Company"},
                "message_thread_id": 12,
                "text": "qa",
            }
        },
    ]

    rows = extract_topic_rows(updates)

    assert rows == [
        {
            "chat_id": "-100123",
            "topic_id": "11",
            "chat_title": "OneShare Software Company",
            "sample_text": "product",
        },
        {
            "chat_id": "-100123",
            "topic_id": "12",
            "chat_title": "OneShare Software Company",
            "sample_text": "qa",
        },
    ]


def test_topic_id_for_accepts_direct_env_key(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOPIC_QA", "77")

    assert topic_id_for("qa") == 77


def test_topic_id_for_accepts_raw_env_key(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOPIC_CUSTOM", "88")

    assert topic_id_for("TELEGRAM_TOPIC_CUSTOM") == 88


def test_latest_owner_review_matches_autopilot_reports(monkeypatch, tmp_path) -> None:
    review_dir = tmp_path / "owner review"
    review_dir.mkdir()
    old_report = review_dir / "2026-06-08_19-13-26_cosuite-cycle-owner-review.md"
    new_report = review_dir / "2026-06-09_18-13-18_cosuite-autopilot-cycle-owner-review.md"
    other_report = review_dir / "2026-06-10_10-00-00_other-autopilot-cycle-owner-review.md"

    old_report.write_text("old", encoding="utf-8")
    new_report.write_text("new", encoding="utf-8")
    other_report.write_text("other", encoding="utf-8")

    monkeypatch.setattr(telegram_bridge, "OWNER_REVIEW_DIR", review_dir)

    assert latest_owner_review("cosuite") == new_report


def _owner_update(update_id: int, text: str, **overrides) -> dict:
    message = {
        "message_id": update_id * 10,
        "date": 1751980000,
        "chat": {"id": -100123, "title": "OneShare Software Company"},
        "from": {"is_bot": False, "username": "wisam"},
        "text": text,
    }
    message.update(overrides)
    return {"update_id": update_id, "message": message}


def test_extract_owner_notes_keeps_human_messages_only() -> None:
    updates = [
        _owner_update(1, "fix the login flow"),
        _owner_update(2, "bot report", **{"from": {"is_bot": True, "username": "companybot"}}),
        _owner_update(3, "/topic_qa"),
        _owner_update(4, "other chat", chat={"id": -999}),
        _owner_update(5, ""),
    ]

    notes = extract_owner_notes(updates, "-100123")

    assert [note["update_id"] for note in notes] == [1]
    assert notes[0]["text"] == "fix the login flow"
    assert notes[0]["sender"] == "wisam"


def test_extract_owner_notes_captures_reply_context() -> None:
    updates = [
        _owner_update(
            7,
            "approve option 2",
            message_thread_id=44,
            reply_to_message={"text": "Owner Review ready\n\nOption 1 or 2?"},
        )
    ]

    notes = extract_owner_notes(updates, "-100123")

    assert notes[0]["thread_id"] == "44"
    assert notes[0]["reply_excerpt"].startswith("Owner Review ready")


def test_format_note_and_filename_round_trip() -> None:
    note = {
        "update_id": 9,
        "message_id": 90,
        "date": 1751980000,
        "thread_id": "",
        "sender": "wisam",
        "text": "please redeploy",
        "reply_excerpt": "Deploy report",
    }

    rendered = format_note(note)

    assert "please redeploy" in rendered
    assert "> Deploy report" in rendered
    assert "Status: new" in rendered
    assert note_filename(note).endswith("_update-9.md")


def test_topic_name_for_thread_resolves_env_mapping(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOPIC_QA", "55")

    assert topic_name_for_thread("55") == "qa"
    assert topic_name_for_thread("") == "main-chat"
    assert topic_name_for_thread("321").startswith("thread-")


def test_known_update_ids_scans_inbox_and_processed(monkeypatch, tmp_path) -> None:
    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    inbox.mkdir()
    processed.mkdir()
    (inbox / "2026-07-08_10-00-00_update-3.md").write_text("a", encoding="utf-8")
    (processed / "2026-07-07_09-00-00_update-2.md").write_text("b", encoding="utf-8")

    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_INBOX", inbox)
    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_PROCESSED", processed)

    assert known_update_ids() == {2, 3}


def test_fetch_notes_writes_files_and_advances_offset(monkeypatch, tmp_path) -> None:
    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    state_path = tmp_path / "state.json"

    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_DIR", tmp_path)
    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_INBOX", inbox)
    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_PROCESSED", processed)
    monkeypatch.setattr(telegram_bridge, "OWNER_FEEDBACK_STATE", state_path)
    monkeypatch.setenv("TELEGRAM_COMPANY_CHAT_ID", "-100123")

    captured: dict = {}

    def fake_get_updates(limit: int, offset=None):
        captured["offset"] = offset
        return [_owner_update(12, "add dark mode")]

    monkeypatch.setattr(telegram_bridge, "get_updates", fake_get_updates)

    assert telegram_bridge.fetch_notes(limit=100, dry_run=False) == 0
    assert captured["offset"] is None

    files = list(inbox.glob("*_update-12.md"))
    assert len(files) == 1
    assert "add dark mode" in files[0].read_text(encoding="utf-8")
    assert json.loads(state_path.read_text(encoding="utf-8"))["next_offset"] == 13

    # Second run resumes from the stored offset and dedupes by update id.
    monkeypatch.setattr(telegram_bridge, "get_updates", lambda limit, offset=None: [_owner_update(12, "add dark mode")])
    assert telegram_bridge.fetch_notes(limit=100, dry_run=False) == 0
    assert len(list(inbox.glob("*_update-12.md"))) == 1
