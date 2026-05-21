"""Meta Ad Library lookup for content inspiration."""
import json
from urllib.parse import quote_plus

import httpx

from ..core.config import settings

GRAPH = "https://graph.facebook.com/v22.0"

COUNTRY_CODES = {
    "israel": "IL",
    "ישראל": "IL",
    "فلسطين": "PS",
    "palestine": "PS",
    "united states": "US",
    "usa": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "france": "FR",
    "spain": "ES",
    "turkey": "TR",
}


def _token(connections: dict | None = None) -> str:
    page_token = ((connections or {}).get("facebook") or {}).get("page_access_token")
    if page_token:
        return page_token
    if settings.meta_app_id and settings.meta_app_secret:
        return f"{settings.meta_app_id}|{settings.meta_app_secret}"
    return ""


def _countries(brand: dict) -> list[str]:
    loc = brand.get("audience_location") or {}
    raw = loc.get("countries") or []
    codes = []
    for country in raw:
        normalized = str(country).strip().lower()
        code = COUNTRY_CODES.get(normalized)
        if code:
            codes.append(code)
    return codes[:3] or ["IL"]


def _search_term(suite_name: str, brand: dict) -> str:
    return (
        brand.get("name")
        or suite_name
        or brand.get("niche")
        or brand.get("industry")
        or ""
    ).strip()


def _library_url(term: str, countries: list[str]) -> str:
    country = countries[0] if countries else "IL"
    return (
        "https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={quote_plus(country)}"
        f"&q={quote_plus(term)}&search_type=keyword_unordered"
    )


async def fetch_meta_ads_inspiration(suite_name: str, brand: dict, connections: dict | None = None) -> dict:
    """Fetch active Meta ads from Ad Library using business context."""
    term = _search_term(suite_name, brand)
    countries = _countries(brand)
    library_url = _library_url(term, countries)

    if not term:
        return {"ads": [], "library_url": library_url, "warning": "Business name is missing."}

    access_token = _token(connections)
    if not access_token:
        return {"ads": [], "library_url": library_url, "warning": "Meta app credentials are missing."}

    params = {
        "access_token": access_token,
        "ad_active_status": "ACTIVE",
        "ad_reached_countries": json.dumps(countries),
        "ad_type": "ALL",
        "fields": ",".join([
            "id",
            "page_id",
            "page_name",
            "ad_snapshot_url",
            "ad_creative_bodies",
            "ad_creative_link_titles",
            "ad_creative_link_descriptions",
            "ad_delivery_start_time",
            "publisher_platforms",
        ]),
        "limit": 12,
        "search_terms": term,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{GRAPH}/ads_archive", params=params)
            if resp.status_code >= 400:
                return {
                    "ads": [],
                    "library_url": library_url,
                    "warning": resp.json().get("error", {}).get("message", "Meta Ad Library request failed."),
                }
            data = resp.json()
    except Exception as e:
        return {"ads": [], "library_url": library_url, "warning": str(e)}

    ads = []
    for item in data.get("data", []):
        bodies = item.get("ad_creative_bodies") or []
        titles = item.get("ad_creative_link_titles") or []
        descriptions = item.get("ad_creative_link_descriptions") or []
        ads.append({
            "id": item.get("id"),
            "page_id": item.get("page_id"),
            "page_name": item.get("page_name"),
            "body": bodies[0] if bodies else "",
            "title": titles[0] if titles else "",
            "description": descriptions[0] if descriptions else "",
            "snapshot_url": item.get("ad_snapshot_url"),
            "start_time": item.get("ad_delivery_start_time"),
            "platforms": item.get("publisher_platforms") or [],
        })

    return {"ads": ads, "library_url": library_url, "query": term, "countries": countries}
