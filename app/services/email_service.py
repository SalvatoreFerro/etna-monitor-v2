"""Simple email delivery helper used for transactional messages.

This module keeps delivery pluggable while offering an in-memory
outbox suitable for unit tests. In production the ``send_email``
function can be easily extended to integrate with a third-party
provider (SendGrid, Mailgun, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from flask import current_app, render_template

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmailMessage:
    """Structure used to store email payloads in memory."""

    subject: str
    recipients: tuple[str, ...]
    html: str
    text: str
    extra: Mapping[str, object] | None = None


def _get_outbox() -> list[EmailMessage]:
    app = current_app._get_current_object()
    extensions = app.extensions.setdefault("email", {})
    outbox: list[EmailMessage] = extensions.setdefault("outbox", [])
    return outbox


def send_email(
    subject: str,
    recipients: Iterable[str],
    template_prefix: str,
    context: Mapping[str, object] | None = None,
) -> EmailMessage:
    """Render and store an email message."""

    context = dict(context or {})
    html = render_template(f"emails/{template_prefix}.html", **context)
    text = render_template(f"emails/{template_prefix}.txt", **context)

    message = EmailMessage(
        subject=subject,
        recipients=tuple(str(r) for r in recipients if r),
        html=html,
        text=text,
        extra=context,
    )

    outbox = _get_outbox()
    outbox.append(message)

    logger.info(
        "Email queued",
        extra={
            "subject": subject,
            "recipients": message.recipients,
            "template": template_prefix,
        },
    )

    return message


__all__ = ["send_email", "EmailMessage"]
