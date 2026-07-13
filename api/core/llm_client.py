"""Provider-neutral text AI client for onboarding and strategy tasks."""
import asyncio
from functools import partial
from typing import Any

import requests

from .ai_client import call_claude
from .config import settings
from .external_calls import external_call

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _provider_or_default(provider: str | None = None) -> str:
    selected = (provider or settings.ai_text_provider or "anthropic").strip().lower()
    return selected if selected in {"anthropic", "openai"} else "anthropic"


def _openai_extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _call_openai_sync(
    model: str,
    max_tokens: int,
    messages: list,
    system: str = "",
    timeout: int = 120,
) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")

    input_items = []
    if system:
        input_items.append({"role": "system", "content": system})
    input_items.extend(messages)

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "max_output_tokens": max_tokens,
    }

    with external_call("openai", "responses", model=model) as call:
        resp = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=timeout)
        call.note(status_code=resp.status_code)
        resp.raise_for_status()
        text = _openai_extract_text(resp.json())
        if not text:
            raise RuntimeError("OpenAI returned no text output")
        return text


async def call_text_ai(
    *,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int,
    messages: list,
    system: str = "",
    timeout: int = 120,
) -> str:
    selected = _provider_or_default(provider)
    if selected == "openai":
        selected_model = model or settings.openai_text_model
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(_call_openai_sync, selected_model, max_tokens, messages, system, timeout),
        )

    selected_model = model or settings.anthropic_text_model
    return await call_claude(
        model=selected_model,
        max_tokens=max_tokens,
        messages=messages,
        system=system,
        timeout=timeout,
    )
