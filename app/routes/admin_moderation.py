"""Moderation queue for community posts."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..models import CommunityPost, ModerationAction, db
from ..services.email_service import send_email
from ..utils.acl import role_required
from ..utils.csrf import validate_csrf_token
from ..utils.sanitize import summarize_removed_elements

bp = Blueprint("moderation", __name__, url_prefix="/admin/moderation")


def _notify_author(post: CommunityPost, template: str, reason: str | None) -> None:
    author = post.author
    if not author or not author.email:
        return
    post_url = url_for("community.community_post", identifier=post.slug, _external=True)
    send_email(
        subject=f"Aggiornamento post: {post.title}",
        recipients=[author.email],
        template_prefix=template,
        context={"post": post, "reason": reason, "post_url": post_url},
    )


@bp.route("/queue", methods=["GET"])
@login_required
@role_required("moderator", "admin")
def moderation_queue():
    pending_posts = (
        CommunityPost.query.filter(
            CommunityPost.status.in_(["pending", "draft", "hidden"])
        )
        .order_by(CommunityPost.created_at.asc())
        .all()
    )
    for post in pending_posts:
        post.sanitization_warnings = summarize_removed_elements(
            post.body, post.body_html_sanitized
        )
    return render_template("admin/moderation_queue.html", posts=pending_posts)


def _moderate(post_id: int, action: str, reason: str | None) -> bool:
    post = CommunityPost.query.get_or_404(post_id)
    if (
        post.status not in {"pending", "draft", "rejected", "hidden"}
        and action != "reject"
    ):
        abort(400)
    moderator_id = current_user.id
    now = datetime.now(timezone.utc)

    if action == "approve":
        if post.has_suspicious_html():
            post.hide(moderator_id, "XSS sanitization")
            post.body_html_sanitized = post.sanitize_body(post.body)
            post.moderator_reason = "XSS sanitization"
            auto_action = ModerationAction(
                post_id=post.id,
                moderator_id=moderator_id,
                action="auto_hide_xss",
                reason="XSS sanitization",
                created_at=now,
            )
            db.session.add(auto_action)
            db.session.add(post)
            db.session.commit()
            return False
        post.publish(moderator_id, reason)
    elif action == "reject":
        post.reject(moderator_id, reason)
    else:
        abort(400)

    moderation_entry = ModerationAction(
        post_id=post.id,
        moderator_id=moderator_id,
        action=action,
        reason=reason,
        created_at=now,
    )
    db.session.add(moderation_entry)
    db.session.add(post)
    db.session.commit()

    template = "post_approved" if action == "approve" else "post_rejected"
    _notify_author(post, template, reason)

    return True


@bp.route("/approve/<int:post_id>", methods=["POST"])
@login_required
@role_required("moderator", "admin")
def approve_post(post_id: int):
    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta.", "error")
        return redirect(url_for("moderation.moderation_queue"))

    reason = (request.form.get("reason") or "").strip() or None
    approved = _moderate(post_id, "approve", reason)
    if approved:
        flash("Post approvato con successo.", "success")
    else:
        flash(
            "Markup sospetto rilevato: il post è stato nascosto automaticamente.",
            "error",
        )
    return redirect(url_for("moderation.moderation_queue"))


@bp.route("/reject/<int:post_id>", methods=["POST"])
@login_required
@role_required("moderator", "admin")
def reject_post(post_id: int):
    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta.", "error")
        return redirect(url_for("moderation.moderation_queue"))

    reason = (request.form.get("reason") or "").strip() or None
    _moderate(post_id, "reject", reason)
    flash("Post rifiutato.", "info")
    return redirect(url_for("moderation.moderation_queue"))


def register_rate_limits(app) -> None:
    limiter = app.extensions.get("limiter")
    if not limiter:
        return

    limiter.limit("10/minute")(approve_post)
    limiter.limit("10/minute")(reject_post)


__all__ = ["bp", "register_rate_limits"]
