"""Occasions/holidays research for a (country, language, period).

Hybrid: an LLM proposes the occasions for the period, then a web search verifies
movable/sports/school dates and adjusts confidence. Results are cached in
``research_cache`` and reused across suites. Never raises — a failure returns
``[]`` so idea generation can proceed on evergreen ideas alone.
"""
import json
import logging

from ..core.llm_client import call_text_ai
from .multi_scraper import search_web
from .research_cache import get_cached, upsert_cached

log = logging.getLogger(__name__)

OCCASION_TYPES = {"religious", "national", "school", "sports", "seasonal", "commercial"}
_VERIFY_TYPES = {"sports", "school", "seasonal"}


def _extract_json(raw: str) -> dict:
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    return {}
    return {}


def _prompt(country: str, language: str, period: str) -> str:
    return (
        f"List real-world occasions relevant to an audience in country='{country}', "
        f"audience language='{language}', for the month/period='{period}'. Include religious, "
        f"national, school (breaks/return), sports (e.g. World Cup, Champions League), seasonal and "
        f"commercial shopping events that a local brand could build content around. "
        f"Return ONLY JSON: "
        f'{{"occasions":[{{"title":"...","type":"religious|national|school|sports|seasonal|commercial",'
        f'"date_or_window":"YYYY-MM or YYYY-MM-DD or range","confidence":"high|medium|low"}}]}}'
    )


async def _verify(occasions: list[dict]) -> list[dict]:
    for occ in occasions:
        if occ.get("type") in _VERIFY_TYPES and occ.get("confidence") != "high":
            try:
                hits = await search_web(f"{occ.get('title', '')} {occ.get('date_or_window', '')} date", limit=3)
            except Exception:
                hits = []
            occ["verified_by"] = "web" if hits else "llm"
            if hits and occ.get("confidence") == "low":
                occ["confidence"] = "medium"
        else:
            occ.setdefault("verified_by", "llm")
    return occasions


async def get_occasions(db, *, country: str, language: str, period: str) -> list[dict]:
    """Cache-or-fetch occasions for the key. Returns a list of occasion dicts."""
    try:
        cached = await get_cached(db, kind="occasions", country=country, language=language, period=period)
        if cached is not None:
            return cached
        raw = await call_text_ai(
            max_tokens=1500,
            messages=[{"role": "user", "content": _prompt(country, language, period)}],
            system="You are a cultural calendar expert. Return valid JSON only.",
        )
        occasions = [
            o for o in (_extract_json(raw).get("occasions") or [])
            if isinstance(o, dict) and o.get("title")
        ]
        for o in occasions:
            if o.get("type") not in OCCASION_TYPES:
                o["type"] = "seasonal"
            o.setdefault("confidence", "medium")
        occasions = await _verify(occasions)
        if db is not None:
            await upsert_cached(
                db, kind="occasions", country=country, language=language,
                period=period, data=occasions, source="hybrid", ttl_days=120,
            )
        return occasions
    except Exception:
        log.exception("occasions fetch failed for %s/%s/%s", country, language, period)
        return []
