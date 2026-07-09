"""Meta Ads interest matching — measures social demand for a suite's audience.

Queries the Marketing API targeting search (``search?type=adinterest``) with the
app access token: how many of the suite's audience interests exist as Meta Ads
targeting interests, and how large their combined audience is. Interests must be
English — the search does not match Arabic/Hebrew queries.
"""

import asyncio
import logging
from typing import Any

import httpx

from ..core.config import settings
from ..core.external_calls import external_call

log = logging.getLogger("cosuite.meta_interests")

GRAPH = "https://graph.facebook.com/v22.0"
MAX_TERMS = 10
_CONCURRENCY = 5


def _app_token() -> str:
    app_id = getattr(settings, "meta_app_id", "") or ""
    app_secret = getattr(settings, "meta_app_secret", "") or ""
    if not app_id or not app_secret:
        return ""
    return f"{app_id}|{app_secret}"


async def _search_interest(client: httpx.AsyncClient, token: str, term: str) -> dict[str, Any] | None:
    async with external_call("meta_ads", "interest_search", term=term[:60]) as call:
        response = await client.get(
            f"{GRAPH}/search",
            params={"type": "adinterest", "q": term, "limit": 3, "access_token": token},
        )
        call.note(status_code=response.status_code)
        response.raise_for_status()
        items = response.json().get("data") or []
        if not items:
            return None
        best = items[0]
        size = best.get("audience_size_upper_bound") or best.get("audience_size") or 0
        return {
            "query": term,
            "name": str(best.get("name") or term),
            "audience_size": int(size) if isinstance(size, (int, float)) else 0,
        }


def _demand_level(matched: int, checked: int, audience_size: int) -> str:
    if checked <= 0:
        return "UNKNOWN"
    ratio = matched / checked
    if matched >= 5 or (ratio >= 0.6 and audience_size >= 50_000_000):
        return "HIGH"
    if matched >= 3 or audience_size >= 5_000_000:
        return "MEDIUM"
    if matched >= 1:
        return "LOW"
    return "LOW"


async def match_meta_interests(terms: list[str]) -> dict[str, Any]:
    """Match English interest terms against Meta Ads targeting interests.

    Returns a snapshot dict; ``level`` is UNKNOWN when the API is unavailable so
    callers can fall back to an estimate.
    """
    cleaned = [str(term).strip() for term in terms if str(term).strip()][:MAX_TERMS]
    snapshot: dict[str, Any] = {
        "provider": "meta_ads_interest_search",
        "checked": len(cleaned),
        "matched": 0,
        "audience_size": 0,
        "matches": [],
        "level": "UNKNOWN",
    }
    token = _app_token()
    if not cleaned or not token:
        snapshot["internal_warning"] = "meta app credentials missing" if not token else "no interest terms"
        return snapshot

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def guarded(client: httpx.AsyncClient, term: str) -> dict[str, Any] | None | Exception:
        async with semaphore:
            try:
                return await _search_interest(client, token, term)
            except Exception as exc:  # per-term failure must not sink the batch
                return exc

    async with httpx.AsyncClient(timeout=12) as client:
        results = await asyncio.gather(*[guarded(client, term) for term in cleaned])

    errors = [result for result in results if isinstance(result, Exception)]
    matches = [result for result in results if isinstance(result, dict)]
    if errors and not matches:
        snapshot["internal_warning"] = f"{type(errors[0]).__name__}: {errors[0]}"
        log.error("Meta interest search failed for all %s terms: %s", len(cleaned), errors[0])
        return snapshot

    matches.sort(key=lambda item: item.get("audience_size") or 0, reverse=True)
    audience_size = sum(item.get("audience_size") or 0 for item in matches)
    snapshot["matched"] = len(matches)
    snapshot["audience_size"] = audience_size
    snapshot["matches"] = matches[:8]
    snapshot["level"] = _demand_level(len(matches), len(cleaned), audience_size)
    return snapshot
