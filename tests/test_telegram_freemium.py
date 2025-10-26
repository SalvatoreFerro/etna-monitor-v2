import os
from datetime import datetime, timedelta
from typing import List

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")

import pytest

from app import create_app
from app.models import db
from app.models.event import Event
from app.models.user import User
from app.services.telegram_service import TelegramService
from config import Config
import app.services.telegram_service as telegram_module


class DummyResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return


def _write_curva_csv(base_dir: str, start: datetime, values: List[float], step_minutes: int = 1) -> None:
    path = os.path.join(base_dir, "curva.csv")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("timestamp,value\n")
        for index, value in enumerate(values):
            ts = start + timedelta(minutes=index * step_minutes)
            handle.write(f"{ts.isoformat()},{value}\n")


def _setup_config() -> None:
    os.environ["SECRET_KEY"] = "test-secret-key"
    os.environ["DISABLE_SCHEDULER"] = "1"
    Config.TELEGRAM_BOT_TOKEN = "test-token"
    Config.PAYPAL_DONATION_LINK = "https://example.org/donate"
    Config.ALERT_THRESHOLD_DEFAULT = 2.0
    Config.PREMIUM_DEFAULT_THRESHOLD = 2.0
    Config.ALERT_HYSTERESIS_DELTA = 0.2


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _setup_config()

    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        yield tmp_path, app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def message_spy(monkeypatch):
    sent: List[dict] = []

    def fake_post(url, json=None, timeout=10):
        sent.append(json or {})
        return DummyResponse()

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    return sent


def _create_user(email: str, plan: str, chat_id: str = "12345", **kwargs) -> User:
    user = User(
        email=email,
        plan_type=plan,
        telegram_chat_id=chat_id,
        telegram_opt_in=True,
        chat_id=chat_id,
        **kwargs,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_free_user_receives_single_trial_alert(app_ctx, message_spy):
    tmp_path, app = app_ctx
    service = TelegramService()

    with app.app_context():
        user = _create_user("free@example.com", "free")
        start = datetime(2024, 1, 1, 0, 0)
        _write_curva_csv(str(tmp_path), start, [2.1, 2.3, 2.6, 2.8, 3.0])

        service.check_and_send_alerts()

        db.session.refresh(user)
        assert user.free_alert_consumed == 1
        assert user.free_alert_event_id is not None
        assert user.alert_count_30d == 1
        assert len(message_spy) == 1
        assert "unico alert gratuito" in message_spy[0]["text"]

        free_events = Event.query.filter_by(user_id=user.id, event_type="free_trial_consumed").count()
        assert free_events == 1


def test_free_user_upsell_only_once_per_day(app_ctx, message_spy):
    tmp_path, app = app_ctx
    service = TelegramService()

    with app.app_context():
        user = _create_user("free2@example.com", "free")
        start = datetime(2024, 1, 1, 0, 0)
        _write_curva_csv(str(tmp_path), start, [2.2, 2.4, 2.6, 2.9, 3.1])
        service.check_and_send_alerts()

        # New event -> upsell
        start = start + timedelta(hours=3)
        _write_curva_csv(str(tmp_path), start, [2.3, 2.5, 2.7, 3.0, 3.2])
        service.check_and_send_alerts()

        assert len(message_spy) == 2  # trial + upsell
        assert "Premium" in message_spy[-1]["text"]

        # Third attempt within 24h does not send another upsell
        start = start + timedelta(hours=1)
        _write_curva_csv(str(tmp_path), start, [2.4, 2.6, 2.7, 3.1, 3.3])
        service.check_and_send_alerts()

        assert len(message_spy) == 2
        upsell_events = Event.query.filter_by(user_id=user.id, event_type="upsell").count()
        assert upsell_events == 1


def test_premium_user_alert_respects_rate_limit(app_ctx, message_spy):
    tmp_path, app = app_ctx
    service = TelegramService()

    with app.app_context():
        user = _create_user("premium@example.com", "premium", is_premium=True)
        start = datetime(2024, 1, 1, 0, 0)
        _write_curva_csv(str(tmp_path), start, [2.5, 2.6, 2.8, 3.0, 3.4])
        service.check_and_send_alerts()
        assert len(message_spy) == 1

        # Within rate limit window -> no new alert
        start = start + timedelta(minutes=30)
        _write_curva_csv(str(tmp_path), start, [2.6, 2.7, 2.9, 3.2, 3.5])
        service.check_and_send_alerts()
        assert len(message_spy) == 1

        # Move past rate limit and drop below hysteresis to reset
        user.last_alert_sent_at = datetime.utcnow() - timedelta(hours=3)
        db.session.commit()
        start = start + timedelta(hours=1)
        _write_curva_csv(str(tmp_path), start, [1.8, 1.9, 1.7, 1.6, 1.5])
        service.check_and_send_alerts()

        # Now trigger again
        start = start + timedelta(hours=3)
        _write_curva_csv(str(tmp_path), start, [2.6, 2.8, 3.0, 3.2, 3.6])
        service.check_and_send_alerts()
        assert len(message_spy) == 2


def test_hysteresis_prevents_duplicate_alerts(app_ctx, message_spy):
    tmp_path, app = app_ctx
    service = TelegramService()

    with app.app_context():
        user = _create_user("premium2@example.com", "premium", is_premium=True)
        start = datetime(2024, 1, 1, 0, 0)
        _write_curva_csv(str(tmp_path), start, [2.5, 2.6, 2.9, 3.2, 3.6])
        service.check_and_send_alerts()
        assert len(message_spy) == 1

        user.last_alert_sent_at = datetime.utcnow() - timedelta(hours=3)
        db.session.commit()

        # Still above threshold, hysteresis should block second alert
        start = start + timedelta(hours=1)
        _write_curva_csv(str(tmp_path), start, [2.6, 2.7, 2.9, 3.1, 3.3])
        service.check_and_send_alerts()
        assert len(message_spy) == 1

        # Drop below hysteresis delta to unlock new alert
        start = start + timedelta(hours=1)
        _write_curva_csv(str(tmp_path), start, [1.5, 1.6, 1.7, 1.4, 1.3])
        service.check_and_send_alerts()

        start = start + timedelta(hours=2)
        _write_curva_csv(str(tmp_path), start, [2.5, 2.7, 3.0, 3.3, 3.7])
        service.check_and_send_alerts()
        assert len(message_spy) == 2

        alert_events = Event.query.filter_by(user_id=user.id, event_type="alert").count()
        assert alert_events == 2
