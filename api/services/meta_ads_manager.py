"""Meta Marketing API read helpers for connected ad accounts."""
import httpx

GRAPH = "https://graph.facebook.com/v22.0"


def _ad_account_node(ad_account_id: str) -> str:
    return ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"


async def fetch_campaigns(ad_account_id: str, access_token: str, limit: int = 25) -> dict:
    """Read campaigns for a connected Meta ad account."""
    if not ad_account_id or not access_token:
        return {"campaigns": [], "warning": "Meta Ads account is not connected."}

    fields = ",".join([
        "id",
        "name",
        "status",
        "effective_status",
        "objective",
        "buying_type",
        "created_time",
        "updated_time",
    ])

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{GRAPH}/{_ad_account_node(ad_account_id)}/campaigns",
                params={
                    "access_token": access_token,
                    "fields": fields,
                    "limit": limit,
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

    return {"campaigns": data.get("data", [])}
