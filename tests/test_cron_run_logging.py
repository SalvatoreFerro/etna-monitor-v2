from datetime import datetime

import pytest

from app import create_app
from app.models import db
from app.models.cron_run import CronRun


@pytest.fixture
def app_with_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    csv_path = tmp_path / "curva.csv"
    csv_path.write_text("timestamp,value\n2024-01-01T00:00:00Z,1.25\n", encoding="utf-8")

    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TESTING": True,
            "CRON_SECRET": "test-secret",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_check_alerts_persists_cron_run(app_with_db, monkeypatch):
    def _fake_check(self, raise_on_error=True):
        return {
            "sent": 0,
            "skipped": 0,
            "cooldown_skipped": 0,
            "skipped_by_reason": {},
            "reason": "completed",
        }

    monkeypatch.setattr("app.routes.internal.TelegramService.is_configured", lambda self: True)
    monkeypatch.setattr("app.routes.internal.TelegramService.check_and_send_alerts", _fake_check)

    client = app_with_db.test_client()
    response = client.post("/internal/cron/check-alerts?key=test-secret")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    with app_with_db.app_context():
        run = CronRun.query.filter_by(job_type="check_alerts").first()
        assert run is not None
        assert run.ok is True
        assert run.status == "success"
        assert run.reason == "completed"
        assert run.duration_ms is not None
        assert run.csv_path
        assert isinstance(run.created_at, datetime)
        assert isinstance(run.started_at, datetime)
        assert isinstance(run.finished_at, datetime)
        assert isinstance(run.diagnostic_json, dict)
