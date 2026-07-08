"""Google Ads OAuth and read-only reporting helpers."""
from typing import Any

import httpx

from ..core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_ADS_API = "https://googleads.googleapis.com/v24"
GOOGLE_ADS_SCOPE = " ".join([
    "https://www.googleapis.com/auth/adwords",
    "openid",
    "email",
    "profile",
])

LANGUAGE_CONSTANTS = {
    "ar": "languageConstants/1019",
    "arabic": "languageConstants/1019",
    "he": "languageConstants/1027",
    "hebrew": "languageConstants/1027",
    "en": "languageConstants/1000",
    "english": "languageConstants/1000",
}

GEO_TARGET_CONSTANTS = {
    "israel": "geoTargetConstants/2376",
    "إسرائيل": "geoTargetConstants/2376",
    "اسرائيل": "geoTargetConstants/2376",
    "ישראל": "geoTargetConstants/2376",
    "il": "geoTargetConstants/2376",
    "palestine": "geoTargetConstants/2275",
    "فلسطين": "geoTargetConstants/2275",
    "פלסטין": "geoTargetConstants/2275",
    "ps": "geoTargetConstants/2275",
    "united states": "geoTargetConstants/2840",
    "usa": "geoTargetConstants/2840",
    "us": "geoTargetConstants/2840",
    "jordan": "geoTargetConstants/2400",
    "jo": "geoTargetConstants/2400",
    "saudi arabia": "geoTargetConstants/2682",
    "saudi": "geoTargetConstants/2682",
    "uae": "geoTargetConstants/2784",
    "united arab emirates": "geoTargetConstants/2784",
    "united kingdom": "geoTargetConstants/2826",
    "uk": "geoTargetConstants/2826",
    "gb": "geoTargetConstants/2826",
    "britain": "geoTargetConstants/2826",
}


def _clean_customer_id(customer_id: str) -> str:
    return (customer_id or "").replace("-", "").strip()


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _micros_to_unit(value: Any) -> float:
    return round(_int_value(value) / 1_000_000, 2)


def language_constant(language: str | None) -> str:
    marker = str(language or "").strip().casefold()
    return LANGUAGE_CONSTANTS.get(marker) or LANGUAGE_CONSTANTS.get(marker[:2]) or LANGUAGE_CONSTANTS["en"]


def _location_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("name", "label", "country", "city", "location", "audience_location"):
            if value.get(key):
                parts.append(_location_text(value.get(key)))
        for key in ("countries", "cities", "regions"):
            nested = value.get(key)
            if isinstance(nested, list):
                parts.extend(_location_text(item) for item in nested[:4])
            elif nested:
                parts.append(_location_text(nested))
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, list):
        return " ".join(part for part in (_location_text(item) for item in value[:4]) if part).strip()
    return str(value or "").strip()


def geo_target_constants(country_or_location: Any) -> list[str]:
    text = _location_text(country_or_location)
    if not text:
        return []
    if text.startswith("geoTargetConstants/"):
        return [text]
    if text.isdigit():
        return [f"geoTargetConstants/{text}"]
    lowered = text.casefold()
    matches = []
    for key, resource_name in GEO_TARGET_CONSTANTS.items():
        marker = key.casefold()
        if len(marker) <= 2:
            found = any(token == marker for token in lowered.replace("/", " ").replace(",", " ").split())
        else:
            found = marker in lowered
        if found:
            matches.append(resource_name)
    return list(dict.fromkeys(matches))


def normalize_keyword_idea(raw: dict[str, Any], source: str = "google_suggested") -> dict[str, Any]:
    metrics = raw.get("keywordIdeaMetrics") or raw.get("keyword_idea_metrics") or {}
    monthly = metrics.get("monthlySearchVolumes") or metrics.get("monthly_search_volumes") or []
    return {
        "keyword": str(raw.get("text") or raw.get("keyword") or "").strip(),
        "source": source,
        "average_monthly_searches": _int_value(metrics.get("avgMonthlySearches") or metrics.get("avg_monthly_searches")),
        "competition": str(metrics.get("competition") or "UNKNOWN").upper(),
        "competition_index": _int_value(metrics.get("competitionIndex") or metrics.get("competition_index")),
        "low_top_of_page_bid": _micros_to_unit(metrics.get("lowTopOfPageBidMicros") or metrics.get("low_top_of_page_bid_micros")),
        "high_top_of_page_bid": _micros_to_unit(metrics.get("highTopOfPageBidMicros") or metrics.get("high_top_of_page_bid_micros")),
        "monthly_search_volumes": [
            {
                "year": _int_value(item.get("year")),
                "month": str(item.get("month") or "").upper(),
                "monthly_searches": _int_value(item.get("monthlySearches") or item.get("monthly_searches")),
            }
            for item in monthly
            if isinstance(item, dict)
        ],
    }


