import json
import logging
from datetime import datetime, timezone

import pytest

from api.core import observability
from api.core.observability import JsonLogFormatter, generation_job_alert_message, notify_generation_job_alert
from api.models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType


def test_json_log_formatter_includes_structured_job_fields(monkeypatch):
    monkeypatch.setattr(observability.settings, "environment", "test")
    record = logging.LogRecord(
        name="api.tests",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Provider limited",
        args=(),
        exc_info=None,
    )
    record.event = "generation_job_provider_limit"
    record.job_id = "job_1"
    record.suite_id = "suite_1"
    record.provider = "openai"
    record.model = "gpt-image-1"
    record.attempt = 2
    record.status = "waiting_provider_limit"
    record.safe_error_class = "provider_limit"

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "WARNING"
    assert payload["event"] == "generation_job_provider_limit"
    assert payload["job_id"] == "job_1"
    assert payload["provider"] == "openai"
    assert payload["safe_error_class"] == "provider_limit"
    assert payload["environment"] == "test"


def test_generation_job_alert_message_omits_raw_error_and_includes_routing(monkeypatch):
    monkeypatch.setattr(observability.settings, "environment", "production")
    job = GenerationJob(
        id="job_2",
        suite_id="suite_2",
        type=GenerationJobType.content_generation,
        status=GenerationJobStatus.waiting_provider_limit,
        provider="google",
        model="veo-3.1-fast-generate-preview",
        retry_count=1,
        max_retries=3,
        estimated_wait_seconds=120,
        error="Google 429 quota exhausted with secret token sk-live-hidden",
        created_at=datetime.now(timezone.utc),
    )

    message = generation_job_alert_message(job, "provider_limit")

    assert "OneShare incident: provider_limit" in message
    assert "Environment: production" in message
    assert "Job: job_2" in message
    assert "Provider: google" in message
    assert "Model: veo-3.1-fast-generate-preview" in message
    assert "Error class: provider_limit" in message
    assert "sk-live-hidden" not in message


@pytest.mark.asyncio
async def test_provider_limit_alert_respects_min_wait_threshold(monkeypatch):
    sent = False

    async def fake_send(message: str) -> bool:
        nonlocal sent
        sent = True
        return True

    monkeypatch.setattr(observability, "send_telegram_alert", fake_send)
    monkeypatch.setattr(observability.settings, "provider_limit_alert_min_wait_seconds", 120)
    job = GenerationJob(
        id="job_3",
        suite_id="suite_3",
        type=GenerationJobType.content_generation,
        status=GenerationJobStatus.waiting_provider_limit,
        estimated_wait_seconds=30,
    )

    result = await notify_generation_job_alert(job, "provider_limit")

    assert result is False
    assert sent is False


@pytest.mark.asyncio
async def test_failed_job_alert_uses_telegram_when_enabled(monkeypatch):
    messages = []

    async def fake_send(message: str) -> bool:
        messages.append(message)
        return True

    monkeypatch.setattr(observability, "send_telegram_alert", fake_send)
    monkeypatch.setattr(observability.settings, "failed_job_alerts_enabled", True)
    job = GenerationJob(
        id="job_4",
        suite_id="suite_4",
        type=GenerationJobType.product_bulk_generate_all,
        status=GenerationJobStatus.failed,
        provider="anthropic",
        model="claude-sonnet-4-6",
        error="timeout",
    )

    result = await notify_generation_job_alert(job, "failed_job")

    assert result is True
    assert len(messages) == 1
    assert "OneShare incident: failed_job" in messages[0]


def test_json_log_formatter_includes_arbitrary_extra_fields(monkeypatch):
    # The formatter used a fixed allowlist, silently dropping structured
    # fields like the montage fallback `reason`.
    monkeypatch.setattr(observability.settings, "environment", "test")
    logger = logging.getLogger("api.tests.log_event")
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = CaptureHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        observability.log_event(
            logger,
            logging.WARNING,
            "Video montage pipeline fell back.",
            event="video_montage_fallback",
            job_id="job_9",
            suite_id="suite_9",
            reason="Could not download the source video: timeout",
            skipped=None,
        )
    finally:
        logger.removeHandler(handler)

    assert len(records) == 1
    payload = json.loads(JsonLogFormatter().format(records[0]))
    assert payload["event"] == "video_montage_fallback"
    assert payload["job_id"] == "job_9"
    assert payload["reason"] == "Could not download the source video: timeout"
    assert "skipped" not in payload
    assert payload["message"] == "Video montage pipeline fell back."
