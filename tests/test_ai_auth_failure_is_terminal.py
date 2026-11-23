"""A rejected API key is permanent. Everything here used to call it temporary.

Found 2026-11-23: OPENAI_API_KEY and ANTHROPIC_API_KEY were both rejected with
401. What the owner saw was "Strategy generation failed. Please try again." —
so he tried again, and again, for a condition no retry can fix. The marketing
plan job of 2026-11-12 did the same thing by itself: three retries over ninety
minutes, then "Generation worker stopped updating this job before it completed."

Three layers each turned a permanent failure into a transient one:
  - llm_client raised a bare `raise_for_status()`, throwing the provider's own
    explanation away (the Anthropic path had already been fixed for this).
  - retry_fields_for_error retried it, because only rate-limit wording was
    treated as special.
  - safe_generation_error rewrote any key/token error as "Please retry."
"""
import pytest

from api.core.ai_errors import AiProviderError


class TestAiProviderError:
    def test_str_keeps_the_shape_other_code_already_matches(self):
        """`classify_provider_limit` and friends sniff this text — don't move it."""
        exc = AiProviderError("Anthropic", 529, "overloaded")
        assert str(exc) == "Anthropic 529: overloaded"

    def test_it_is_still_a_runtimeerror(self):
        """Call sites that catch RuntimeError must keep catching it."""
        assert isinstance(AiProviderError("OpenAI", 401, "nope"), RuntimeError)

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures_are_recognised(self, status):
        assert AiProviderError("OpenAI", status, "bad key").is_auth_failure

    @pytest.mark.parametrize("status", [429, 500, 529, 400])
    def test_everything_else_is_not_an_auth_failure(self, status):
        assert not AiProviderError("OpenAI", status, "x").is_auth_failure

    def test_a_missing_detail_still_produces_a_usable_message(self):
        assert "no detail" in str(AiProviderError("OpenAI", 401, ""))


class TestRetriesStopOnAuthFailure:
    def _job(self, retry_count=0, max_retries=3):
        from api.models.generation_job import GenerationJob

        job = GenerationJob()
        job.id = "j1"
        job.suite_id = "s1"
        job.retry_count = retry_count
        job.max_retries = max_retries
        return job

    def test_an_auth_failure_fails_the_job_on_the_first_attempt(self):
        from api.services.durable_generation_queue import retry_fields_for_error
        from api.models.generation_job import GenerationJobStatus

        fields = retry_fields_for_error(
            self._job(), AiProviderError("OpenAI", 401, "Incorrect API key provided")
        )
        assert fields["status"] == GenerationJobStatus.failed
        assert fields["stage"] == "failed"
        assert "finished_at" in fields
        # The 2026-11-12 job burned three retries and ninety minutes on this.
        assert fields.get("retry_count", 0) == 0

    def test_an_ordinary_failure_still_retries(self):
        """The unchanged path — don't make every failure terminal."""
        from api.services.durable_generation_queue import retry_fields_for_error
        from api.models.generation_job import GenerationJobStatus

        fields = retry_fields_for_error(self._job(), RuntimeError("connection reset"))
        assert fields["status"] == GenerationJobStatus.retrying
        assert fields["retry_count"] == 1

    def test_a_rate_limit_still_retries(self):
        from api.services.durable_generation_queue import retry_fields_for_error
        from api.models.generation_job import GenerationJobStatus

        fields = retry_fields_for_error(self._job(), AiProviderError("OpenAI", 429, "rate limit"))
        assert fields["status"] == GenerationJobStatus.retrying


