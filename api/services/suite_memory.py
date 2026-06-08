from __future__ import annotations

from typing import Any, Optional


SECRET_HINTS = ("token", "secret", "key", "password")


def _list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _safe_connection_summary(connections: dict) -> dict:
    summary = {}
    for platform in ("facebook", "instagram", "google_ads", "google"):
        raw = connections.get(platform) or {}
        if platform == "google":
            key = "google_ads"
        else:
            key = platform
        if not isinstance(raw, dict) or not raw:
            summary.setdefault(key, {"state": "not_connected"})
            continue

        safe = {
            name: value
            for name, value in raw.items()
            if not any(hint in name.lower() for hint in SECRET_HINTS)
            and name
            in {
                "id",
                "page_id",
                "page_name",
                "instagram_user_id",
                "ig_user_id",
                "account_id",
                "account_name",
                "customer_id",
                "email",
                "name",
                "status",
            }
        }
        summary[key] = {"state": "connected", **safe}
    return summary


def build_suite_memory_v0(
    brand: Optional[dict] = None,
    strategy: Optional[dict] = None,
    connections: Optional[dict] = None,
) -> dict:
    brand = brand or {}
    strategy = strategy or {}
    connections = connections or {}
    marketing_plan = strategy.get("marketing_plan") or {}

    business_profile = {
        "name": _first_non_empty(brand.get("name"), brand.get("business_name")),
        "category": _first_non_empty(brand.get("category"), brand.get("industry"), brand.get("niche")),
        "description": _first_non_empty(brand.get("description"), brand.get("summary")),
        "website": _first_non_empty(brand.get("website"), brand.get("website_url")),
        "location": _first_non_empty(brand.get("location"), brand.get("audience_location")),
    }
    audience_profile = {
        "summary": _first_non_empty(brand.get("target_audience"), brand.get("audience"), strategy.get("target_audience")),
        "segments": _list(_first_non_empty(brand.get("audience_segments"), strategy.get("audience_segments"))),
        "interests": _list(brand.get("audience_interests")),
        "behaviors": _list(brand.get("audience_behaviors")),
        "note": brand.get("audience_note"),
    }
    brand_profile = {
        "tone": brand.get("tone"),
        "tagline": brand.get("tagline"),
        "colors": brand.get("colors") or {},
        "usp_points": _list(brand.get("usp_points")),
        "esp_points": _list(brand.get("esp_points")),
        "content_themes": _list(marketing_plan.get("content_themes")),
    }
    language_profile = {
        "languages": _list(_first_non_empty(brand.get("audience_languages"), brand.get("languages"))),
        "primary_language": _first_non_empty(brand.get("primary_language"), (_list(brand.get("audience_languages")) or [None])[0]),
    }
    visual_assets = {
        "logos": _list(_first_non_empty(brand.get("brand_logos"), brand.get("logos"), brand.get("logo_url"))),
        "reference_images": _list(brand.get("reference_images")),
        "fonts": _list(brand.get("fonts")),
    }
    products_services = {
        "items": _list(_first_non_empty(brand.get("services"), brand.get("products"), brand.get("products_services"))),
    }

    usable_brand_fields = [
        business_profile["name"],
        business_profile["category"],
        audience_profile["summary"],
        products_services["items"],
        brand_profile["tone"],
    ]

    return {
        "version": "suite_memory_v0",
        "business_profile": business_profile,
        "audience_profile": audience_profile,
        "brand_profile": brand_profile,
        "language_profile": language_profile,
        "content_rules": _list(brand.get("content_rules")),
        "visual_assets": visual_assets,
        "personas": _list(_first_non_empty(brand.get("brand_personas"), brand.get("personas"))),
        "products_services": products_services,
        "platform_connections_summary": _safe_connection_summary(connections),
        "use_brand_default": any(bool(value) for value in usable_brand_fields),
    }


def merge_suite_brand(existing: Optional[dict], incoming: dict) -> dict:
    """Merge profile edits without erasing unrelated Suite Memory fields.

    M1 profile editing sends partial brand sections from multiple screens. A
    shallow replacement can erase user-uploaded logos, content rules, personas,
    or previous AI/user fields. Lists are replaced intentionally when supplied;
    nested dicts are merged.
    """
    if not isinstance(incoming, dict):
        return dict(existing or {})
    return _deep_merge_dicts(dict(existing or {}), incoming)


def _deep_merge_dicts(existing: dict, incoming: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
