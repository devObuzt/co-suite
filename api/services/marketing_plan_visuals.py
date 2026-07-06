"""Generate and store field-related images for the marketing plan deck."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from ..core.config import settings
from ..models.suite import Suite
from .content_generator import _generate_image
from .media_storage import r2_configured, store_brand_asset

log = logging.getLogger(__name__)

VISUAL_SPECS: list[tuple[str, str]] = [
    ("cover", "16:9"),
    ("audience", "16:9"),
    ("services", "16:9"),
]


def _visual_prompt(brand: dict[str, Any], suite_name: str, kind: str) -> str:
    industry = str(brand.get("industry") or brand.get("category") or brand.get("niche") or "local business").strip()
    services = ", ".join(str(item) for item in (brand.get("services") or [])[:4])
    audience = str(brand.get("target_audience") or brand.get("audience_notes") or "local customers").strip()
    base_quality = (
        "Professional editorial commercial photography, realistic, warm modern lighting, "
        "shallow depth of field, high-end magazine quality. "
        "Absolutely no text, no words, no letters, no logos, no watermarks, no captions."
    )
    if kind == "audience":
        return (
            f"Lifestyle photo of the target customers of a {industry} business ({audience}), "
            f"in a natural everyday setting relevant to {services or industry}. {base_quality}"
        )
    if kind == "services":
        return (
            f"Detailed close-up photo showing the work or products of a {industry} business: {services or industry}. "
            f"{base_quality}"
        )
    return (
        f"Hero cover photo representing a {industry} business named context only (do not render the name), "
        f"showing its environment or craft: {services or industry}. Cinematic composition. {base_quality}"
    )


def deck_visuals(suite: Suite) -> list[dict[str, Any]]:
    strategy = suite.strategy if isinstance(suite.strategy, dict) else {}
    deck = strategy.get("marketing_plan_deck") if isinstance(strategy.get("marketing_plan_deck"), dict) else {}
    items = list(strategy.get("marketing_plan_visuals") or []) + list(deck.get("visuals") or [])
    return [item for item in items if isinstance(item, dict) and item.get("url")]


async def ensure_marketing_plan_visuals(suite: Suite) -> list[dict[str, Any]]:
    """Generate the plan's field images once and persist their URLs on the strategy."""
    strategy = dict(suite.strategy or {})
    if not strategy:
        return []
    existing = deck_visuals(suite)
    if existing:
        return existing
    if not settings.google_api_key or not r2_configured():
        return []
    brand = suite.brand if isinstance(suite.brand, dict) else {}
    suite_name = str(brand.get("name") or suite.name or "business")

    async def generate_one(kind: str, aspect: str) -> dict[str, Any] | None:
        try:
            data = await asyncio.to_thread(
                _generate_image,
                _visual_prompt(brand, suite_name, kind),
                aspect,
            )
            if not data:
                return None
            stored = store_brand_asset(
                suite.id,
                "plan-visual",
                f"{kind}-{uuid.uuid4().hex[:8]}.png",
                data,
                "image/png",
            )
            return {"kind": kind, "url": stored.url}
        except Exception as exc:
            log.warning("Plan visual generation failed for %s: %s", kind, exc)
            return None

    results = await asyncio.gather(*[generate_one(kind, aspect) for kind, aspect in VISUAL_SPECS])
    visuals = [item for item in results if item]
    if visuals:
        strategy["marketing_plan_visuals"] = visuals
        suite.strategy = strategy
    return visuals