def build_keyword_planner_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    analyzed = [item for item in items if item.get("keyword")]
    count = len(analyzed)
    total_searches = sum(_int_value(item.get("average_monthly_searches")) for item in analyzed)
    average_searches = round(total_searches / count) if count else 0
    competition_values = [
        _int_value(item.get("competition_index"))
        for item in analyzed
        if item.get("competition_index") is not None
    ]
    average_competition = round(sum(competition_values) / len(competition_values)) if competition_values else 0
    competition_level = "HIGH" if average_competition >= 67 else "MEDIUM" if average_competition >= 34 else "LOW" if count else "UNKNOWN"
    demand_level = "HIGH" if average_searches >= 1000 else "MEDIUM" if average_searches >= 100 else "LOW" if count else "UNKNOWN"
    pressure_score = round((min(100, average_competition) + min(100, average_searches / 20)) / 2) if count else 0
    return {
        "analyzed_keywords": count,
        "average_monthly_searches": average_searches,
        "total_monthly_searches": total_searches,
        "average_competition_index": average_competition,
        "competition_level": competition_level,
        "demand_level": demand_level,
        "market_pressure_score": pressure_score,
    }


def _keyword_idea_request(keywords: list[str], language: str | None, location: str | None, page_url: str | None = None) -> dict[str, Any]:
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        text = str(keyword or "").strip()
        marker = text.casefold()
        if not text or marker in seen:
            continue
        seen.add(marker)
        unique_keywords.append(text)
        if len(unique_keywords) >= 20:
            break
    body: dict[str, Any] = {
        "language": language_constant(language),
        "geoTargetConstants": geo_target_constants(location),
        "includeAdultKeywords": False,
        "keywordPlanNetwork": "GOOGLE_SEARCH",
        "pageSize": 50,
    }
    url = str(page_url or "").strip()
    if unique_keywords and url:
        body["keywordAndUrlSeed"] = {"keywords": unique_keywords, "url": url}
    elif unique_keywords:
        body["keywordSeed"] = {"keywords": unique_keywords}
    elif url:
        body["urlSeed"] = {"url": url}
    else:
        raise ValueError("At least one keyword or website URL is required for Keyword Planner.")
    return body


def _google_ads_error_detail(payload: dict[str, Any] | None, fallback: str = "Google Ads request failed") -> str:
    error = (payload or {}).get("error") if isinstance(payload, dict) else {}
    message = str((error or {}).get("message") or fallback).strip()
    details: list[str] = []
    for detail in (error or {}).get("details") or []:
        for item in detail.get("errors") or []:
            code = item.get("errorCode") or item.get("error_code") or {}
            code_text = next((f"{key}: {value}" for key, value in code.items() if value), "")
            field_path = ".".join(
                str(part.get("fieldName") or part.get("field_name") or "")
                for part in (item.get("location") or {}).get("fieldPathElements", [])
                if part.get("fieldName") or part.get("field_name")
            )
            item_message = str(item.get("message") or "").strip()
            parts = [part for part in (code_text, field_path, item_message) if part]
            if parts:
                details.append(" | ".join(parts))
    if details:
        return f"{message} Details: " + "; ".join(details[:3])
    return message


def _should_retry_without_login_customer(detail: str) -> bool:
    if not _clean_customer_id(settings.google_ads_login_customer_id):
        return False
    marker = str(detail or "").casefold()
    return (
        "user_permission_denied" in marker
        or "doesn't have permission" in marker
        or "does not have permission" in marker
    )


async def _post_keyword_ideas(
    client: httpx.AsyncClient,
    customer_id: str,
    access_token: str,
    body: dict[str, Any],
    *,
    include_login_customer: bool = True,
) -> httpx.Response:
    return await client.post(
        f"{GOOGLE_ADS_API}/customers/{_clean_customer_id(customer_id)}:generateKeywordIdeas",
        headers=_headers(access_token, customer_id, include_login_customer=include_login_customer),
        json=body,
    )


