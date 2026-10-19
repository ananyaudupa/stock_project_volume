"""Administrator alerts. Always logged at ERROR/WARNING; optionally POSTed to ALERT_WEBHOOK_URL."""

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("alerts")


def send_alert(kind: str, message: str, **context) -> None:
    log.error(message, extra={"alert": kind, **context})
    url = get_settings().alert_webhook_url
    if not url:
        return
    try:
        httpx.post(url, json={"kind": kind, "message": message, "context": context}, timeout=5)
    except httpx.HTTPError:
        log.warning("alert webhook delivery failed", extra={"alert": kind})
