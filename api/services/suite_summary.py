"""The suite, in the shape other products are allowed to depend on.

The `strategy` column is co-Suite's internal blob and changes whenever its
generators change. This function is the published contract, so a change there
stays here instead of breaking OneShare — and nothing from `connections` is
ever part of it.
"""
from typing import Any

from ..models.suite import Suite


def _plan(suite: Suite) -> dict[str, Any]:
    strategy = suite.strategy or {}
    return strategy.get("marketing_plan") or {}


def suite_summary(suite: Suite) -> dict[str, Any]:
    strategy = suite.strategy or {}
    brand = suite.brand or {}
    plan = _plan(suite)
    audience = plan.get("audience") or {}
    demographics = audience.get("demographics") or {}

    return {
        "suite": {
            "id": suite.id,
            "name": suite.name,
            "status": getattr(suite.status, "value", suite.status) or "onboarding",
            "updated_at": suite.updated_at.isoformat() if suite.updated_at else None,
        },
        "brand": {
            "description": brand.get("description") or "",
            "tagline": brand.get("tagline") or "",
            "services": brand.get("services") or [],
        },
        "audience": {
            "language": demographics.get("language") or strategy.get("language") or "",
            "demographics": {
                "age": demographics.get("age") or "",
                "gender": demographics.get("gender") or "",
                "social_status": demographics.get("social_status") or "",
            },
            "problem": audience.get("problem") or "",
            "personas": audience.get("personas") or [],
            "keywords": plan.get("keywords") or [],
        },
        "marketing_message": strategy.get("marketing_message") or "",
        "content_themes": plan.get("content_themes") or [],
    }