async def fetch_keyword_planner_ideas(
    customer_id: str,
    refresh_token: str,
    keywords: list[str],
    language: str | None,
    location: str | None,
    page_url: str | None = None,
) -> dict[str, Any]:
    if not customer_id or not refresh_token:
        return {"keyword_metrics": [], "suggested_keywords": [], "summary": build_keyword_planner_summary([]), "warning": "Google Ads account is not connected."}
    try:
        access_token = await refresh_google_ads_access_token(refresh_token)
        body = _keyword_idea_request(keywords, language, location, page_url)
        retried_without_login_customer = False
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await _post_keyword_ideas(client, customer_id, access_token, body)
            if resp.status_code >= 400:
                try:
                    detail = _google_ads_error_detail(resp.json(), "Google Ads Keyword Planner request failed")
                except Exception:
                    detail = resp.text or "Google Ads Keyword Planner request failed"
                if _should_retry_without_login_customer(detail):
                    retried_without_login_customer = True
                    resp = await _post_keyword_ideas(
                        client,
                        customer_id,
                        access_token,
                        body,
                        include_login_customer=False,
                    )
                    if resp.status_code >= 400:
                        try:
                            retry_detail = _google_ads_error_detail(resp.json(), "Google Ads Keyword Planner request failed")
                        except Exception:
                            retry_detail = resp.text or "Google Ads Keyword Planner request failed"
                        raise RuntimeError(
                            "Retried without login-customer-id after manager permission error. "
                            + retry_detail
                        )
                else:
                    raise RuntimeError(detail)
        if resp.status_code >= 400:
            try:
                detail = _google_ads_error_detail(resp.json(), "Google Ads Keyword Planner request failed")
            except Exception:
                detail = resp.text or "Google Ads Keyword Planner request failed"
            raise RuntimeError(detail)
        payload = resp.json()
        original_markers = {str(keyword or "").strip().casefold() for keyword in keywords if str(keyword or "").strip()}
        metrics = []
        suggestions = []
        for raw in payload.get("results") or []:
            if not isinstance(raw, dict):
                continue
            source = "existing_keyword" if str(raw.get("text") or "").strip().casefold() in original_markers else "google_suggested"
            item = normalize_keyword_idea(raw, source=source)
            if not item["keyword"]:
                continue
            metrics.append(item)
            if source == "google_suggested":
                suggestions.append(item)
        summary = build_keyword_planner_summary(metrics)
        summary["suggested_keywords"] = len(suggestions)
        result = {
            "keyword_metrics": metrics,
            "suggested_keywords": suggestions[:30],
            "summary": summary,
            "request": {
                "language": body.get("language"),
                "geo_target_constants": body.get("geoTargetConstants") or [],
                "keyword_count": len(body.get("keywordSeed", {}).get("keywords") or body.get("keywordAndUrlSeed", {}).get("keywords") or []),
                "retried_without_login_customer": retried_without_login_customer,
            },
        }
        if not metrics:
            result["warning"] = "No keyword ideas or historical metrics were returned by Google Ads Keyword Planner for the selected country, language, and keywords."
        return result
    except Exception as e:
        return {"keyword_metrics": [], "suggested_keywords": [], "summary": build_keyword_planner_summary([]), "warning": str(e)}


def _redirect_uri() -> str:
    return f"{settings.frontend_url}/connections/google/callback"


def _missing_google_ads_config() -> list[str]:
    required = {
        "GOOGLE_ADS_CLIENT_ID": settings.google_ads_client_id,
        "GOOGLE_ADS_CLIENT_SECRET": settings.google_ads_client_secret,
        "GOOGLE_ADS_DEVELOPER_TOKEN": settings.google_ads_developer_token,
    }
    return [name for name, value in required.items() if not value]


def get_google_ads_oauth_url(suite_id: str) -> str:
    missing = _missing_google_ads_config()
    if missing:
        raise RuntimeError("Missing Google Ads configuration: " + ", ".join(missing))
    if not settings.frontend_url.startswith("https://"):
        raise RuntimeError("FRONTEND_URL must be the public HTTPS web domain for Google Ads OAuth.")

    from urllib.parse import urlencode

    params = urlencode({
        "client_id": settings.google_ads_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_ADS_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": suite_id,
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


async def exchange_google_ads_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_google_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code >= 400:
            return {}
        return resp.json()


async def refresh_google_ads_access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def _headers(access_token: str, customer_id: str | None = None, *, include_login_customer: bool = True) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.google_ads_developer_token,
        "Content-Type": "application/json",
    }
    login_customer_id = _clean_customer_id(settings.google_ads_login_customer_id)
    if include_login_customer and login_customer_id and login_customer_id != _clean_customer_id(customer_id or ""):
        headers["login-customer-id"] = login_customer_id
    return headers


async def _customer_details(customer_id: str, access_token: str) -> dict:
    rows = await _search(customer_id, access_token, """
        SELECT
          customer.id,
          customer.descriptive_name,
          customer.currency_code,
          customer.time_zone
        FROM customer
        LIMIT 1
    """)
    if not rows:
        return {}
    customer = rows[0].get("customer") or {}
    return {
        "name": customer.get("descriptiveName") or customer.get("descriptive_name"),
        "currency_code": customer.get("currencyCode") or customer.get("currency_code"),
        "time_zone": customer.get("timeZone") or customer.get("time_zone"),
    }


async def list_accessible_customers(access_token: str) -> list[dict]:
    if not settings.google_ads_developer_token:
        raise RuntimeError("GOOGLE_ADS_DEVELOPER_TOKEN is missing")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GOOGLE_ADS_API}/customers:listAccessibleCustomers",
            headers=_headers(access_token),
        )
        resp.raise_for_status()
        resource_names = resp.json().get("resourceNames", [])

    customers = []
    for name in resource_names:
        customer_id = name.replace("customers/", "")
        customer = {"id": customer_id, "resource_name": name}
        try:
            customer.update(await _customer_details(customer_id, access_token))
        except Exception:
            pass
        customers.append(customer)
    return customers


