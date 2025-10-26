import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")

from app import create_app
from app.services import telegram_bot_service


def test_telegram_bot_mode_off_prevents_polling(monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
    os.environ.setdefault("DISABLE_SCHEDULER", "1")
    os.environ["TELEGRAM_BOT_MODE"] = "off"
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "token")

    started = False

    def fake_start(self):
        nonlocal started
        started = True

    monkeypatch.setattr(
        telegram_bot_service.TelegramBotService,
        "_start_bot_thread",
        fake_start,
    )

    app = create_app({"TESTING": True})

    assert started is False
    status = app.config["TELEGRAM_BOT_STATUS"]
    assert status["mode"] == "off"
    assert status["running"] is False
