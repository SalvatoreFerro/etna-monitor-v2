"""Public routes dedicated to the community hub: blog, forum, feedback."""

from __future__ import annotations

from datetime import datetime, timezone

import requests
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..models import (
    db,
    BlogPost,
    CommunityPost,
    ForumThread,
    ForumReply,
    ModerationAction,
    UserFeedback,
)
from ..services.gamification_service import GamificationService
from ..utils.csrf import validate_csrf_token
from ..utils.acl import role_required


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
    if not post.published and not (
        current_user.is_authenticated and current_user.is_admin
    ):
        flash("L'articolo richiesto non è disponibile.", "error")
        return redirect(url_for("community.blog_index"))

    GamificationService().award("blog:read")
    db.session.commit()

    related_posts = (
        BlogPost.query.filter(
            BlogPost.published.is_(True),
            BlogPost.id != post.id,
        )
        .order_by(BlogPost.created_at.desc())
        .limit(3)
        .all()
    )

    previous_post = (
        BlogPost.query.filter(
            BlogPost.published.is_(True),
            BlogPost.created_at < post.created_at,
        )
        .order_by(BlogPost.created_at.desc())
        .first()
    )

    next_post = (
        BlogPost.query.filter(
            BlogPost.published.is_(True),
            BlogPost.created_at > post.created_at,
        )
        .order_by(BlogPost.created_at.asc())
        .first()
    )

    author_name = getattr(post, "author", None) or getattr(post, "author_name", None)
    post_url = url_for("community.blog_detail", slug=post.slug, _external=True)

    breadcrumb_schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": url_for("main.index", _external=True),
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Community",
                "item": url_for("community.forum_home", _external=True),
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": "Blog",
                "item": url_for("community.blog_index", _external=True),
            },
            {
                "@type": "ListItem",
                "position": 4,
                "name": post.title,
                "item": post_url,
            },
        ],
    }

    return render_template(
        "blog/detail.html",
        post=post,
        author_name=author_name,
        related_posts=related_posts,
        previous_post=previous_post,
        next_post=next_post,
        breadcrumb_schema=breadcrumb_schema,
    )


@bp.route("/forum/", methods=["GET", "POST"])
def forum_home():
    service = GamificationService()
    display_name, author_email = _resolve_forum_identity(current_user) if current_user.is_authenticated else (None, None)

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Devi effettuare l'accesso per aprire una discussione.", "error")
            login_url = url_for("auth.login", next=request.url)
            return redirect(login_url)

        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, ricarica la pagina.", "error")
            return redirect(url_for("community.forum_home"))

        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        author_name = display_name

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

    threads = ForumThread.query.order_by(ForumThread.updated_at.desc()).limit(30).all()
    return render_template("forum/index.html", threads=threads, display_name=display_name)


@bp.route("/forum/<slug>/", methods=["GET", "POST"])
def thread_detail(slug: str):
    thread = ForumThread.query.filter_by(slug=slug).first_or_404()
    service = GamificationService()

    display_name, author_email = _resolve_forum_identity(current_user) if current_user.is_authenticated else (None, None)

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Accedi per partecipare alla discussione.", "error")
            login_url = url_for("auth.login", next=request.url)
            return redirect(login_url)

        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, riprova.", "error")
            return redirect(url_for("community.thread_detail", slug=slug))

        body = (request.form.get("body") or "").strip()
        author_name = display_name

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
        thread.status = (
            "resolved" if request.form.get("mark_resolved") == "1" else thread.status
        )
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
    return render_template(
        "forum/thread_detail.html",
        thread=thread,
        replies=replies,
        display_name=display_name,
    )


def _resolve_forum_identity(user) -> tuple[str, str | None]:
    """Return the immutable identity used for forum contributions."""

    if not getattr(user, "is_authenticated", False):
        return ("", None)

    raw_name = (getattr(user, "name", None) or "").strip()
    email = (getattr(user, "email", None) or "").strip() or None

    if raw_name:
        display_name = raw_name
    elif email:
        display_name = email.split("@")[0]
    else:
        display_name = "Membro EtnaMonitor"

    return display_name, email


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


