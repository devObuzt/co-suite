"""Pure relevance filter: pick the occasions worth building ideas around.

Universal types (religious/national/seasonal/commercial) are always kept;
sports/school are kept this phase (refined against brand field later). Ranked by
confidence then universality, capped so generation isn't flooded.
"""
_UNIVERSAL = {"religious", "national", "seasonal", "commercial"}
_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def relevant_occasions(occasions, brand, *, limit: int = 6) -> list[dict]:
    kept = [
        o for o in (occasions or [])
        if isinstance(o, dict) and o.get("title")
        and (o.get("type") in _UNIVERSAL or o.get("type") in {"sports", "school"})
    ]
    kept.sort(key=lambda o: (
        _CONF_RANK.get(o.get("confidence"), 1),
        0 if o.get("type") in _UNIVERSAL else 1,
    ))
    return kept[:limit]
