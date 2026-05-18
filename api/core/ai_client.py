"""Anthropic API client using requests (not httpx) — fixes Railway connectivity."""
import asyncio
import json
import logging
from functools import partial
from typing import Any

import requests

from .config import settings

log = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def _call_sync(model: str, max_tokens: int, messages: list, system: str = "") -> dict[str, Any]:
    """Synchronous Anthropic API call via requests."""
    headers = {
        "x-api-key": settings.anthropic_api_key.strip(),
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


async def call_claude(model: str, max_tokens: int, messages: list, system: str = "") -> str:
    """Async wrapper — runs requests in a thread, returns the text of the first content block."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, partial(_call_sync, model, max_tokens, messages, system)
    )
    return result["content"][0]["text"]


def call_claude_sync(model: str, max_tokens: int, system: str, messages: list) -> str:
    """Sync version for use in non-async contexts (content_generator)."""
    result = _call_sync(model, max_tokens, messages, system)
    return result["content"][0]["text"]
