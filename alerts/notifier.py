"""Utilities for notifying users via Telegram."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests
from requests import RequestException, Response

from app.utils.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0


def _build_payload(chat_id: str, text: str, parse_mode: Optional[str] = None,
                   disable_notification: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_notification:
        payload["disable_notification"] = disable_notification
    return payload


def _should_retry(response: Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code < 600


def send_telegram_alert(
    token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: Optional[str] = None,
    disable_notification: bool = False,
) -> bool:
    """Send an alert message through the Telegram Bot API.

    The function retries on rate-limit (HTTP 429) and transient server errors
    with exponential backoff, respecting the ``Retry-After`` header when
    present. Returns ``True`` on success and ``False`` when the message could
    not be delivered after the configured retries.
    """

    if not token or not chat_id:
        logger.warning("Token/chat_id mancanti: niente invio")
        return False

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = _build_payload(chat_id, text, parse_mode=parse_mode,
                             disable_notification=disable_notification)

    backoff = INITIAL_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        except RequestException as exc:
            logger.error("Errore nel contattare Telegram (tentativo %s/%s): %s",
                         attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                return False
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if attempt == MAX_RETRIES:
                logger.error("Telegram rate limit raggiunto dopo %s tentativi", attempt)
                return False
            try:
                wait_seconds = float(retry_after) if retry_after is not None else backoff
            except (TypeError, ValueError):
                wait_seconds = backoff
            wait_seconds = max(wait_seconds, 0.5)
            logger.warning("Rate limit Telegram (%s). Retry fra %s secondi.",
                           chat_id, wait_seconds)
            time.sleep(min(wait_seconds, MAX_BACKOFF))
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        if _should_retry(response):
            logger.error("Errore server Telegram %s al tentativo %s/%s",
                         response.status_code, attempt, MAX_RETRIES)
            if attempt == MAX_RETRIES:
                return False
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        try:
            response.raise_for_status()
        except RequestException as exc:
            logger.error("Errore risposta Telegram: %s", exc)
            if attempt == MAX_RETRIES:
                return False
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        logger.info("[TELEGRAM] → %s: %s", chat_id, text)
        return True

    return False
