"""Meta Marketing API read helpers for connected ad accounts."""
import json

import httpx

GRAPH = "https://graph.facebook.com/v22.0"


def _ad_account_node(ad_account_id: str) -> str:
    return ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"


async def fetch_campaigns(ad_account_id: str, access_token: str, limit: int = 25) -> dict:
    """Read active campaigns with their ad sets, ads, and performance numbers."""
    if not ad_account_id or not access_token:
        return {"campaigns": [], "warning": "Meta Ads account is not connected."}

    insights_fields = "impressions,reach,clicks,spend,cpm,cpc,ctr,actions"
    fields = ",".join([
        "id",
        "name",
        "status",
        "effective_status",
        "objective",
        "buying_type",
        "created_time",
        "updated_time",
        f"insights.date_preset(maximum){{{insights_fields}}}",
        (
            "adsets.limit(25){"
            "id,name,status,effective_status,daily_budget,lifetime_budget,"
            "bid_strategy,optimization_goal,created_time,updated_time,"
            f"insights.date_preset(maximum){{{insights_fields}}},"
            "ads.limit(25){"
            "id,name,status,effective_status,created_time,updated_time,"
            "creative{id,name,object_story_spec,effective_object_story_id},"
            f"insights.date_preset(maximum){{{insights_fields}}}"
            "}"
            "}"
        ),
    ])
    filtering = json.dumps([
        {"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}
    ])

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{GRAPH}/{_ad_account_node(ad_account_id)}/campaigns",
                params={
                    "access_token": access_token,
                    "fields": fields,
                    "limit": limit,
                    "filtering": filtering,
                },
            )
            if resp.status_code >= 400:
                return {
                    "campaigns": [],
                    "warning": resp.json().get("error", {}).get("message", "Meta campaigns request failed."),
                }
            data = resp.json()
    except Exception as e:
        return {"campaigns": [], "warning": str(e)}

    campaigns = []
    for campaign in data.get("data", []):
        if campaign.get("effective_status") != "ACTIVE" and campaign.get("status") != "ACTIVE":
            continue

        adsets = (campaign.get("adsets") or {}).get("data", [])
        active_adsets = []
        for adset in adsets:
            if adset.get("effective_status") != "ACTIVE" and adset.get("status") != "ACTIVE":
                continue
            ads = (adset.get("ads") or {}).get("data", [])
            adset["ads"] = {
                "data": [
                    ad for ad in ads
                    if ad.get("effective_status") == "ACTIVE" or ad.get("status") == "ACTIVE"
                ]
            }
            active_adsets.append(adset)
        campaign["adsets"] = {"data": active_adsets}
        campaigns.append(campaign)
    return {"campaigns": campaigns}
