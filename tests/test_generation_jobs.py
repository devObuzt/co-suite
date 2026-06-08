from datetime import datetime, timedelta, timezone

from api.models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
from api.services.generation_jobs import classify_provider_limit, serialize_job


def test_generation_job_status_values_are_stable():
    assert GenerationJobStatus.queued.value == "queued"
    assert GenerationJobStatus.waiting_capacity.value == "waiting_capacity"
    assert GenerationJobStatus.waiting_provider_limit.value == "waiting_provider_limit"
    assert GenerationJobStatus.running.value == "running"
    assert GenerationJobStatus.retrying.value == "retrying"
    assert GenerationJobStatus.completed.value == "completed"
    assert GenerationJobStatus.failed.value == "failed"
    assert GenerationJobStatus.cancelled.value == "cancelled"
    assert GenerationJobStatus.timeout.value == "timeout"


def test_generation_job_type_values_are_stable():
    assert GenerationJobType.content_generation.value == "content_generation"
    assert GenerationJobType.content_regeneration.value == "content_regeneration"


def test_serialize_job_returns_frontend_contract():
    now = datetime.now(timezone.utc)
    job = GenerationJob(
        id="job_1",
        suite_id="suite_1",
        type=GenerationJobType.content_generation,
        status=GenerationJobStatus.waiting_provider_limit,
        stage="provider_limit",
        message="Waiting for OpenAI rate limit reset.",
        progress=35,
        provider="openai",
        model="gpt-image-1",
        retry_count=1,
        estimated_wait_seconds=120,
        created_at=now - timedelta(seconds=90),
        updated_at=now - timedelta(seconds=15),
        error="Traceback: API key sk-live-secret failed with raw provider payload",
    )

    payload = serialize_job(job, now=now)

    assert payload["job_id"] == "job_1"
    assert payload["suite_id"] == "suite_1"
    assert payload["status"] == "waiting_provider_limit"
    assert payload["stage"] == "provider_limit"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-image-1"
    assert payload["retry_count"] == 1
    assert payload["estimated_wait_seconds"] == 120
    assert payload["age_seconds"] == 90
    assert payload["last_update_age_seconds"] == 15
    assert payload["wait_state"]["state"] == "waiting_provider_limit"
    assert payload["is_active"] is True
    assert payload["is_stale"] is False
    assert payload["safe_error"] == "The AI provider could not complete this request. Please retry."
    assert "sk-live-secret" not in payload["safe_error"]


def test_serialize_job_marks_stale_background_task_states():
    now = datetime.now(timezone.utc)
    job = GenerationJob(
        id="job_2",
        suite_id="suite_1",
        type=GenerationJobType.content_generation,
        status=GenerationJobStatus.running,
        stage="media",
        progress=40,
        created_at=now - timedelta(minutes=40),
        updated_at=now - timedelta(minutes=31),
    )

    payload = serialize_job(job, now=now)

    assert payload["is_stale"] is True
    assert payload["stale_reason"] == "No job update has been recorded recently. Background task execution may have stopped."


def test_provider_limit_classifier_detects_quota_errors():
    payload = classify_provider_limit(Exception("OpenAI 429 rate limit exceeded"))

    assert payload is not None
    assert payload["provider"] == "openai"
    assert payload["wait_seconds"] == 120
