"""Cached market-research snapshot for a (country, language).

Reuses the existing competitor research and the brand's audience notes, cached
in ``research_cache`` (period=None) and reused across suites of the same
country+language. Never raises — returns an empty-but-shaped dict on failure.
"""
import logging

from .research_cache import get_cached, upsert_cached
from .strategy_generator import research_competitors

log = logging.getLogger(__name__)

_EMPTY = {"audience_behavior": "", "local_trends": [], "competitors_summary": ""}


async def get_market_research(db, *, country: str, language: str, brand: dict) -> dict:
    try:
        cached = await get_cached(db, kind="market", country=country, language=language, period=None)
        if cached is not None:
            return cached
        competitors = [c for c in (brand.get("competitors") or []) if isinstance(c, str)][:4]
        summary = ""
        if competitors:
            snippets = await research_competitors(competitors, str(brand.get("name") or ""))
            summary = " | ".join(f"{k}: {v[:200]}" for k, v in snippets.items() if v)
        data = {
            "audience_behavior": str(brand.get("audience_notes") or brand.get("target_audience") or ""),
            "local_trends": [],
            "competitors_summary": summary,
        }
        if db is not None:
            await upsert_cached(
                db, kind="market", country=country, language=language,
                period=None, data=data, source="hybrid", ttl_days=90,
            )
        return data
    except Exception:
        log.exception("market research failed for %s/%s", country, language)
        return dict(_EMPTY)
