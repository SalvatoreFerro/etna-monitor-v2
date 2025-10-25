"""Notification helpers used across the application."""

import logging


def notify_admin_new_donation(user_email: str, tx_id: str) -> None:
    """Stub notification to alert admins about a new donation request."""
    logging.getLogger(__name__).info(
        "New donation submitted for review", extra={"user_email": user_email, "tx_id": tx_id}
    )
    print(f"[donations] Pending verification for {user_email} (tx_id={tx_id})")
