"""Google Ads OAuth and read-only reporting helpers."""
import httpx

from ..core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ADS_API = "https://googleads.googleapis.com/v20"
GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


def _clean_customer_id(customer_id: str) -> str:
    return (customer_id or "").replace("-", "").strip()


def _redirect_uri() -> str:
    return f"{settings.frontend_url}/connections/google/callback"


def get_google_ads_oauth_url(suite_id: str) -> str:
    if not settings.google_ads_client_id:
        raise RuntimeError("GOOGLE_ADS_CLIENT_ID is missing")

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


def _headers(access_token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.google_ads_developer_token,
        "Content-Type": "application/json",
    }
    login_customer_id = _clean_customer_id(settings.google_ads_login_customer_id)
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id
    return headers


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

    return [
        {"id": name.replace("customers/", ""), "resource_name": name}
        for name in resource_names
    ]


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
