from __future__ import annotations

from scripts.software_company.telegram_bridge import extract_topic_rows, topic_id_for


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
