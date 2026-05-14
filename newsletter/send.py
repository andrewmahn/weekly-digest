"""Resend API client. Resend supports a free tier of 3,000 emails/month, 100/day —
oversized for a personal weekly newsletter with two recipients.
"""

from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from newsletter.config import Settings
from newsletter.logging_config import get_logger

log = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"


@retry(
    retry=retry_if_exception_type((httpx.HTTPError,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=10),
    reraise=True,
)
def send_email(
    settings: Settings,
    *,
    subject: str,
    html: str,
    recipients: list[str] | None = None,
) -> dict[str, Any]:
    """Send the newsletter via Resend. Retries up to 3x on transient HTTP errors."""
    to_addresses = recipients or settings.recipient_list

    payload: dict[str, Any] = {
        "from": settings.newsletter_from_email,
        "to": to_addresses,
        "subject": subject,
        "html": html,
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    log.info("resend.send_start", to_count=len(to_addresses), subject=subject)
    response = httpx.post(RESEND_URL, json=payload, headers=headers, timeout=30.0)

    if response.status_code >= 400:
        log.error(
            "resend.send_failed",
            status=response.status_code,
            body=response.text[:500],
        )
        response.raise_for_status()

    data = cast(dict[str, Any], response.json())
    log.info("resend.send_ok", message_id=data.get("id"))
    return data