async def _search(customer_id: str, access_token: str, query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{GOOGLE_ADS_API}/customers/{_clean_customer_id(customer_id)}/googleAds:searchStream",
            headers=_headers(access_token),
            json={"query": query},
        )
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", {}).get("message", "Google Ads request failed")
            except Exception:
                detail = resp.text or "Google Ads request failed"
            raise RuntimeError(detail)
        batches = resp.json()

    rows: list[dict] = []
    for batch in batches:
        rows.extend(batch.get("results", []))
    return rows


def _metrics(row: dict) -> dict:
    metrics = row.get("metrics") or {}
    cost_micros = int(metrics.get("costMicros") or 0)
    return {
        "impressions": int(metrics.get("impressions") or 0),
        "clicks": int(metrics.get("clicks") or 0),
        "cost": round(cost_micros / 1_000_000, 2),
        "conversions": float(metrics.get("conversions") or 0),
        "ctr": float(metrics.get("ctr") or 0),
        "average_cpc": round(int(metrics.get("averageCpc") or 0) / 1_000_000, 2),
    }


async def fetch_google_ads_campaigns(customer_id: str, refresh_token: str) -> dict:
    if not customer_id or not refresh_token:
        return {"campaigns": [], "warning": "Google Ads account is not connected."}

    try:
        access_token = await refresh_google_ads_access_token(refresh_token)
        campaign_rows = await _search(customer_id, access_token, """
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.advertising_channel_type,
              campaign.start_date,
              campaign.end_date,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.ctr,
              metrics.average_cpc
            FROM campaign
            WHERE campaign.status = ENABLED
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.cost_micros DESC
            LIMIT 25
        """)

        ad_group_rows = await _search(customer_id, access_token, """
            SELECT
              campaign.id,
              ad_group.id,
              ad_group.name,
              ad_group.status,
              ad_group.type,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.ctr,
              metrics.average_cpc
            FROM ad_group
            WHERE campaign.status = ENABLED
              AND ad_group.status = ENABLED
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.cost_micros DESC
            LIMIT 100
        """)

        ad_rows = await _search(customer_id, access_token, """
            SELECT
              campaign.id,
              ad_group.id,
              ad_group_ad.ad.id,
              ad_group_ad.ad.name,
              ad_group_ad.status,
              ad_group_ad.ad.type,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.ctr,
              metrics.average_cpc
            FROM ad_group_ad
            WHERE campaign.status = ENABLED
              AND ad_group.status = ENABLED
              AND ad_group_ad.status = ENABLED
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.cost_micros DESC
            LIMIT 150
        """)
    except Exception as e:
        return {"campaigns": [], "warning": str(e)}

    ads_by_group: dict[str, list[dict]] = {}
    for row in ad_rows:
        ad_group = row.get("adGroup") or {}
        ad = (row.get("adGroupAd") or {}).get("ad") or {}
        group_id = str(ad_group.get("id") or "")
        ads_by_group.setdefault(group_id, []).append({
            "id": str(ad.get("id") or ""),
            "name": ad.get("name") or f"Ad {ad.get('id', '')}",
            "status": (row.get("adGroupAd") or {}).get("status"),
            "type": ad.get("type"),
            "metrics": _metrics(row),
        })

    groups_by_campaign: dict[str, list[dict]] = {}
    for row in ad_group_rows:
        campaign = row.get("campaign") or {}
        ad_group = row.get("adGroup") or {}
        group_id = str(ad_group.get("id") or "")
        campaign_id = str(campaign.get("id") or "")
        groups_by_campaign.setdefault(campaign_id, []).append({
            "id": group_id,
            "name": ad_group.get("name") or f"Ad group {group_id}",
            "status": ad_group.get("status"),
            "type": ad_group.get("type"),
            "metrics": _metrics(row),
            "ads": ads_by_group.get(group_id, []),
        })

    campaigns = []
    for row in campaign_rows:
        campaign = row.get("campaign") or {}
        campaign_id = str(campaign.get("id") or "")
        campaigns.append({
            "id": campaign_id,
            "name": campaign.get("name") or f"Campaign {campaign_id}",
            "status": campaign.get("status"),
            "channel_type": campaign.get("advertisingChannelType"),
            "start_date": campaign.get("startDate"),
            "end_date": campaign.get("endDate"),
            "metrics": _metrics(row),
            "ad_groups": groups_by_campaign.get(campaign_id, []),
        })

    return {"campaigns": campaigns}
