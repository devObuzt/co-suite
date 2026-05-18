"""Shared Anthropic client factory — forces HTTP/1.1 to fix Railway connectivity."""
import httpx
import anthropic
from .config import settings


def make_async_anthropic() -> anthropic.AsyncAnthropic:
    """Return an AsyncAnthropic client with HTTP/2 disabled (fixes Railway APIConnectionError)."""
    http_client = httpx.AsyncClient(http2=False)
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        http_client=http_client,
    )


def make_sync_anthropic() -> anthropic.Anthropic:
    """Return a sync Anthropic client with HTTP/2 disabled."""
    http_client = httpx.Client(http2=False)
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        http_client=http_client,
    )
