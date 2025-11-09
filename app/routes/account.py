"""Account management endpoints (export, deletion, lifecycle)."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..models import CommunityPost, ModerationAction, User, db
from ..services.email_service import send_email
from ..utils.csrf import validate_csrf_token

bp = Blueprint("account", __name__, url_prefix="/account")


def _serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config["SECRET_KEY"]
    salt = "account-delete"
    return URLSafeTimedSerializer(secret_key, salt=salt)


def _generate_delete_token(user: User) -> str:
    serializer = _serializer()
    return serializer.dumps({"user_id": user.id})


def _load_delete_token(token: str) -> User | None:
    serializer = _serializer()
    max_age = current_app.config.get("ACCOUNT_DELETE_TOKEN_MAX_AGE", 172800)
    try:
        payload = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    user_id = payload.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


@bp.route("/delete-request", methods=["POST"])
@login_required
def delete_request():
    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta, riprova.", "error")
        return redirect(url_for("dashboard.settings"))

    token = _generate_delete_token(current_user)
    confirm_url = url_for("account.delete_confirm", token=token, _external=True)

    send_email(
        subject="Conferma eliminazione account",
        recipients=[current_user.email],
        template_prefix="account_delete_request",
        context={
            "user": current_user,
            "confirm_url": confirm_url,
        },
    )

    flash(
        "Abbiamo inviato un'email con il link per confermare l'eliminazione.",
        "success",
    )
    return redirect(url_for("dashboard.settings"))


@bp.route("/delete-confirm/<token>", methods=["GET"])
def delete_confirm(token: str):
    user = _load_delete_token(token)
    if not user:
        flash("Link non valido o scaduto.", "error")
        return render_template("account/delete_confirm_failed.html"), 400

    if not user.deleted_at:
        user.soft_delete()
        user.anonymize()
        db.session.add(user)
        db.session.commit()
        logout_user()
        current_app.logger.info("User %s scheduled for deletion", user.id)

    ttl_days = current_app.config.get("ACCOUNT_SOFT_DELETE_TTL_DAYS", 30)
    purge_at = user.purge_deadline(ttl_days)

    return render_template(
        "account/delete_confirm_success.html",
        purge_at=purge_at,
    )


@bp.route("/export-data", methods=["GET"])
@login_required
def export_data():
    user: User = current_user  # type: ignore[assignment]

    posts = [
        post.to_export() for post in user.posts.order_by(CommunityPost.created_at.asc())
    ]
    moderated = [
        {
            "post_id": action.post_id,
            "action": action.action,
            "reason": action.reason,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }
        for action in ModerationAction.query.filter_by(moderator_id=user.id)
        .order_by(ModerationAction.created_at.desc())
        .all()
    ]

    payload = {
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "plan_type": user.plan_type,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "settings": {
                "threshold": user.threshold,
                "email_alerts": user.email_alerts,
                "theme_preference": user.theme_preference,
            },
        },
        "posts": posts,
        "moderation_actions": moderated,
    }

    return jsonify(payload)


def register_rate_limits(app) -> None:
    limiter = app.extensions.get("limiter")
    if not limiter:
        return

    limiter.limit("3/hour")(delete_request)
    limiter.limit("30/hour")(export_data)


__all__ = ["bp", "register_rate_limits"]
