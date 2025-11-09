#!/usr/bin/env python3
"""Management script to hide community posts with suspicious HTML payloads."""

from __future__ import annotations

from datetime import datetime, timezone

from app import create_app
from app.models import CommunityPost, ModerationAction, db
from app.utils.sanitize import find_suspicious_html

REPLACEMENT_MESSAGE = "[Contenuto rimosso per motivi di sicurezza]"


def sanitize_posts() -> int:
    app = create_app()
    sanitized_count = 0
    with app.app_context():
        now = datetime.now(timezone.utc)
        posts = CommunityPost.query.all()
        for post in posts:
            if not post:
                continue
            suspicious_patterns = find_suspicious_html(post.body)
            if not suspicious_patterns:
                suspicious_patterns = find_suspicious_html(post.body_html_sanitized)
            if not suspicious_patterns:
                continue
            if post.body == REPLACEMENT_MESSAGE and post.body_html_sanitized == REPLACEMENT_MESSAGE:
                continue

            post.status = "hidden"
            post.body = REPLACEMENT_MESSAGE
            post.body_html_sanitized = REPLACEMENT_MESSAGE
            post.moderator_reason = "XSS sanitization"
            post.moderated_at = now
            post.moderated_by = None

            moderation_action = ModerationAction(
                post_id=post.id,
                moderator_id=None,
                action="auto_hide_xss",
                reason="XSS sanitization",
                created_at=now,
            )
            db.session.add(moderation_action)
            db.session.add(post)
            sanitized_count += 1

        if sanitized_count:
            db.session.commit()
        else:
            db.session.rollback()

    return sanitized_count


def main() -> None:
    sanitized = sanitize_posts()
    print(f"Sanitized {sanitized} community post(s).")


if __name__ == "__main__":
    main()
