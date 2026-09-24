"""«Your work plan is ready» — the WhatsApp notification for a long run.

The work plan takes minutes, not seconds. Rather than hold the visitor on a
spinner, the page offers to message them when it is done. Two rules shape this
module:

1. The offer is only made when the message can actually be sent. Availability
   is reported to the page, so the WhatsApp button never appears on a system
   that would silently drop the message.
2. The message goes out in the language the visitor chose. Arabic and Hebrew
   have their own templates; every other language uses the English one.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import text

from ..core.config import settings
from ..core.external_calls import external_call, redact_secrets
from ..models.suite import Suite

log = logging.getLogger(__name__)

NOTIFY_KEY = "plan_ready_notify"


def whatsapp_notify_available() -> bool:
    """Whether a "plan is ready" WhatsApp message can actually leave.

    All three must hold — the flag, the token and the sending number. The API
    reports this to the page and the worker checks it again before sending.
    """
    return bool(
        settings.whatsapp_notify_enabled
        and settings.whatsapp_access_token
        and settings.whatsapp_phone_number_id
    )


def template_for_language(language: str) -> str:
    """Arabic and Hebrew have their own; everything else falls back to English."""
    marker = (language or "").strip().lower()
    if marker.startswith("ar"):
        return settings.whatsapp_plan_ready_template_ar
    if marker.startswith("he"):
        return settings.whatsapp_plan_ready_template_he
    return settings.whatsapp_plan_ready_template_en


def template_language_code(language: str) -> str:
    marker = (language or "").strip().lower()
    if marker.startswith("ar"):
        return "ar"
    if marker.startswith("he"):
        return "he"
    return "en"


def _strategy(suite: Suite) -> dict[str, Any]:
    return dict(suite.strategy or {})


def read_preference(suite: Suite) -> dict[str, Any]:
    value = _strategy(suite).get(NOTIFY_KEY)
    return value if isinstance(value, dict) else {}


def save_preference(suite: Suite, *, whatsapp: bool, language: str, phone: str | None) -> dict[str, Any]:
    """Record what the visitor chose in the waiting dialog."""
    strategy = _strategy(suite)
    preference = {
        "whatsapp": bool(whatsapp),
        "language": language or "",
        "phone": (phone or "").strip(),
        "sent": False,
    }
    strategy[NOTIFY_KEY] = preference
    suite.strategy = strategy
    return preference


async def mark_sent(db, suite_id: str) -> None:
    """One message per plan: a retrying job must not message twice.

    Written with `jsonb_set` for the same reason every other plan write is —
    rewriting the whole `strategy` column from a Python copy is what kept
    erasing sibling jobs' work.
    """
    await db.execute(
        text(
            """
            UPDATE suites
               SET strategy = jsonb_set(
                     COALESCE(strategy::jsonb, '{}'::jsonb),
                     ARRAY[:key, 'sent'], 'true'::jsonb, true
                   )::json
             WHERE id = :suite_id
            """
        ),
        {"key": NOTIFY_KEY, "suite_id": suite_id},
    )
    await db.commit()


async def maybe_notify_plan_ready(db, suite_id: str) -> bool:
    """Send the "it's ready" message if the visitor asked and it is now true.

    Called at the end of every job that finishes something the visitor might be
    waiting on. The first version only fired at the end of the marketing-plan
    run — but the dialog lives on the WORK-PLANS page, whose jobs run minutes
    later, so the message was attached to a run that had already finished and
    nothing was ever sent (measured 2026-09-24: plan done 17:12:42, work plan
    17:24:04, opt-in in between, no message).

    Safe to call from several places: `sent` is the guard.
    """
    row = (
        await db.execute(
            text("SELECT name, brand, strategy FROM suites WHERE id = :id"), {"id": suite_id}
        )
    ).mappings().first()
    if not row:
        return False

    strategy = row["strategy"] or {}
    if isinstance(strategy, str):
        strategy = json.loads(strategy)
    preference = strategy.get(NOTIFY_KEY) or {}
    if not preference.get("whatsapp") or preference.get("sent"):
        return False

    brand = row["brand"] or {}
    if isinstance(brand, str):
        brand = json.loads(brand)

    delivered = await send_plan_ready(
        str(preference.get("phone") or ""),
        str(preference.get("language") or ""),
        str(brand.get("name") or row["name"] or ""),
    )
    if delivered:
        await mark_sent(db, suite_id)
    return delivered


async def send_plan_ready(phone: str, language: str, business_name: str) -> bool:
    """Send the template. Returns True when WhatsApp accepted it."""
    if not whatsapp_notify_available():
        log.info("plan_notify: WhatsApp notification not available; nothing sent to %s", phone)
        return False
    if not phone.strip():
        log.info("plan_notify: no phone on file; nothing sent")
        return False

    to = phone.strip().lstrip("+")
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )
    template = template_for_language(language)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": template_language_code(language)},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": business_name or "—"}]}
            ],
        },
    }
    try:
        async with external_call("whatsapp", "send_plan_ready", template=template) as call:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                    json=payload,
                )
            call.note(status_code=response.status_code)
            if response.status_code >= 400:
                # Never fail the generation over a notification.
                log.warning(
                    "plan_notify: WhatsApp refused the message (%s): %s",
                    response.status_code,
                    (redact_secrets(response.text) or "")[:300],
                )
                return False
    except Exception:
        log.exception("plan_notify: could not send the plan-ready message")
        return False
    return True
