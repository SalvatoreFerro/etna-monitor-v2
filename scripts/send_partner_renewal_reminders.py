"""Send renewal reminders for partner subscriptions."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import joinedload

from app import create_app
from app.models import PartnerSubscription
from flask import render_template

from app.services.email_service import send_email

REMINDER_WINDOWS = {30, 7, 1}


def send_reminders() -> int:
    app = create_app()
    sent = 0
    with app.app_context():
        today = date.today()
        admin_email = app.config.get("ADMIN_EMAIL")
        query = PartnerSubscription.query.filter(PartnerSubscription.status == "paid")
        for subscription in query.options(joinedload(PartnerSubscription.partner)).all():
            if not subscription.valid_to:
                continue
            days_left = (subscription.valid_to - today).days
            if days_left not in REMINDER_WINDOWS:
                continue
            partner = subscription.partner
            recipients = [partner.email] if partner and partner.email else []
            bcc = [admin_email] if admin_email else []
            delivery = recipients or bcc
            if not delivery:
                continue
            send_email(
                subject=f"Rinnovo directory partner — {partner.name}",
                recipients=delivery,
                bcc=bcc if recipients else None,
                body=render_template(
                    partner=partner,
                    subscription=subscription,
                    days_left=days_left,
                ),
            )
            sent += 1
    return sent


if __name__ == "__main__":
    total = send_reminders()
    print(f"Sent {total} reminder(s)")
