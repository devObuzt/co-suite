"""Where a Meta token comes from.

Until now it came from `suites.connections` — a JSON column holding page and
user tokens in clear text. Manzuma's vault holds the same tokens encrypted and
hands them out per business, so that is where we read them from now.

Migration is a reconnect, not a copy: a suite linked to a business whose Meta
connection lives in the vault uses the vault. A suite that is not linked yet
keeps working on its stored token, and says so in the log — that line is how we
know when the old column is finally unused and safe to empty.
"""
import logging
from typing import Any, Optional

from ..models.suite import Suite
from .manzuma_accounts import vault_token

log = logging.getLogger(__name__)


async def _from_vault(organization_id: str, asset_id: Optional[str]) -> Optional[str]:
    return await vault_token(organization_id, "meta", asset_id)


async def connections_with_vault_tokens(suite: Suite) -> dict[str, Any]:
    """`suite.connections`, with every Meta token replaced by the vault's.

    Returns a copy: nothing here writes a token back into the database.
    """
    connections: dict[str, Any] = dict(suite.connections or {})
    organization_id = getattr(suite, "organization_id", None)
    if not organization_id:
        log.info("[meta-tokens] suite %s has no business yet — using its stored tokens", suite.id)
        return connections

    facebook = dict(connections.get("facebook") or {})
    instagram = dict(connections.get("instagram") or {})
    meta_ads = dict(connections.get("meta_ads") or {})

    page_id = facebook.get("page_id")
    page_token = await _from_vault(organization_id, page_id) if page_id else None
    if page_token:
        facebook["page_access_token"] = page_token
        # Instagram posts through the same Page token.
        if instagram:
            instagram["page_access_token"] = page_token
        connections["facebook"] = facebook
        if instagram:
            connections["instagram"] = instagram
    elif facebook.get("page_access_token"):
        log.info(
            "[meta-tokens] suite %s: vault has no page token for business %s — using the stored one",
            suite.id,
            organization_id,
        )

    if meta_ads:
        # Ad accounts are read with the user-level token, which the vault
        # serves when no asset is named.
        ads_token = await _from_vault(organization_id, None)
        if ads_token:
            meta_ads["user_access_token"] = ads_token
            connections["meta_ads"] = meta_ads
        elif meta_ads.get("user_access_token"):
            log.info(
                "[meta-tokens] suite %s: vault has no ads token for business %s — using the stored one",
                suite.id,
                organization_id,
            )

    return connections
