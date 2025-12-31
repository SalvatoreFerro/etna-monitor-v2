import os
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from app import create_app
from app.utils.metrics import get_csv_metrics, record_csv_update


@pytest.fixture
def app(tmp_path):
    metrics_path = tmp_path / "csv_metrics.json"
    os.environ["CSV_METRICS_PATH"] = str(metrics_path)

    app = create_app(
        {
            "TESTING": True,
            "CSV_METRICS_PATH": str(metrics_path),
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
        }
    )

    with app.app_context():
        yield app


def test_csv_update_metrics_are_exposed(app, tmp_path):
    metrics_path = Path(os.environ["CSV_METRICS_PATH"])
    assert not metrics_path.exists()

    with app.app_context():
        record_csv_update(42, None, error_message="test-error")
        metrics = get_csv_metrics()

    assert metrics_path.exists()
    assert metrics["last_update_row_count"] == 42
    assert metrics["last_update_error"] == "test-error"
