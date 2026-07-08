"""Fire-and-forget Telegram notifications to the company group."""
import logging

import httpx

from ..core.config import settings
from ..core.external_calls import external_call

log = logging.getLogger(__name__)


async def send_company_message(text: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_company_chat_id or "").strip()
    if not token or not chat_id:
        log.info("Telegram notify skipped: bot token or company chat id not configured")
        return False
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    topic = (settings.telegram_topic_leads or "").strip()
    if topic:
        payload["message_thread_id"] = int(topic)
    try:
        async with external_call("telegram", "send_company_message") as call:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage", json=payload
                )
                call.note(status_code=resp.status_code)
                if resp.status_code != 200:
                    call.fail(f"telegram returned {resp.status_code}")
                    return False
                return True
    except Exception:
        log.warning("Telegram notify failed", exc_info=True)
        return False
