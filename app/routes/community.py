"""Public routes dedicated to the community hub: blog, forum, feedback."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import current_user

from ..models import (
    db,
    BlogPost,
    ForumThread,
    ForumReply,
    UserFeedback,
)
from ..services.gamification_service import GamificationService
from ..utils.csrf import validate_csrf_token


bp = Blueprint("community", __name__, url_prefix="/community")


@bp.route("/blog/")
def blog_index():
    posts = (
        BlogPost.query.filter_by(published=True)
        .order_by(BlogPost.created_at.desc())
        .all()
    )
    return render_template("blog/index.html", posts=posts)


@bp.route("/blog/<slug>/")
def blog_detail(slug: str):
    post = BlogPost.query.filter_by(slug=slug).first_or_404()
    if not post.published and not (current_user.is_authenticated and current_user.is_admin):
        flash("L'articolo richiesto non è disponibile.", "error")
        return redirect(url_for("community.blog_index"))

    GamificationService().award("blog:read")
    db.session.commit()
    return render_template("blog/detail.html", post=post)


@bp.route("/forum/", methods=["GET", "POST"])
def forum_home():
    service = GamificationService()
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, ricarica la pagina.", "error")
            return redirect(url_for("community.forum_home"))

        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        author_name = (request.form.get("author_name") or "").strip() or None
        author_email = (request.form.get("author_email") or "").strip() or None

        if len(title) < 10 or len(body) < 20:
            flash("Fornisci un titolo e un messaggio più dettagliato.", "error")
            return redirect(url_for("community.forum_home"))

        thread = ForumThread(
            title=title,
            body=body,
            author_name=author_name,
            author_email=author_email,
        )
        thread.updated_at = datetime.utcnow()
        db.session.add(thread)
        service.award("forum:thread")
        db.session.commit()
        flash("Discussione pubblicata con successo!", "success")
        return redirect(url_for("community.thread_detail", slug=thread.slug))

    threads = (
        ForumThread.query.order_by(ForumThread.updated_at.desc()).limit(30).all()
    )
    return render_template("forum/index.html", threads=threads)


@bp.route("/forum/<slug>/", methods=["GET", "POST"])
def thread_detail(slug: str):
    thread = ForumThread.query.filter_by(slug=slug).first_or_404()
    service = GamificationService()

    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, riprova.", "error")
            return redirect(url_for("community.thread_detail", slug=slug))

        body = (request.form.get("body") or "").strip()
        author_name = (request.form.get("author_name") or "").strip() or None
        author_email = (request.form.get("author_email") or "").strip() or None

        if len(body) < 5:
            flash("Scrivi una risposta più completa.", "error")
            return redirect(url_for("community.thread_detail", slug=slug))

        reply = ForumReply(
            thread_id=thread.id,
            body=body,
            author_name=author_name,
            author_email=author_email,
        )
        db.session.add(reply)
        thread.status = "resolved" if request.form.get("mark_resolved") == "1" else thread.status
        thread.updated_at = datetime.utcnow()
        service.award("forum:reply")
        db.session.commit()
        flash("Risposta pubblicata!", "success")
        return redirect(url_for("community.thread_detail", slug=slug) + "#replies")

    replies = (
        ForumReply.query.filter_by(thread_id=thread.id)
        .order_by(ForumReply.created_at.asc())
        .all()
    )
    return render_template("forum/thread_detail.html", thread=thread, replies=replies)


@bp.route("/feedback/", methods=["GET", "POST"])
def feedback_portal():
    service = GamificationService()
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, ricarica la pagina.", "error")
            return redirect(url_for("community.feedback_portal"))

        rating = int(request.form.get("rating", 0))
        comment = (request.form.get("comment") or "").strip()
        category = (request.form.get("category") or "").strip() or None
        display_name = (request.form.get("display_name") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None

        if rating not in {1, 2, 3, 4, 5} or len(comment) < 10:
            flash("Valutazione o commento non validi.", "error")
            return redirect(url_for("community.feedback_portal"))

        feedback = UserFeedback(
            rating=rating,
            comment=comment,
            category=category,
            display_name=display_name,
            email=email,
        )
        db.session.add(feedback)
        service.award("feedback:new")
        db.session.commit()
        flash("Grazie per il tuo feedback!", "success")
        return redirect(url_for("community.feedback_portal"))

    latest_feedback = (
        UserFeedback.query.filter(UserFeedback.status != "archived")
        .order_by(UserFeedback.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template("feedback/index.html", latest_feedback=latest_feedback)
