from datetime import datetime, timezone

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
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
    )

    payload = serialize_job(job)

    assert payload["job_id"] == "job_1"
    assert payload["suite_id"] == "suite_1"
    assert payload["status"] == "waiting_provider_limit"
    assert payload["stage"] == "provider_limit"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-image-1"
    assert payload["retry_count"] == 1
    assert payload["estimated_wait_seconds"] == 120


def test_provider_limit_classifier_detects_quota_errors():
    payload = classify_provider_limit(Exception("OpenAI 429 rate limit exceeded"))

    assert payload is not None
    assert payload["provider"] == "openai"
    assert payload["wait_seconds"] == 120
