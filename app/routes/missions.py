"""Missions blueprint for gamification system."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from app.services.mission_service import (
    check_and_complete_missions,
    claim_mission_reward,
    get_user_missions,
)
from app.utils.auth import get_current_user
from app.utils.csrf import validate_csrf_token

bp = Blueprint("missions", __name__)


def _is_missions_enabled() -> bool:
    """Check if missions feature is enabled."""
    enable_missions = os.getenv("ENABLE_MISSIONS", "").strip().lower()
    return enable_missions in {"1", "true", "yes"}


@bp.get("/api/missions")
def list_missions():
    """Get all missions for the current user."""
    if not _is_missions_enabled():
        return jsonify({"ok": False, "error": "feature_disabled"}), 404

    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    # Check and auto-complete any missions that are now eligible
    check_and_complete_missions(user.id)

    missions = get_user_missions(user.id, include_expired=False)
    return jsonify({"ok": True, "missions": missions})


@bp.post("/api/missions/<int:mission_id>/claim")
def claim_mission(mission_id: int):
    """Claim rewards for a completed mission."""
    if not _is_missions_enabled():
        return jsonify({"ok": False, "error": "feature_disabled"}), 404

    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    # Validate CSRF token
    payload = request.get_json(silent=True) or request.form
    csrf_token = payload.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        return jsonify({"ok": False, "error": "invalid_csrf"}), 400

    result = claim_mission_reward(mission_id, user.id)

    if not result.get("ok"):
        error = result.get("error", "unknown_error")
        if error in {"mission_not_found", "invalid_mission_code"}:
            return jsonify(result), 404
        elif error == "unauthorized":
            return jsonify(result), 403
        elif error == "mission_not_completed":
            return jsonify(result), 400
        else:
            return jsonify(result), 500

    return jsonify(result), 200
