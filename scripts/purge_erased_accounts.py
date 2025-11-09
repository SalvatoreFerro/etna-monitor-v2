"""Utility script to purge anonymised accounts after the retention window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import create_app
from app.models import CommunityPost, ModerationAction, User, db


def purge() -> None:
    app = create_app({"SERVER_NAME": "localhost"})
    with app.app_context():
        ttl_days = app.config.get("ACCOUNT_SOFT_DELETE_TTL_DAYS", 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        candidates = (
            User.query.filter(User.deleted_at.isnot(None))
            .filter(User.deleted_at <= cutoff)
            .all()
        )
        if not candidates:
            app.logger.info("[PURGE] Nessun account da eliminare")
            return

        now = datetime.now(timezone.utc)
        for user in candidates:
            app.logger.info("[PURGE] Eliminazione pianificata per user_id=%s", user.id)
            CommunityPost.query.filter_by(author_id=user.id).delete()
            ModerationAction.query.filter_by(moderator_id=user.id).delete()
            user.erased_at = now
            db.session.add(user)

        db.session.commit()
        app.logger.info("[PURGE] %s account aggiornati", len(candidates))


if __name__ == "__main__":
    purge()
