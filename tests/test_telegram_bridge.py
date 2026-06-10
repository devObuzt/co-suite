from __future__ import annotations

from scripts.software_company import telegram_bridge
from scripts.software_company.telegram_bridge import extract_topic_rows, latest_owner_review, topic_id_for


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
