import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")

from app import create_app


def test_telegram_bot_mode_off_sets_status(monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
    os.environ.setdefault("DISABLE_SCHEDULER", "1")
    os.environ["TELEGRAM_BOT_MODE"] = "off"
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "token")

    app = create_app({"TESTING": True})

    status = app.config["TELEGRAM_BOT_STATUS"]
    assert status["mode"] == "off"
    assert status["running"] is False
