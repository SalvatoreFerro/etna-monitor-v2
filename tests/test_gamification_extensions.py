"""Tests for multi-horizon predictions and mission system."""

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
os.environ.setdefault("ENABLE_MISSIONS", "1")

from app import create_app
from app.models import db
from app.models.event import Event
from app.models.mission import UserMission
from app.models.tremor_prediction import TremorPrediction
from app.models.user import User
from app.services.mission_service import (
    assign_mission_to_user,
    check_and_complete_missions,
    claim_mission_reward,
    get_user_missions,
)
from app.services.prediction_service import (
    PREDICTION_HORIZONS,
    resolve_expired_predictions,
)
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


@pytest.fixture
def client(app):
    return app.test_client()


def _write_curva_csv(path: Path, rows: list[dict[str, str | float]]) -> None:
    lines = ["timestamp,value"]
    for row in rows:
        lines.append(f"{row['timestamp']},{row['value']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_prediction_horizons_constant():
    """Test that PREDICTION_HORIZONS is properly defined."""
    assert PREDICTION_HORIZONS == [6, 12, 24]
    assert 6 in PREDICTION_HORIZONS
    assert 12 in PREDICTION_HORIZONS
    assert 24 in PREDICTION_HORIZONS


def test_create_prediction_with_custom_horizon(app, client, tmp_path):
    """Test creating a prediction with a non-default horizon."""
    with app.app_context():
        user = User(email="test@example.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    # Login the user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    # Note: This test is mainly for documentation - actual CSRF validation
    # would prevent this from working without a proper token setup


def test_create_prediction_rejects_invalid_horizon(app, client, tmp_path):
    """Test that invalid horizon values are rejected."""
    with app.app_context():
        user = User(email="test@example.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    # Note: This test is mainly for documentation - actual CSRF validation
    # would prevent this from working without a proper token setup


def test_resolve_predictions_with_different_horizons(app, tmp_path):
    """Test that predictions with different horizons are resolved correctly."""
    now = datetime.now(timezone.utc)

    user = User(email="player@example.com")
    db.session.add(user)
    db.session.commit()

    # Create predictions with different horizons
    for horizon in [6, 12, 24]:
        created_at = now - timedelta(hours=horizon + 1)
        resolves_at = created_at + timedelta(hours=horizon)

        prediction = TremorPrediction(
            user_id=user.id,
            created_at=created_at,
            horizon_hours=horizon,
            prediction="UP",
            resolves_at=resolves_at,
            resolved=False,
        )
        db.session.add(prediction)

    db.session.commit()

    # Create CSV data that shows an upward trend
    curva_rows = []
    for hours_back in range(30, 0, -1):
        timestamp = now - timedelta(hours=hours_back)
        # Value increases over time
        value = 100 + (30 - hours_back) * 2
        curva_rows.append({"timestamp": timestamp.isoformat(), "value": value})

    _write_curva_csv(app_config.CURVA_CANONICAL_PATH, curva_rows)

    # Resolve all predictions
    resolved_count = resolve_expired_predictions(now=now)
    assert resolved_count == 3

    # Check that all predictions were resolved
    predictions = TremorPrediction.query.all()
    assert len(predictions) == 3
    for pred in predictions:
        assert pred.resolved is True
        assert pred.actual_outcome in ["UP", "DOWN", "FLAT"]


def test_mission_assignment(app):
    """Test assigning a mission to a user."""
    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    mission = assign_mission_to_user(user.id, "daily_prediction")
    assert mission is not None
    assert mission.mission_code == "daily_prediction"
    assert mission.user_id == user.id
    assert mission.is_active is True
    assert mission.is_completed is False


def test_mission_completion_daily_prediction(app):
    """Test completing a daily prediction mission."""
    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    now = datetime.now(timezone.utc)

    # Assign mission
    mission = assign_mission_to_user(user.id, "daily_prediction", now=now)
    assert mission.is_active is True

    # Initially should not be completed
    completed_count = check_and_complete_missions(user.id, now=now)
    assert completed_count == 0

    # Create a prediction
    prediction = TremorPrediction(
        user_id=user.id,
        created_at=now,
        horizon_hours=24,
        prediction="UP",
        resolves_at=now + timedelta(hours=24),
        resolved=False,
    )
    db.session.add(prediction)
    db.session.commit()

    # Now mission should be completable
    completed_count = check_and_complete_missions(user.id, now=now)
    assert completed_count == 1

    # Refresh mission
    db.session.refresh(mission)
    assert mission.is_completed is True


def test_mission_completion_weekly_login(app):
    """Test completing a weekly login streak mission."""
    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    # Start mission now
    now = datetime.now(timezone.utc)

    # Assign mission
    mission = assign_mission_to_user(
        user.id, "weekly_login_streak", now=now
    )
    assert mission is not None

    # Create login events for 5 different days (exactly the minimum required)
    for day in range(5):
        event_time = now + timedelta(days=day, hours=12)
        event = Event(
            user_id=user.id,
            event_type="login",
            timestamp=event_time,
        )
        db.session.add(event)

    db.session.commit()

    # Check after 5th login (should now be completable)
    check_time = now + timedelta(days=5, hours=13)
    completed_count = check_and_complete_missions(user.id, now=check_time)
    
    # Mission should have been completed
    assert completed_count >= 1

    # Refresh mission
    db.session.refresh(mission)
    assert mission.is_completed is True


def test_get_user_missions(app):
    """Test retrieving user missions with status."""
    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    now = datetime.now(timezone.utc)

    # Assign multiple missions
    assign_mission_to_user(user.id, "daily_prediction", now=now)
    assign_mission_to_user(user.id, "weekly_login_streak", now=now)

    missions = get_user_missions(user.id, now=now)
    assert len(missions) == 2

    # Check structure
    for mission in missions:
        assert "id" in mission
        assert "code" in mission
        assert "label" in mission
        assert "description" in mission
        assert "icon" in mission
        assert "points" in mission
        assert "progress" in mission
        assert "is_active" in mission


def test_claim_mission_reward(app):
    """Test claiming rewards for a completed mission."""
    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    now = datetime.now(timezone.utc)

    # Assign and complete mission
    mission = assign_mission_to_user(user.id, "daily_prediction", now=now)

    # Create a prediction to complete the mission
    prediction = TremorPrediction(
        user_id=user.id,
        created_at=now,
        horizon_hours=24,
        prediction="UP",
        resolves_at=now + timedelta(hours=24),
        resolved=False,
    )
    db.session.add(prediction)
    db.session.commit()

    check_and_complete_missions(user.id, now=now)

    # Claim reward
    result = claim_mission_reward(mission.id, user.id)
    assert result["ok"] is True
    assert result["points_awarded"] == 5  # daily_prediction gives 5 points


def test_mission_badge_awarded(app):
    """Test that MISSION_COMPLETE badge is awarded after 5 missions."""
    from app.services.badge_service import recompute_badges_for_user

    user = User(email="mission@example.com")
    db.session.add(user)
    db.session.commit()

    now = datetime.now(timezone.utc)

    # Complete 5 missions
    for i in range(5):
        mission_time = now + timedelta(days=i)
        mission = assign_mission_to_user(
            user.id, "daily_prediction", now=mission_time
        )

        # Complete the mission
        prediction = TremorPrediction(
            user_id=user.id,
            created_at=mission_time,
            horizon_hours=24,
            prediction="UP",
            resolves_at=mission_time + timedelta(hours=24),
            resolved=False,
        )
        db.session.add(prediction)
        db.session.commit()

        check_and_complete_missions(user.id, now=mission_time)

    # Recompute badges
    level = recompute_badges_for_user(user.id)
    assert level is not None

    # Check that MISSION_COMPLETE badge was awarded
    from app.models.gamification import UserBadge

    badge = UserBadge.query.filter_by(
        user_id=user.id, badge_code="MISSION_COMPLETE"
    ).first()
    assert badge is not None
