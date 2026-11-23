"""One error type for "the AI provider refused", carrying why.

Both clients used to raise a bare string, so the only way to tell a rate limit
from a dead API key was to grep the message — and a 401 matched none of the
patterns anyone had written, so it was retried like a blip. `status_code` makes
that a question with an answer.

`__str__` keeps the exact `"Provider 401: detail"` shape the previous
RuntimeError produced, because `classify_provider_limit` and
`safe_generation_error` read the stored text, not the exception.
"""
from __future__ import annotations


class AiProviderError(RuntimeError):
    def __init__(self, provider: str, status_code: int, detail: str = "") -> None:
        self.provider = provider
        self.status_code = int(status_code)
        self.detail = detail or "no detail returned"
        super().__init__(f"{provider} {self.status_code}: {self.detail}")

    @property
    def is_auth_failure(self) -> bool:
        """A rejected or revoked credential. No amount of retrying fixes it."""
        return self.status_code in (401, 403)
