import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db
from app.models.user import User
from app.services.telegram_service import TelegramService


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("SKIP_CURVA_BOOTSTRAP", "1")
    config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        "SECRET_KEY": "test-secret",
        "TELEGRAM_BOT_MODE": "off",
        "DISABLE_SCHEDULER": True,
    }
    app = create_app(config)
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_bigint_filters_ignore_blank_entries(app):
    with app.app_context():
        valid = User(
            email="valid@example.com",
            telegram_chat_id=123456789,
            telegram_opt_in=True,
            plan_type="premium",
            subscription_status="active",
        )
        legacy = User(
            email="legacy@example.com",
            telegram_chat_id=None,
            chat_id=None,
            telegram_opt_in=True,
        )
        db.session.add_all([valid, legacy])
        db.session.commit()

        service = TelegramService()
        subscribers = service._get_subscribed_users()
        emails = {user.email for user in subscribers}
        assert emails == {"valid@example.com"}
