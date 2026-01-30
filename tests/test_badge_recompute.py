import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db
from app.models.event import Event
from app.models.user import User
from app.services.badge_service import recompute_badges_for_user


os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _create_user(email: str, **kwargs) -> User:
    user = User(email=email, **kwargs)
    db.session.add(user)
    db.session.commit()
    return user


def test_recompute_badges_awards_watcher_7d(app):
    with app.app_context():
        user = _create_user("watcher7d@example.com")
        now = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
        for offset in range(7):
            db.session.add(
                Event(
                    user_id=user.id,
                    event_type="login",
                    timestamp=now - timedelta(days=offset),
                )
            )
        db.session.commit()

        recompute_badges_for_user(user.id)
        db.session.commit()

        codes = {badge.badge_code for badge in user.badges}
        assert "WATCHER_7D" in codes


def test_recompute_badges_awards_premium_supporter(app):
    with app.app_context():
        user = _create_user("premium@example.com", premium=True, is_premium=True)
        recompute_badges_for_user(user.id)
        db.session.commit()

        codes = {badge.badge_code for badge in user.badges}
        assert "PREMIUM_SUPPORTER" in codes


def test_recompute_badges_awards_alert_triggered(app):
    with app.app_context():
        user = _create_user("alert@example.com")
        db.session.add(Event(user_id=user.id, event_type="alert"))
        db.session.commit()

        recompute_badges_for_user(user.id)
        db.session.commit()

        codes = {badge.badge_code for badge in user.badges}
        assert "ALERT_TRIGGERED" in codes
