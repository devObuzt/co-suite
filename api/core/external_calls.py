"""Central instrumentation for outbound calls to external providers.

Every request to an external service (AI models, Meta Graph, R2, fal/VEED,
ElevenLabs, SerpAPI, scraping, Telegram, ...) should run inside
``external_call(...)`` so one clear, admin-readable JSON log line is emitted
per logical operation with provider, operation, success/failure, duration and
HTTP status. Example log lines::

    External call OK: veed-fal background_removal (42.3s)
    External call FAILED: meta publish_photo (1.2s) - HTTPStatusError: 400 ...

Usage (sync or async — same object supports both)::

    async with external_call("meta", "publish_photo", suite_id=suite.id) as call:
        resp = await client.post(url, ...)
        call.note(status_code=resp.status_code)

    with external_call("anthropic", "messages", model=model) as call:
        resp = requests.post(...)
        call.note(status_code=resp.status_code)

For call sites that report failure via return values instead of exceptions,
mark the failure explicitly::

    call.fail("provider returned no output_url")
"""
import logging
import re
import time
from typing import Any, Optional

log = logging.getLogger("api.external")

_SECRET_PATTERN = re.compile(
    r"(access_token|api_key|apikey|key|token|secret|authorization)=[^&\s\"']+",
    re.IGNORECASE,
)


def redact_secrets(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    return _SECRET_PATTERN.sub(r"\1=***", str(text))


class ExternalCall:
    """Times one logical outbound operation and logs a single summary line."""

    def __init__(self, provider: str, operation: str, **context: Any) -> None:
        self.provider = provider
        self.operation = operation
        self.context = {k: v for k, v in context.items() if v is not None}
        self._started: Optional[float] = None
        self._error: Optional[str] = None
        self._finished = False

    def note(self, **fields: Any) -> None:
        """Attach extra fields mid-call (status_code, request_id, polls, ...)."""
        self.context.update({k: v for k, v in fields.items() if v is not None})

    def fail(self, error: Any) -> None:
        """Mark the call failed when the provider signals failure without raising."""
        self._error = str(error) if error else "unknown error"

    def __enter__(self) -> "ExternalCall":
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._finish(exc)
        return False

    async def __aenter__(self) -> "ExternalCall":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._finish(exc)
        return False

    @property
    def elapsed_seconds(self) -> float:
        if self._started is None:
            return 0.0
        return round(time.monotonic() - self._started, 2)

    def _finish(self, exc: Optional[BaseException]) -> None:
        if self._finished:  # tolerate double-exit
            return
        self._finished = True

        duration_seconds = self.elapsed_seconds
        error = self._error
        status_code = self.context.pop("status_code", None)
        if exc is not None:
            error = f"{type(exc).__name__}: {exc}"
            response = getattr(exc, "response", None)
            if status_code is None and response is not None:
                status_code = getattr(response, "status_code", None)

        ok = error is None
        fields = {
            "event": "external_call",
            "provider": self.provider,
            "operation": self.operation,
            "ok": ok,
            "duration_seconds": duration_seconds,
            "duration_ms": int(duration_seconds * 1000),
        }
        if status_code is not None:
            fields["status_code"] = status_code
        if error is not None:
            fields["error"] = redact_secrets(error)
        for key, value in self.context.items():
            if key not in fields and value is not None:
                fields[key] = redact_secrets(value) if isinstance(value, str) else value

        if ok:
            message = f"External call OK: {self.provider} {self.operation} ({duration_seconds}s)"
            level = logging.INFO
        else:
            message = (
                f"External call FAILED: {self.provider} {self.operation}"
                f" ({duration_seconds}s) - {fields.get('error')}"
            )
            level = logging.ERROR

        try:
            log.log(level, message, extra=fields)
        except Exception:  # logging must never break the actual call
            pass


def external_call(provider: str, operation: str, **context: Any) -> ExternalCall:
    return ExternalCall(provider, operation, **context)