def _require_captcha(user) -> bool:
    if not current_app.config.get("COMMUNITY_RECAPTCHA_ENABLED"):
        return False
    if getattr(user, "is_authenticated", False):
        if user.is_moderator() or user.has_premium_access:
            return False
        optional = current_app.config.get("OPTIONAL_CAPTCHA_FOR_UNVERIFIED", True)
        if optional:
            return not bool(user.telegram_opt_in or user.google_id)
    return True


def _verify_recaptcha(response_token: str) -> bool:
    if not current_app.config.get("COMMUNITY_RECAPTCHA_ENABLED"):
        return True
    secret = current_app.config.get("COMMUNITY_RECAPTCHA_SECRET_KEY")
    if not secret or not response_token:
        return False
    try:
        verification = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": secret, "response": response_token},
            timeout=5,
        )
    except Exception:
        current_app.logger.warning("reCAPTCHA verification failed", exc_info=True)
        return False
    if verification.status_code != 200:
        return False
    payload = verification.json()
    return bool(payload.get("success"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_post():
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not validate_csrf_token(csrf_token):
            flash("Sessione scaduta, riprova.", "error")
            return redirect(url_for("community.create_post"))

        if _require_captcha(current_user):
            captcha_token = request.form.get("g-recaptcha-response", "")
            if not _verify_recaptcha(captcha_token):
                flash("Verifica captcha non riuscita.", "error")
                return redirect(url_for("community.create_post"))

        title = (request.form.get("title") or "").strip()
        body = request.form.get("body") or ""
        anonymous = request.form.get("anonymous") == "1"

        if len(title) < 10 or len(body) < 30:
            flash("Completa titolo e contenuto (minimo 30 caratteri).", "error")
            return redirect(url_for("community.create_post"))

        post = CommunityPost(
            author_id=current_user.id, title=title, anonymous=anonymous
        )
        suspicious_matches = post.set_body(body)
        post.status = "pending"
        db.session.add(post)

        if suspicious_matches:
            post.status = "hidden"
            post.moderator_reason = "XSS sanitization"
            post.moderated_at = datetime.now(timezone.utc)
            moderation_entry = ModerationAction(
                post=post,
                moderator_id=None,
                action="auto_hide_xss",
                reason="XSS sanitization",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(moderation_entry)
            flash(
                "Il contenuto include markup non consentito ed è stato inviato alla revisione manuale.",
                "warning",
            )
        else:
            flash("Post inviato, sarà pubblicato dopo la moderazione.", "success")

        db.session.commit()
        return redirect(url_for("community.my_posts"))

    return render_template(
        "community/new.html",
        require_captcha=_require_captcha(current_user),
        recaptcha_site_key=current_app.config.get("COMMUNITY_RECAPTCHA_SITE_KEY"),
    )


def _get_post_by_identifier(identifier: str) -> CommunityPost:
    post: CommunityPost | None = None
    if identifier.isdigit():
        post = CommunityPost.query.get(int(identifier))
    if not post:
        post = CommunityPost.query.filter_by(slug=identifier).first()
    if not post:
        abort(404)
    return post


@bp.route("/my-posts", methods=["GET"])
@login_required
def my_posts():
    posts = (
        CommunityPost.query.filter_by(author_id=current_user.id)
        .order_by(CommunityPost.created_at.desc())
        .all()
    )
    return render_template("community/my_posts.html", posts=posts)


@bp.route("/<identifier>", methods=["GET"])
def community_post(identifier: str):
    post = _get_post_by_identifier(identifier)
    viewer = current_user if current_user.is_authenticated else None
    if not post.is_visible_to(viewer):
        abort(404)

    actions = (
        ModerationAction.query.filter_by(post_id=post.id)
        .order_by(ModerationAction.created_at.desc())
        .all()
    )

    return render_template(
        "community/post.html",
        post=post,
        actions=actions,
    )
