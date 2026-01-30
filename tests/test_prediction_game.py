import os
from datetime import datetime, timedelta, timezone
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
from app.models import db
from app.models.tremor_prediction import TremorPrediction
from app.models.user import User
from app.services.prediction_service import resolve_expired_predictions
import app.utils.config as app_config


@pytest.fixture
def app(tmp_path):
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

    curva_path = tmp_path / "curva.csv"
    app_config.CURVA_CANONICAL_PATH = curva_path

    with app.app_context():
        db.create_all()
        yield app


def _write_curva_csv(path: Path, rows: list[dict[str, str | float]]) -> None:
    lines = ["timestamp,value"]
    for row in rows:
        lines.append(f"{row['timestamp']},{row['value']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_prediction_resolution_awards_points(app, tmp_path):
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(hours=25)
    resolves_at = created_at + timedelta(hours=24)

    user = User(email="player@example.com")
    db.session.add(user)
    db.session.commit()

    prediction = TremorPrediction(
        user_id=user.id,
        created_at=created_at,
        horizon_hours=24,
        prediction="UP",
        resolves_at=resolves_at,
        resolved=False,
    )
    db.session.add(prediction)
    db.session.commit()

    curva_rows = [
        {
            "timestamp": (resolves_at - timedelta(hours=24)).isoformat(),
            "value": 100,
        },
        {
            "timestamp": (resolves_at - timedelta(hours=23, minutes=50)).isoformat(),
            "value": 98,
        },
        {
            "timestamp": (resolves_at - timedelta(minutes=30)).isoformat(),
            "value": 115,
        },
        {
            "timestamp": (resolves_at - timedelta(minutes=5)).isoformat(),
            "value": 120,
        },
    ]
    _write_curva_csv(app_config.CURVA_CANONICAL_PATH, curva_rows)

    resolved_count = resolve_expired_predictions(now=now)
    assert resolved_count == 1

    refreshed = TremorPrediction.query.get(prediction.id)
    assert refreshed.resolved is True
    assert refreshed.actual_outcome == "UP"
    assert refreshed.points_awarded == 3
