import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.generation_job import GenerationJob, GenerationJobStatus
from .config import settings


# Attributes every LogRecord carries by default (plus formatter-injected ones).
# Anything outside this set was attached via `extra=` and belongs in the JSON
# payload — a fixed allowlist silently dropped structured fields like `reason`.
_RESERVED_LOG_RECORD_KEYS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__
) | {"message", "asctime", "taskName"}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": settings.environment,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            if value is not None and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    if settings.log_format.lower() != "json":
        logging.basicConfig(level=logging.INFO)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={key: value for key, value in fields.items() if value is not None})


def _safe_error_class(error: Optional[str]) -> Optional[str]:
    if not error:
        return None
    text_value = str(error).lower()
    if any(token in text_value for token in ("rate limit", "429", "quota", "resource exhausted")):
        return "provider_limit"
    if any(token in text_value for token in ("api key", "credential", "unauthorized", "forbidden")):
        return "provider_auth"
    if "timeout" in text_value or "timed out" in text_value:
        return "provider_timeout"
    return "generation_failure"


def _telegram_recipients() -> list[str]:
    return [
        chat_id
        for chat_id in {settings.telegram_owner_chat_id, settings.telegram_admin_chat_id}
        if chat_id
    ]


async def send_telegram_alert(message: str) -> bool:
    if not settings.observability_alerts_enabled:
        return False
    if not settings.telegram_bot_token or not _telegram_recipients():
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=8) as client:
        for chat_id in _telegram_recipients():
            await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
    return True


def generation_job_alert_message(job: GenerationJob, incident_type: str) -> str:
    safe_error_class = _safe_error_class(job.error)
    return "\n".join(
        part
        for part in (
            f"OneShare incident: {incident_type}",
            f"Environment: {settings.environment}",
            f"Job: {job.id}",
            f"Suite: {job.suite_id}",
            f"Type: {job.type.value if job.type else 'unknown'}",
            f"Status: {job.status.value if job.status else 'unknown'}",
            f"Provider: {job.provider or 'unknown'}",
            f"Model: {job.model or 'unknown'}",
            f"Attempt: {job.retry_count}/{job.max_retries}",
            f"Wait seconds: {job.estimated_wait_seconds}" if job.estimated_wait_seconds else "",
            f"Error class: {safe_error_class}" if safe_error_class else "",
        )
        if part
    )


async def notify_generation_job_alert(job: Optional[GenerationJob], incident_type: str) -> bool:
    if job is None:
        return False
    if incident_type == "provider_limit" and int(job.estimated_wait_seconds or 0) < settings.provider_limit_alert_min_wait_seconds:
        return False
    if incident_type == "failed_job" and not settings.failed_job_alerts_enabled:
        return False
    return await send_telegram_alert(generation_job_alert_message(job, incident_type))


async def api_health_payload(db: Optional[AsyncSession] = None) -> dict:
    payload = {
        "status": "ok",
        "service": "api",
        "app": settings.app_name,
        "environment": settings.environment,
    }
    if db is None:
        return payload
    await db.execute(text("SELECT 1"))
    payload["database"] = "ok"
    return payload


async def worker_health_payload(db: AsyncSession) -> dict:
    await db.execute(text("SELECT 1"))
    active_statuses = {
        GenerationJobStatus.queued,
        GenerationJobStatus.waiting_capacity,
        GenerationJobStatus.waiting_provider_limit,
        GenerationJobStatus.running,
        GenerationJobStatus.retrying,
    }
    failed_result = await db.execute(
        select(func.count())
        .select_from(GenerationJob)
        .where(GenerationJob.status == GenerationJobStatus.failed)
    )
    active_result = await db.execute(
        select(func.count())
        .select_from(GenerationJob)
        .where(GenerationJob.status.in_(active_statuses))
    )
    return {
        "status": "ok",
        "service": "generation-worker",
        "environment": settings.environment,
        "database": "ok",
        "active_jobs": int(active_result.scalar() or 0),
        "failed_jobs": int(failed_result.scalar() or 0),
    }
