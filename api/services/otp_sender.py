"""OTP delivery for the startbyconnec funnel.

Sends the login code over the WhatsApp Cloud API using the "logincode"
AUTHENTICATION template. Authentication templates carry the code twice: once as
the body parameter and once as the copy-code button parameter.

When WhatsApp is not configured the sender is a no-op and the funnel keeps the
static dev code (settings.funnel_otp_code), so local development still works.
"""
import logging
import secrets

import httpx

from ..core.config import settings
from ..core.external_calls import external_call, redact_secrets

log = logging.getLogger(__name__)


class OtpSendError(RuntimeError):
    """WhatsApp did not accept the OTP template message."""


def whatsapp_configured() -> bool:
    return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id)


def generate_code() -> str:
    """Random 6-digit code when WhatsApp can deliver it, static code otherwise.

    A random code is only safe once the user actually receives it — without a
    delivery channel the funnel would be unusable, so dev keeps the static one.
    """
    if not whatsapp_configured():
        return settings.funnel_otp_code
    return f"{secrets.randbelow(1_000_000):06d}"


async def send_otp(phone: str, code: str) -> None:
    """Deliver ``code`` to ``phone`` over WhatsApp. Raises OtpSendError on failure."""
    if not whatsapp_configured():
        log.info("otp_sender: WhatsApp not configured; static code left for %s", phone)
        return

    # Cloud API expects E.164 digits without the leading "+".
    to = phone.lstrip("+")
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_otp_template_name,
            "language": {"code": settings.whatsapp_otp_template_language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": code}],
                },
            ],
        },
    }

    async with external_call(
        "whatsapp",
        "send_otp_template",
        template=settings.whatsapp_otp_template_name,
    ) as call:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json=payload,
            )
        call.note(status_code=response.status_code)
        if response.status_code >= 400:
            detail = redact_secrets(response.text) or ""
            raise OtpSendError(detail[:400])
