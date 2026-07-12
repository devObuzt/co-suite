"""OTP delivery for the startbyconnec funnel.

Currently a stub: the code is static (settings.funnel_otp_code) and nothing is
actually sent. When WhatsApp/SMS is wired in, implement send_otp() with the
provider call wrapped in external_call() per the logging convention.
"""
import logging

log = logging.getLogger(__name__)


async def send_otp(phone: str, code: str) -> None:
    log.info("otp_sender stub: would send code to %s (code=%s)", phone, code)