class TestWhatTheUserIsTold:
    def test_an_auth_failure_does_not_tell_the_user_to_retry(self):
        from api.services.generation_jobs import safe_generation_error

        message = safe_generation_error("OpenAI 401: Incorrect API key provided: sk-proj-abc")
        assert "retry" not in message.lower()
        assert "again" not in message.lower()

    def test_it_says_plainly_that_the_key_was_rejected(self):
        from api.services.generation_jobs import safe_generation_error

        message = safe_generation_error("OpenAI 401: Incorrect API key provided: sk-proj-abc")
        assert "key" in message.lower()
        assert "rejected" in message.lower()

    def test_the_key_itself_never_reaches_the_user(self):
        """The reason this branch masked everything in the first place."""
        from api.services.generation_jobs import safe_generation_error

        message = safe_generation_error("OpenAI 401: Incorrect API key provided: sk-proj-abcdef")
        assert "sk-proj" not in message
        assert "abcdef" not in message

    def test_a_rate_limit_message_is_unchanged(self):
        from api.services.generation_jobs import safe_generation_error

        assert "rate limited" in safe_generation_error("OpenAI 429: rate limit reached")


class TestBothClientsRaiseIt:
    """The OpenAI path threw the provider's explanation away.

    `resp.raise_for_status()` produces "401 Client Error: Unauthorized for
    url: ..." and nothing else — so the actual reason ("Incorrect API key
    provided") never reached a log or a human. The Anthropic path had already
    been fixed for exactly this on 2026-09-28, when an out-of-credit account
    read as a broken request for days.
    """

    def _response(self, status, payload):
        class R:
            status_code = status
            text = str(payload)

            def json(self):
                return payload

        return R()

    def test_openai_401_carries_the_providers_own_message(self, monkeypatch):
        import api.core.llm_client as llm

        monkeypatch.setattr(llm.settings, "openai_api_key", "sk-proj-whatever")
        monkeypatch.setattr(
            llm.requests,
            "post",
            lambda *a, **k: self._response(
                401, {"error": {"message": "Incorrect API key provided: sk-proj-abc"}}
            ),
        )

        with pytest.raises(AiProviderError) as caught:
            llm._call_openai_sync("gpt-5.1", 16, [{"role": "user", "content": "hi"}])

        assert caught.value.status_code == 401
        assert caught.value.is_auth_failure
        assert "Incorrect API key provided" in str(caught.value)

    def test_openai_success_is_untouched(self, monkeypatch):
        import api.core.llm_client as llm

        monkeypatch.setattr(llm.settings, "openai_api_key", "sk-proj-whatever")
        monkeypatch.setattr(
            llm.requests, "post", lambda *a, **k: self._response(200, {"output_text": "hello"})
        )
        assert llm._call_openai_sync("gpt-5.1", 16, [{"role": "user", "content": "hi"}]) == "hello"

    def test_anthropic_401_raises_the_same_type(self, monkeypatch):
        import api.core.ai_client as ai

        monkeypatch.setattr(ai.settings, "anthropic_api_key", "sk-ant-whatever")
        monkeypatch.setattr(
            ai.requests,
            "post",
            lambda *a, **k: self._response(401, {"error": {"message": "invalid x-api-key"}}),
        )

        with pytest.raises(AiProviderError) as caught:
            ai._call_sync("claude-sonnet-4-6", 16, [{"role": "user", "content": "hi"}])

        assert caught.value.status_code == 401
        assert caught.value.is_auth_failure


class TestWhatTheApiReturns:
    """The route said "Please try again" for a key that will never be accepted."""

    def test_an_auth_failure_becomes_a_distinct_http_error(self):
        from api.routers.onboarding import http_error_for_ai_failure

        exc = http_error_for_ai_failure(AiProviderError("OpenAI", 401, "Incorrect API key"))
        assert exc.status_code == 502
        assert "again" not in exc.detail.lower()
        assert "key" in exc.detail.lower()

    def test_an_overloaded_provider_still_says_try_again(self):
        from api.routers.onboarding import http_error_for_ai_failure

        exc = http_error_for_ai_failure(AiProviderError("Anthropic", 529, "overloaded"))
        assert exc.status_code == 503
        assert "again" in exc.detail.lower()

    def test_an_unknown_failure_keeps_the_old_message(self):
        from api.routers.onboarding import http_error_for_ai_failure

        exc = http_error_for_ai_failure(RuntimeError("something odd"))
        assert exc.status_code == 500
        assert "again" in exc.detail.lower()
