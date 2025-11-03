from datetime import datetime

import pytest
from sqlalchemy import and_, or_, text

from app import create_app
from app.models import db
from app.models.event import Event
from app.models.user import User
from config import Config


@pytest.fixture
def app_with_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    Config.TELEGRAM_BOT_TOKEN = "test-token"
    Config.ALERT_THRESHOLD_DEFAULT = 2.0
    Config.PREMIUM_DEFAULT_THRESHOLD = 2.0
    Config.ALERT_HYSTERESIS_DELTA = 0.2

    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _make_user(email: str, **kwargs) -> User:
    user = User(
        email=email,
        plan_type=kwargs.pop("plan_type", "premium"),
        premium=kwargs.pop("premium", True),
        is_premium=kwargs.pop("is_premium", True),
        premium_since=kwargs.pop("premium_since", datetime.utcnow()),
        telegram_opt_in=kwargs.pop("telegram_opt_in", True),
        **kwargs,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_admin_test_alert_filters_numeric_chat_ids(app_with_admin, monkeypatch):
    app = app_with_admin

    def _noop_check(self):
        return None

    monkeypatch.setattr("app.routes.admin.TelegramService.check_and_send_alerts", _noop_check)
    send_calls = []

    def _fake_send(token, chat_id, text, **kwargs):
        send_calls.append((token, chat_id, text))
        return True

    monkeypatch.setattr("app.services.telegram_service.send_telegram_alert", _fake_send)

    with app.app_context():
        admin = _make_user("admin@example.com", is_admin=True, telegram_opt_in=False)
        valid = _make_user("valid@example.com", telegram_chat_id=123456789, telegram_opt_in=True)
        legacy = _make_user("legacy@example.com", telegram_chat_id=None, chat_id=987654321, telegram_opt_in=True)
        _make_user("no_opt_in@example.com", telegram_chat_id=444444444, telegram_opt_in=False)
        _make_user("missing_chat@example.com", telegram_chat_id=None, telegram_opt_in=True)

        # Inject legacy dirty values that should be ignored by the numeric filter
        db.session.execute(text("PRAGMA ignore_check_constraints = 1"))
        db.session.execute(
            text(
                "INSERT INTO users (email, plan_type, premium, is_premium, premium_lifetime, telegram_opt_in, telegram_chat_id, chat_id) "
                "VALUES (:email, 'premium', 1, 1, 0, 1, '', NULL)"
            ),
            {"email": "blank@example.com"},
        )
        db.session.execute(
            text(
                "INSERT INTO users (email, plan_type, premium, is_premium, premium_lifetime, telegram_opt_in, telegram_chat_id, chat_id) "
                "VALUES (:email, 'premium', 1, 1, 0, 1, '   ', '')"
            ),
            {"email": "spaces@example.com"},
        )
        db.session.execute(text("PRAGMA ignore_check_constraints = 0"))
        db.session.execute(
            text("UPDATE users SET telegram_chat_id = NULL WHERE trim(CAST(telegram_chat_id AS TEXT)) = ''")
        )
        db.session.execute(
            text("UPDATE users SET chat_id = NULL WHERE trim(CAST(chat_id AS TEXT)) = ''")
        )
        db.session.commit()

        eligible_users = User.query.filter(
            or_(
                and_(User.telegram_chat_id.isnot(None), User.telegram_chat_id > 0),
                and_(User.chat_id.isnot(None), User.chat_id > 0),
            ),
            User.telegram_opt_in.is_(True),
        ).all()
        assert {user.email for user in eligible_users} == {"valid@example.com", "legacy@example.com"}

        client = app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = admin.id

        response = client.post("/admin/test-alert")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        assert "Utenti Premium con Telegram: 2" in payload["message"]
        assert len(send_calls) == 2

        # Ensure the dirty rows did not create alert events
        alert_events = Event.query.filter_by(event_type="alert").count()
        assert alert_events == 0


def test_admin_test_alert_requires_token(app_with_admin, monkeypatch):
    app = app_with_admin

    with app.app_context():
        admin = _make_user("admin@example.com", is_admin=True, telegram_opt_in=False)
        admin_id = admin.id

    # Remove token from both runtime config and fallback Config
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "")
    app.config["TELEGRAM_BOT_TOKEN"] = ""

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = admin_id

    response = client.post("/admin/test-alert")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "non configurato" in payload["message"].lower()
