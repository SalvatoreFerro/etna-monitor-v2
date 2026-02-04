from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import case, func

from app.models import db
from app.models.tremor_prediction import TremorPrediction
from app.models.user import User
from app.services.prediction_service import (
    PREDICTION_CHOICES,
    PREDICTION_HORIZONS,
    PREDICTION_HORIZON_HOURS,
)
from app.utils.auth import get_current_user
from app.utils.csrf import validate_csrf_token
from app.services.mission_service import record_daily_event

bp = Blueprint("predictions", __name__)


def _display_name(user: User) -> str:
    if user.name:
        return user.name
    if user.email:
        return user.email
    return f"Utente {user.id}"


def _fetch_leaderboard(limit: int) -> list[dict]:
    points_sum = func.coalesce(func.sum(TremorPrediction.points_awarded), 0)
    correct_count = func.coalesce(
        func.sum(case((TremorPrediction.points_awarded > 0, 1), else_=0)),
        0,
    )
    prediction_count = func.count(TremorPrediction.id)

    rows = (
        db.session.query(User, points_sum.label("points"), correct_count.label("correct"), prediction_count.label("total"))
        .join(TremorPrediction, TremorPrediction.user_id == User.id)
        .filter(TremorPrediction.resolved.is_(True))
        .group_by(User.id)
        .order_by(points_sum.desc(), correct_count.desc(), prediction_count.desc())
        .limit(limit)
        .all()
    )

    leaderboard = []
    for idx, (user, points, correct, total) in enumerate(rows, start=1):
        leaderboard.append(
            {
                "rank": idx,
                "name": _display_name(user),
                "points": int(points or 0),
                "correct": int(correct or 0),
                "total": int(total or 0),
            }
        )
    return leaderboard


@bp.post("/api/predictions")
def create_prediction():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    payload = request.get_json(silent=True) or request.form
    prediction = str(payload.get("prediction") or "").upper().strip()
    csrf_token = payload.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        return jsonify({"ok": False, "error": "invalid_csrf"}), 400

    if prediction not in PREDICTION_CHOICES:
        return jsonify({"ok": False, "error": "invalid_prediction"}), 400

    # Extract and validate horizon_hours
    horizon_hours = payload.get("horizon_hours")
    if horizon_hours is None:
        horizon_hours = PREDICTION_HORIZON_HOURS  # Default to 24
    else:
        try:
            horizon_hours = int(horizon_hours)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "invalid_horizon"}), 400

    if horizon_hours not in PREDICTION_HORIZONS:
        return jsonify(
            {
                "ok": False,
                "error": "invalid_horizon",
                "valid_horizons": PREDICTION_HORIZONS,
            }
        ), 400

    existing = (
        TremorPrediction.query.filter(
            TremorPrediction.user_id == user.id,
            TremorPrediction.resolved.is_(False),
            TremorPrediction.horizon_hours == horizon_hours,
        )
        .order_by(TremorPrediction.created_at.desc())
        .first()
    )
    if existing:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "active_prediction_exists",
                    "resolves_at": existing.resolves_at.isoformat(),
                }
            ),
            409,
        )

    created_at = datetime.now(timezone.utc)
    resolves_at = created_at + timedelta(hours=horizon_hours)

    prediction_row = TremorPrediction(
        user_id=user.id,
        created_at=created_at,
        horizon_hours=horizon_hours,
        prediction=prediction,
        resolves_at=resolves_at,
        resolved=False,
    )
    db.session.add(prediction_row)
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "prediction": prediction_row.prediction,
            "resolves_at": prediction_row.resolves_at.isoformat(),
            "horizon_hours": prediction_row.horizon_hours,
        }
    )


@bp.get("/api/leaderboard")
def leaderboard_api():
    limit = request.args.get("limit", type=int) or 20
    limit = max(1, min(limit, 100))
    leaderboard = _fetch_leaderboard(limit)
    return jsonify({"ok": True, "leaderboard": leaderboard, "limit": limit})


@bp.get("/leaderboard")
def leaderboard_page():
    leaderboard = _fetch_leaderboard(20)
    user = get_current_user()
    enable_missions = os.getenv("ENABLE_MISSIONS", "").strip().lower()
    if user and enable_missions in {"1", "true", "yes"}:
        record_daily_event(user.id, "leaderboard_view")
    return render_template(
        "leaderboard.html",
        leaderboard=leaderboard,
        page_title="Prediction Game – Classifica",
        page_description="Classifica Prediction Game EtnaMonitor con top 20 e punti accumulati.",
    )
