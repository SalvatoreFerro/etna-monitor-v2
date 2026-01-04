import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    flash,
    redirect,
    url_for,
    make_response,
    current_app,
)
from flask_login import current_user
from sqlalchemy import and_, cast, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..utils.auth import admin_required, get_current_user
from ..utils.metrics import get_csv_metrics
from ..models import (
    db,
    BlogPost,
    MediaAsset,
    UserFeedback,
    AdminActionLog,
    CommunityPost,
    ForumThread,
    ForumReply,
    CronRunLog,
)
from ..models.user import User
from ..models.event import Event
from ..models.billing import EventLog
from ..models.premium_request import PremiumRequest
from ..models.partner import (
    PARTNER_STATUSES,
    Partner,
    PartnerCategory,
    PartnerSubscription,
)
from ..services.gamification_service import ensure_demo_profiles
from ..services.partner_categories import (
    CATEGORY_FORM_FIELDS,
    ensure_partner_categories,
    ensure_partner_category_fk,
    ensure_partner_extra_data_column,
    ensure_partner_slug_column,
    ensure_partner_subscriptions_table,
    missing_table_error,
    missing_column_error,
    serialize_category_fields,
)
from ..services.partner_directory import (
    can_approve_partner,
    create_subscription,
    generate_invoice_pdf,
    slots_usage,
)
from ..utils.partners import build_partner_media_url, next_partner_slug

try:
    from ..models.sponsor_banner import (
        SponsorBanner,
        SponsorBannerClick,
        SponsorBannerImpression,
    )
except Exception:  # pragma: no cover - optional dependency guard
    SponsorBanner = None  # type: ignore
    SponsorBannerClick = None  # type: ignore
    SponsorBannerImpression = None  # type: ignore
from ..services.telegram_service import TelegramService
from ..utils.csrf import validate_csrf_token
from ..filters import render_markdown, strip_literal_breaks
from ..services.email_service import send_email
from ..services.ai_writer import generate_ai_article
from ..services.media_library import (
    configure_cloudinary,
    upload_media_asset,
    validate_media_file,
)

bp = Blueprint("admin", __name__)


def _is_csrf_valid(submitted_token: str | None) -> bool:
    """Return True when the provided CSRF token is valid or tests are running."""
    if validate_csrf_token(submitted_token):
        return True
    return bool(current_app.config.get("TESTING"))


def _parse_date_param(value, default):
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


def _parse_datetime_local(value: str | None) -> datetime | None:
    """Parse datetime-local input values from the admin forms."""

    if not value:
        return None
    try:
        # Admin inputs are stored as naive UTC timestamps for simplicity.
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_tracking_filters(query, model, start_dt, end_dt, banner_id, page_filter):
    if start_dt:
        query = query.filter(model.ts >= start_dt)
    if end_dt:
        query = query.filter(model.ts <= end_dt)
    if banner_id:
        query = query.filter(model.banner_id == banner_id)
    if page_filter:
        like_value = f"%{page_filter.lower()}%"
        query = query.filter(model.page.isnot(None))
        query = query.filter(func.lower(model.page).like(like_value))
    return query


def _normalize_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return value


def _coerce_int(value, *, default: int, minimum: int = 0, maximum: int = 500) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _coerce_bool_param(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _serialize_partner(partner: Partner) -> dict:
    return {
        "id": partner.id,
        "name": partner.name,
        "category": partner.category,
        "category_label": partner.category_label(),
        "verified": bool(partner.verified),
        "visible": bool(partner.visible),
        "website": partner.website,
    }


ADMIN_USERS_PER_PAGE = 20

_ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_ALLOWED_LOGO_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}


def _validate_partner_logo(
    file_storage: FileStorage | None,
    *,
    max_bytes: int,
) -> tuple[bool, str | None, str | None]:
    if not file_storage or not file_storage.filename:
        return False, None, None

    filename = secure_filename(file_storage.filename)
    if not filename:
        return False, "Nome file non valido.", None

    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_LOGO_EXTENSIONS:
        return False, "Formato immagine non supportato.", None

    mimetype = (file_storage.mimetype or "").lower()
    if mimetype and mimetype not in _ALLOWED_LOGO_MIME_TYPES:
        return False, "Tipo immagine non supportato.", None

    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)

    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        return False, f"File troppo grande. Limite: {max_mb:.1f}MB.", None

    return True, None, extension


def _store_partner_logo(
    file_storage: FileStorage | None,
    *,
    slug: str,
    max_bytes: int,
) -> tuple[str | None, str | None]:
    """Persist the uploaded partner logo to the static directory.

    Returns a tuple of (relative_path, error_message).
    """

    is_valid, error, extension = _validate_partner_logo(file_storage, max_bytes=max_bytes)
    if not is_valid:
        return None, error
    if not extension:
        return None, None

    static_folder = Path(current_app.static_folder or "static")
    upload_dir = static_folder / "images" / "partners"
    upload_dir.mkdir(parents=True, exist_ok=True)

    unique_id = uuid4().hex
    stored_name = f"{slug}-{unique_id}{extension}"
    destination = upload_dir / stored_name

    file_storage.stream.seek(0)
    file_storage.save(destination)

    relative_path = Path("images") / "partners" / stored_name
    return relative_path.as_posix(), None


def _get_admin_ip() -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr


def _log_admin_action(
    action: str,
    *,
    target_user: User | None = None,
    target_email: str | None = None,
    status: str = "success",
    message: str | None = None,
    details: dict | None = None,
) -> None:
    """Persist an admin action log without interrupting the request flow."""

    admin_id = current_user.id if current_user.is_authenticated else None
    admin_email = current_user.email if current_user.is_authenticated else None
    entry = AdminActionLog(
        action=action,
        status=status,
        message=message,
        admin_id=admin_id,
        admin_email=admin_email,
        target_user_id=target_user.id if target_user else None,
        target_email=target_email or (target_user.email if target_user else None),
        ip_address=_get_admin_ip(),
        context=details,
    )

    try:
        db.session.add(entry)
        db.session.commit()
    except Exception:  # pragma: no cover - defensive logging
        db.session.rollback()
        current_app.logger.exception("Failed to store admin action log")


def _coerce_positive_int(raw_value, *, default: int = 1) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _build_users_query(search_term: str | None, plan_filter: str | None):
    query = User.query

    if search_term:
        normalized = f"%{search_term.strip().lower()}%"
        query = query.filter(func.lower(User.email).like(normalized))

    plan = (plan_filter or "all").lower()
    premium_clause = User.premium_status_clause()

    if plan == "premium":
        query = query.filter(premium_clause)
    elif plan == "free":
        query = query.filter(~premium_clause)
    elif plan == "admin":
        query = query.filter(User.is_admin.is_(True))

    return query.order_by(User.created_at.desc())


def _serialize_user_for_admin(user: User) -> dict:
    chat_id = user.telegram_chat_id or user.chat_id
    return {
        "id": user.id,
        "email": user.email,
        "plan": user.current_plan,
        "has_premium": bool(user.has_premium_access),
        "is_admin": bool(user.is_admin),
        "threshold": user.threshold,
        "chat_id": chat_id,
        "telegram_chat_id": user.telegram_chat_id,
        "telegram_opt_in": bool(user.telegram_opt_in),
        "free_alert_consumed": int(user.free_alert_consumed or 0),
    }


@bp.route("/")
@admin_required
def admin_home():
    ensure_demo_profiles()
    search_query = (request.args.get("q") or "").strip()
    plan_filter = (request.args.get("plan") or "all").lower()
    page = _coerce_positive_int(request.args.get("page"), default=1)

    users_query = _build_users_query(search_query, plan_filter)
    pagination = users_query.paginate(
        page=page, per_page=ADMIN_USERS_PER_PAGE, error_out=False
    )

    initial_users = [_serialize_user_for_admin(user) for user in pagination.items]

    post_status_counts = {
        status: count
        for status, count in db.session.query(
            CommunityPost.status, func.count(CommunityPost.id)
        )
        .group_by(CommunityPost.status)
        .all()
    }
    pending_post_count = post_status_counts.get("pending", 0)
    draft_post_count = post_status_counts.get("draft", 0)

    feedback_new_count = (
        db.session.query(func.count(UserFeedback.id))
        .filter(UserFeedback.status == "new")
        .scalar()
        or 0
    )

    pending_donations_count = (
        db.session.query(func.count(User.id))
        .filter(
            User.donation_tx.isnot(None),
            User.donation_tx != "",
            User.is_premium.is_(False),
            User.premium.is_(False),
        )
        .scalar()
        or 0
    )

    pending_premium_requests_count = (
        db.session.query(func.count(PremiumRequest.id))
        .filter(PremiumRequest.status == "pending")
        .scalar()
        or 0
    )

    soft_deleted_count = (
        db.session.query(func.count(User.id))
        .filter(User.deleted_at.isnot(None), User.erased_at.is_(None))
        .scalar()
        or 0
    )

    moderators_count = (
        db.session.query(func.count(User.id)).filter(User.role == "moderator").scalar()
        or 0
    )

    admin_shortcuts = [
        {
            "label": "Gestione utenti",
            "description": "Aggiorna piani, resetta prove e controlla gli alert.",
            "icon": "fa-users-cog",
            "url": url_for("admin.admin_home"),
        },
        {
            "label": "Moderazione community",
            "description": "Approva o rifiuta i contributi degli utenti.",
            "icon": "fa-comments",
            "url": url_for("moderation.moderation_queue"),
            "badge": pending_post_count + draft_post_count,
            "badge_label": "Post in coda",
        },
        {
            "label": "Gestione blog",
            "description": "Pubblica articoli ufficiali e comunicazioni.",
            "icon": "fa-newspaper",
            "url": url_for("admin.blog_manager"),
        },
        {
            "label": "Media Library",
            "description": "Carica immagini su Cloudinary e copia URL pronti per gli articoli.",
            "icon": "fa-images",
            "url": url_for("admin.media_library"),
        },
        {
            "label": "AI Writer",
            "description": "Genera bozze editoriali da revisionare prima della pubblicazione.",
            "icon": "fa-robot",
            "url": url_for("admin.ai_writer"),
        },
        {
            "label": "Forum Q&A",
            "description": "Gestisci discussioni e risposte della community.",
            "icon": "fa-people-group",
            "url": url_for("admin.forum_manager"),
        },
        {
            "label": "Feedback utenti",
            "description": "Esamina e rispondi ai feedback ricevuti.",
            "icon": "fa-comment-dots",
            "url": url_for("admin.feedback_center"),
            "badge": feedback_new_count,
            "badge_label": "Feedback nuovi",
        },
        {
            "label": "Donazioni",
            "description": "Verifica ricevute e sblocca gli account premium.",
            "icon": "fa-donate",
            "url": url_for("admin.donations"),
            "badge": pending_donations_count,
            "badge_label": "Da validare",
        },
        {
            "label": "Richieste Premium",
            "description": "Gestisci richieste Premium Lifetime e stato approvazioni.",
            "icon": "fa-star",
            "url": url_for("admin.premium_requests"),
            "badge": pending_premium_requests_count,
            "badge_label": "Pending",
        },
        {
            "label": "Partner Experience",
            "description": "Gestisci partner, offerte e visibilità.",
            "icon": "fa-handshake",
            "url": url_for("admin.partners_dashboard"),
        },
    ]

    if SponsorBanner is not None:
        admin_shortcuts.append(
            {
                "label": "Banner sponsor",
                "description": "Configura campagne e creatività attive.",
                "icon": "fa-image",
                "url": url_for("admin.banner_list"),
            }
        )
        admin_shortcuts.append(
            {
                "label": "Sponsor analytics",
                "description": "Analizza impression e click delle campagne.",
                "icon": "fa-chart-line",
                "url": url_for("admin.sponsor_analytics"),
            }
        )

    admin_shortcuts.append(
        {
            "label": "Theme manager",
            "description": "Personalizza l'aspetto pubblico del sito.",
            "icon": "fa-palette",
            "url": url_for("admin.theme_manager"),
        }
    )
    admin_shortcuts.append(
        {
            "label": "Lifecycle account",
            "description": "Monitora richieste GDPR e account in eliminazione.",
            "icon": "fa-user-slash",
            "url": url_for("admin.admin_home", _anchor="account-lifecycle"),
            "badge": soft_deleted_count,
            "badge_label": "In coda purge",
        }
    )

    csv_metrics = get_csv_metrics()

    return render_template(
        "admin.html",
        users=pagination.items,
        initial_users=initial_users,
        total_users=pagination.total,
        page=page,
        pages=pagination.pages,
        plan_filter=plan_filter,
        search_query=search_query,
        per_page=ADMIN_USERS_PER_PAGE,
        pending_post_count=pending_post_count,
        draft_post_count=draft_post_count,
        feedback_new_count=feedback_new_count,
        pending_donations_count=pending_donations_count,
        soft_deleted_count=soft_deleted_count,
        moderators_count=moderators_count,
        admin_shortcuts=admin_shortcuts,
        csv_metrics=csv_metrics,
    )


@bp.route("/ai-writer", methods=["GET", "POST"])
@admin_required
def ai_writer():
    form_values = {
        "topic": (request.form.get("topic") or "").strip(),
        "main_keyword": (request.form.get("main_keyword") or "").strip(),
        "target_length": (request.form.get("target_length") or "medium").strip(),
        "tone": (request.form.get("tone") or "neutro").strip(),
    }
    generated_markdown: str | None = None

    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not _is_csrf_valid(csrf_token):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.ai_writer"))

        if not form_values["topic"] or not form_values["main_keyword"]:
            flash("Compila almeno argomento e keyword principale.", "error")
            return render_template(
                "admin/ai_writer.html",
                form_values=form_values,
                generated_markdown=generated_markdown,
            )

        article = None
        try:
            article = generate_ai_article(
                form_values["topic"],
                form_values["main_keyword"],
                form_values["target_length"],
                form_values["tone"],
            )
        except Exception as exc:
            current_app.logger.exception("AI Writer failure: %s", exc)
            flash(
                "Errore nella generazione dell'articolo. Controlla la chiave OPENAI_API_KEY o riprova.",
                "error",
            )
        else:
            if not article:
                current_app.logger.error("AI Writer returned an empty article payload")
                flash(
                    "Errore nella generazione dell'articolo. Controlla la chiave OPENAI_API_KEY o riprova.",
                    "error",
                )
            else:
                generated_markdown = article["markdown"]
                summary = article.get("meta_description") or None
                post = BlogPost(
                    title=article.get("title") or form_values["topic"],
                    summary=summary,
                    content=generated_markdown,
                    meta_title=article.get("meta_title") or None,
                    meta_description=summary,
                    seo_title=article.get("meta_title") or None,
                    seo_description=summary,
                    published=False,
                )
                try:
                    db.session.add(post)
                    db.session.commit()
                    flash(
                        "Bozza generata con successo. Revisiona e pubblica dall'editor del blog.",
                        "success",
                    )
                    return redirect(url_for("admin.blog_manager"))
                except SQLAlchemyError:
                    db.session.rollback()
                    flash("Errore nel salvataggio della bozza. Riprova.", "error")

    return render_template(
        "admin/ai_writer.html",
        form_values=form_values,
        generated_markdown=generated_markdown,
    )


@bp.route("/blog", methods=["GET", "POST"])
@admin_required
def blog_manager():
    ensure_demo_profiles()
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not _is_csrf_valid(csrf_token):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.blog_manager"))

        action = request.form.get("action") or ""

        if action == "create":
            title = (request.form.get("title") or "").strip()
            content_raw = (request.form.get("content") or "").strip()
            content = strip_literal_breaks(content_raw).strip()
            if not title or not content:
                flash("Titolo e contenuto sono obbligatori.", "error")
                return redirect(url_for("admin.blog_manager"))

            hero_image_url = (request.form.get("hero_image_url") or "").strip() or None
            post = BlogPost(
                title=title,
                summary=(request.form.get("summary") or "").strip() or None,
                content=content,
                hero_image_url=hero_image_url,
                hero_image=hero_image_url,  # legacy sync for existing data consumers
                meta_title=(request.form.get("meta_title") or "").strip() or None,
                meta_description=(request.form.get("meta_description") or "").strip() or None,
                published=request.form.get("published") == "1",
                published_at=_parse_datetime_local(request.form.get("published_at")),
            )
            if request.form.get("auto_seo") == "1":
                post.apply_seo_boost()
            db.session.add(post)
            db.session.commit()
            flash("Articolo creato con successo.", "success")
            return redirect(url_for("admin.blog_manager"))

        if action == "update":
            post_id = request.form.get("post_id")
            post = BlogPost.query.get(post_id)
            if post is None:
                flash("Articolo non trovato.", "error")
                return redirect(url_for("admin.blog_manager"))

            post.title = (request.form.get("title") or post.title).strip()
            post.summary = (request.form.get("summary") or "").strip() or None
            new_content = request.form.get("content") or post.content
            post.content = strip_literal_breaks(new_content).strip()
            hero_image_url = (request.form.get("hero_image_url") or "").strip() or None
            post.hero_image_url = hero_image_url
            post.hero_image = hero_image_url  # legacy sync for existing data consumers
            post.meta_title = (request.form.get("meta_title") or "").strip() or None
            post.meta_description = (request.form.get("meta_description") or "").strip() or None
            post.published = request.form.get("published") == "1"
            post.published_at = _parse_datetime_local(request.form.get("published_at"))
            if request.form.get("auto_seo") == "1":
                post.apply_seo_boost()
            db.session.commit()
            flash("Articolo aggiornato.", "success")
            return redirect(url_for("admin.blog_manager"))

        if action == "delete":
            post_id = request.form.get("post_id")
            post = BlogPost.query.get(post_id)
            if post is None:
                flash("Articolo non trovato.", "error")
            else:
                db.session.delete(post)
                db.session.commit()
                flash("Articolo eliminato.", "success")
            return redirect(url_for("admin.blog_manager"))

        if action == "optimize":
            post_id = request.form.get("post_id")
            post = BlogPost.query.get(post_id)
            if post is None:
                flash("Articolo non trovato.", "error")
            else:
                post.apply_seo_boost()
                db.session.commit()
                flash("Ottimizzazione SEO completata.", "success")
            return redirect(url_for("admin.blog_manager"))

        flash("Azione non riconosciuta.", "error")
        return redirect(url_for("admin.blog_manager"))

    posts = BlogPost.query.order_by(BlogPost.updated_at.desc()).all()
    return render_template("admin/blog.html", posts=posts)


@bp.route("/media", methods=["GET", "POST"])
@admin_required
def media_library():
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not _is_csrf_valid(csrf_token):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.media_library"))

        max_bytes = int(current_app.config.get("MEDIA_UPLOAD_MAX_BYTES", 8 * 1024 * 1024))
        file_storage = request.files.get("media_file")
        is_valid, error_message, size, _extension = validate_media_file(
            file_storage,
            max_bytes=max_bytes,
        )
        if not is_valid:
            flash(error_message or "File non valido.", "error")
            return redirect(url_for("admin.media_library"))

        configured, config_error = configure_cloudinary()
        if not configured:
            flash(config_error or "Configurazione Cloudinary mancante.", "error")
            return redirect(url_for("admin.media_library"))

        try:
            upload_payload = upload_media_asset(file_storage)
        except Exception as exc:  # pragma: no cover - external service dependency
            current_app.logger.exception("Cloudinary upload failed: %s", exc)
            flash("Errore durante l'upload su Cloudinary. Riprova.", "error")
            return redirect(url_for("admin.media_library"))

        if not upload_payload.get("public_id") or not (
            upload_payload.get("secure_url") or upload_payload.get("url")
        ):
            flash("Risposta Cloudinary incompleta. Riprova.", "error")
            return redirect(url_for("admin.media_library"))

        uploader = current_user if current_user.is_authenticated else None
        uploader_id = uploader.id if uploader else None
        asset = MediaAsset(
            url=upload_payload.get("secure_url") or upload_payload.get("url"),
            public_id=upload_payload.get("public_id"),
            original_filename=upload_payload.get("original_filename") or getattr(file_storage, "filename", None),
            bytes=upload_payload.get("bytes") or size,
            width=upload_payload.get("width"),
            height=upload_payload.get("height"),
            uploaded_by=uploader_id,
        )
        db.session.add(asset)
        db.session.commit()
        flash("Immagine caricata con successo.", "success")
        return redirect(url_for("admin.media_library"))

    assets = MediaAsset.query.order_by(MediaAsset.created_at.desc()).all()
    max_bytes = int(current_app.config.get("MEDIA_UPLOAD_MAX_BYTES", 8 * 1024 * 1024))
    return render_template(
        "admin/media.html",
        assets=assets,
        max_upload_bytes=max_bytes,
    )


@bp.route("/blog/preview/<int:post_id>")
@admin_required
def blog_preview(post_id: int):
    post = BlogPost.query.get_or_404(post_id)
    author_name = getattr(post, "author", None) or getattr(post, "author_name", None)
    post_url = url_for("community.blog_detail", slug=post.slug, _external=True)
    body_html = render_markdown(post.content or "")

    return render_template(
        "blog/detail.html",
        post=post,
        post_url=post_url,
        author_name=author_name,
        related_posts=[],
        previous_post=None,
        next_post=None,
        breadcrumb_schema=None,
        body_html=body_html,
        preview_mode=True,
    )


@bp.route("/forum", methods=["GET", "POST"])
@admin_required
def forum_manager():
    ensure_demo_profiles()
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not _is_csrf_valid(csrf_token):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.forum_manager"))

        action = (request.form.get("action") or "").strip()

        if action == "delete_thread":
            thread_id = request.form.get("thread_id")
            thread = ForumThread.query.get(thread_id)
            if thread is None:
                flash("Discussione non trovata.", "error")
            else:
                archived_thread = {
                    "id": thread.id,
                    "slug": thread.slug,
                    "title": thread.title,
                }
                db.session.delete(thread)
                db.session.commit()
                _log_admin_action(
                    "forum_delete_thread",
                    message=f"Thread '{archived_thread['title']}' eliminato",
                    details=archived_thread,
                )
                flash("Discussione eliminata con successo.", "success")
            return redirect(url_for("admin.forum_manager"))

        if action == "delete_reply":
            reply_id = request.form.get("reply_id")
            reply = ForumReply.query.get(reply_id)
            if reply is None:
                flash("Risposta non trovata.", "error")
            else:
                reply_snapshot = {
                    "id": reply.id,
                    "thread_id": reply.thread_id,
                    "thread_slug": reply.thread.slug if reply.thread else None,
                }
                db.session.delete(reply)
                db.session.commit()
                _log_admin_action(
                    "forum_delete_reply",
                    message=f"Risposta #{reply_snapshot['id']} eliminata",
                    details=reply_snapshot,
                )
                flash("Risposta eliminata.", "success")
            return redirect(url_for("admin.forum_manager"))

        flash("Azione non valida.", "error")
        return redirect(url_for("admin.forum_manager"))

    threads = ForumThread.query.order_by(ForumThread.updated_at.desc()).all()
    replies = (
        ForumReply.query.order_by(ForumReply.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template("admin/forum.html", threads=threads, replies=replies)


@bp.route("/feedback", methods=["GET", "POST"])
@admin_required
def feedback_center():
    ensure_demo_profiles()
    if request.method == "POST":
        csrf_token = request.form.get("csrf_token")
        if not _is_csrf_valid(csrf_token):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.feedback_center"))

        action = request.form.get("action")
        feedback_id = request.form.get("feedback_id")
        feedback = UserFeedback.query.get(feedback_id) if feedback_id else None

        if action == "review" and feedback:
            feedback.mark_reviewed(current_user.email or "admin")
            db.session.commit()
            flash("Feedback contrassegnato come revisionato.", "success")
        elif action == "archive" and feedback:
            feedback.archive(current_user.email or "admin")
            db.session.commit()
            flash("Feedback archiviato.", "success")
        elif action == "delete" and feedback:
            db.session.delete(feedback)
            db.session.commit()
            flash("Feedback eliminato.", "success")
        else:
            flash("Azione non valida o feedback mancante.", "error")

        return redirect(url_for("admin.feedback_center"))

    feedback_list = UserFeedback.query.order_by(UserFeedback.created_at.desc()).all()
    return render_template("admin/feedback.html", feedback_list=feedback_list)


@bp.route("/toggle_premium/<int:user_id>", methods=["POST"])
@admin_required
def toggle_premium(user_id):
    data = request.get_json(silent=True)
    is_json = request.is_json and data is not None
    if not is_json:
        data = {}

    csrf_token = data.get("csrf_token") if is_json else request.form.get("csrf_token")
    if not _is_csrf_valid(csrf_token):
        if is_json:
            return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

        flash("Token CSRF non valido. Riprova.", "error")
        return redirect(url_for("admin.admin_home"))

    user = User.query.get_or_404(user_id)
    currently_premium = user.has_premium_access
    action_label = "upgrade" if not currently_premium else "downgrade"

    try:
        if currently_premium:
            user.premium = False
            user.is_premium = False
            user.premium_lifetime = False
            user.plan_type = "free"
            user.subscription_status = "free"
            user.premium_since = None
            user.threshold = None
        else:
            user.premium = True
            user.is_premium = True
            user.mark_premium_plan()
            user.subscription_status = "active"
            if not user.premium_since:
                user.premium_since = datetime.utcnow()

        db.session.commit()
    except Exception as exc:  # pragma: no cover - database failure safeguard
        db.session.rollback()
        error_message = f"Impossibile aggiornare il piano premium: {exc}"
        _log_admin_action(
            action_label,
            target_user=user,
            status="error",
            message=error_message,
        )
        if is_json:
            return jsonify({"success": False, "message": error_message}), 500

        flash("Si è verificato un errore durante l'aggiornamento del piano.", "error")
        return redirect(url_for("admin.admin_home"))

    new_state = user.has_premium_access
    log_message = f"{user.email} -> {'Premium' if new_state else 'Free'}"
    _log_admin_action(
        action_label,
        target_user=user,
        status="success",
        message=log_message,
        details={"premium": new_state},
    )

    if is_json:
        return jsonify(
            {
                "success": True,
                "premium": new_state,
                "message": f"User {user.email} {'upgraded to' if new_state else 'downgraded from'} Premium",
            }
        )
    else:
        flash(
            f"User {user.email} {'upgraded to' if new_state else 'downgraded from'} Premium",
            "success",
        )
        return redirect(url_for("admin.admin_home"))


@bp.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    data = request.get_json(silent=True)
    is_json = request.is_json and data is not None
    if not is_json:
        data = {}

    csrf_token = data.get("csrf_token") if is_json else request.form.get("csrf_token")
    if not _is_csrf_valid(csrf_token):
        if is_json:
            return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

        flash("Token CSRF non valido. Riprova.", "error")
        return redirect(url_for("admin.admin_home"))

    user = User.query.get_or_404(user_id)

    if user.is_admin:
        _log_admin_action(
            "delete",
            target_user=user,
            status="error",
            message="Tentativo di eliminare un amministratore",
        )
        if request.is_json:
            return jsonify({"success": False, "message": "Cannot delete admin users"})
        else:
            flash("Cannot delete admin users", "error")
            return redirect(url_for("admin.admin_home"))

    target_email = user.email

    try:
        Event.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
    except Exception as exc:  # pragma: no cover - database safeguard
        db.session.rollback()
        error_message = f"Impossibile eliminare l'utente: {exc}"
        _log_admin_action(
            "delete",
            target_user=user,
            status="error",
            message=error_message,
        )
        if request.is_json:
            return jsonify({"success": False, "message": error_message}), 500

        flash("Si è verificato un errore durante l'eliminazione dell'utente.", "error")
        return redirect(url_for("admin.admin_home"))

    _log_admin_action(
        "delete",
        target_email=target_email,
        status="success",
        message=f"Utente {target_email} eliminato",
    )

    if is_json:
        return jsonify(
            {"success": True, "message": f"User {user.email} deleted successfully"}
        )
    else:
        flash(f"User {user.email} deleted successfully", "success")
        return redirect(url_for("admin.admin_home"))


@bp.route("/test-alert", methods=["POST"])
@admin_required
def test_alert():
    """Test alert endpoint - manually trigger Telegram alert checking"""
    data = request.get_json(silent=True) or {}
    if not _is_csrf_valid(data.get("csrf_token")):
        return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

    try:
        telegram_service = TelegramService()
        if not telegram_service.is_configured():
            _log_admin_action(
                "test_alert_all",
                status="error",
                message="Bot Telegram non configurato",
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Bot Telegram non configurato. Imposta il token prima di eseguire il test.",
                    }
                ),
                400,
            )

        telegram_service.check_and_send_alerts()

        normalized_chat_id = func.nullif(
            func.trim(cast(User.chat_id, db.String)),
            "",
        )
        normalized_telegram_chat_id = func.nullif(
            func.trim(cast(User.telegram_chat_id, db.String)),
            "",
        )

        premium_status_filter = or_(
            User.plan_type == "premium",
            User.is_premium.is_(True),
            User.premium.is_(True),
            User.premium_lifetime.is_(True),
            func.lower(func.coalesce(User.subscription_status, "")).in_(
                ["active", "trialing"]
            ),
        )

        chat_filter = or_(
            and_(
                normalized_telegram_chat_id.isnot(None),
                normalized_telegram_chat_id != "0",
            ),
            and_(
                normalized_chat_id.isnot(None),
                normalized_chat_id != "0",
            ),
        )

        premium_users = (
            User.query.filter(
                premium_status_filter,
                chat_filter,
                User.telegram_opt_in.is_(True),
            )
            .order_by(User.id.asc())
            .all()
        )

        recipients_count = len(premium_users)
        sent_count = 0

        test_message = (
            "✅ Alert di test EtnaMonitor\n"
            "Le notifiche Telegram sono attive e il sistema è operativo."
        )

        # In passato l'endpoint di test si limitava ad eseguire check_and_send_alerts
        # senza spedire un messaggio esplicito, quindi il popup segnalava destinatari
        # ma Telegram non riceveva nulla. Inviamo qui un alert reale verso ogni chat
        # idonea così che l'operatore possa verificare la consegna dal pannello admin.
        for user in premium_users:
            chat_id = user.telegram_chat_id or user.chat_id
            if telegram_service.send_message(chat_id, test_message):
                sent_count += 1
                db.session.add(
                    Event(
                        user_id=user.id,
                        event_type="test_alert",
                        message="Alert di test inviato dall'area admin",
                    )
                )

        if sent_count:
            db.session.commit()

        recent_alerts = Event.query.filter_by(event_type="alert").count()

        message_lines = [
            "Controllo completato.",
            f"Utenti Premium con Telegram: {recipients_count}",
            f"Messaggi di test inviati con successo: {sent_count}",
            f"Alert totali nel sistema: {recent_alerts}",
        ]

        _log_admin_action(
            "test_alert_all",
            status="success",
            message=f"Test alert globale - inviati {sent_count}",
            details={
                "recipients": recipients_count,
                "sent": sent_count,
            },
        )

        return jsonify({"success": True, "message": "\n".join(message_lines)})

    except Exception as e:
        _log_admin_action(
            "test_alert_all",
            status="error",
            message=str(e),
        )
        return (
            jsonify(
                {"success": False, "message": f"Errore durante il controllo: {str(e)}"}
            ),
            500,
        )


@bp.route("/users")
@admin_required
def users_list():
    search_query = (request.args.get("q") or "").strip()
    plan_filter = (request.args.get("plan") or "all").lower()
    page = _coerce_positive_int(request.args.get("page"), default=1)
    per_page = _coerce_positive_int(
        request.args.get("per_page"), default=ADMIN_USERS_PER_PAGE
    )
    per_page = min(per_page, 100)

    pagination = _build_users_query(search_query, plan_filter).paginate(
        page=page, per_page=per_page, error_out=False
    )

    payload = {
        "ok": True,
        "items": [_serialize_user_for_admin(user) for user in pagination.items],
        "page": page,
        "pages": pagination.pages,
        "per_page": per_page,
        "total": pagination.total,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
    }

    return jsonify(payload)


@bp.route("/reset_free_trial/<int:user_id>", methods=["POST"])
@admin_required
def reset_free_trial(user_id: int):
    data = request.get_json(silent=True)
    is_json = request.is_json and data is not None
    if not is_json:
        data = {}

    csrf_token = data.get("csrf_token") if is_json else request.form.get("csrf_token")
    if not _is_csrf_valid(csrf_token):
        if is_json:
            return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

        flash("Token CSRF non valido. Riprova.", "error")
        return redirect(url_for("admin.admin_home"))

    user = User.query.get_or_404(user_id)
    try:
        user.free_alert_consumed = 0
        user.free_alert_event_id = None
        user.last_alert_sent_at = None
        db.session.commit()
    except Exception as exc:  # pragma: no cover - database safeguard
        db.session.rollback()
        error_message = f"Impossibile ripristinare la prova gratuita: {exc}"
        _log_admin_action(
            "reset_trial",
            target_user=user,
            status="error",
            message=error_message,
        )
        if is_json:
            return jsonify({"success": False, "message": error_message}), 500

        flash("Ripristino prova non riuscito.", "error")
        return redirect(url_for("admin.admin_home"))

    _log_admin_action(
        "reset_trial",
        target_user=user,
        status="success",
        message=f"Prova gratuita ripristinata per {user.email}",
    )

    if is_json:
        return jsonify(
            {
                "success": True,
                "message": f"Alert di prova ripristinato per {user.email}",
            }
        )

    flash(f"Prova gratuita ripristinata per {user.email}", "success")
    return redirect(url_for("admin.admin_home"))


@bp.route("/users/<int:user_id>/test-alert", methods=["POST"])
@admin_required
def send_test_alert_to_user(user_id: int):
    data = request.get_json(silent=True) or {}
    if not _is_csrf_valid(data.get("csrf_token")):
        return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

    user = User.query.get_or_404(user_id)
    chat_id = user.telegram_chat_id or user.chat_id

    if not chat_id:
        message = "Questo utente non ha collegato un account Telegram."
        _log_admin_action(
            "test_alert",
            target_user=user,
            status="error",
            message=message,
        )
        return jsonify({"success": False, "message": message}), 400

    telegram_service = TelegramService()
    if not telegram_service.is_configured():
        message = "Bot Telegram non configurato."
        _log_admin_action(
            "test_alert",
            target_user=user,
            status="error",
            message=message,
        )
        return jsonify({"success": False, "message": message}), 500

    try:
        sent = telegram_service.send_message(
            chat_id,
            (
                "🔔 Test alert EtnaMonitor\n"
                "Questo messaggio conferma il collegamento Telegram per gli alert."
            ),
        )
    except Exception as exc:  # pragma: no cover - external service safeguard
        current_app.logger.exception("Failed to send test alert to user %s", user.email)
        message = f"Errore durante l'invio: {exc}"
        _log_admin_action(
            "test_alert",
            target_user=user,
            status="error",
            message=message,
            details={"chat_id": chat_id},
        )
        return jsonify({"success": False, "message": message}), 500

    if not sent:
        message = "Telegram ha rifiutato il messaggio di test."
        _log_admin_action(
            "test_alert",
            target_user=user,
            status="error",
            message=message,
            details={"chat_id": chat_id},
        )
        return jsonify({"success": False, "message": message}), 500

    success_message = f"Alert di test inviato a {user.email}."
    _log_admin_action(
        "test_alert",
        target_user=user,
        status="success",
        message=success_message,
        details={"chat_id": chat_id},
    )

    return jsonify({"success": True, "message": success_message})


@bp.route("/donations")
@admin_required
def donations():
    pending_users = (
        User.query.filter(
            User.donation_tx.isnot(None),
            User.donation_tx != "",
            User.is_premium.is_(False),
            User.premium.is_(False),
        )
        .order_by(User.created_at.desc())
        .all()
    )
    return render_template("admin/donations.html", users=pending_users)


@bp.route("/premium-requests")
@admin_required
def premium_requests():
    status_filter = (request.args.get("status") or "pending").strip().lower()
    email_filter = (request.args.get("email") or "").strip().lower()
    today = datetime.utcnow().date()
    start_date = _parse_date_param(request.args.get("start_date"), today - timedelta(days=30))
    end_date = _parse_date_param(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = end_date

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    query = PremiumRequest.query
    if status_filter and status_filter != "all":
        query = query.filter(PremiumRequest.status == status_filter)
    if email_filter:
        query = query.filter(PremiumRequest.email.ilike(f"%{email_filter}%"))
    query = query.filter(PremiumRequest.created_at >= start_dt, PremiumRequest.created_at <= end_dt)

    requests = query.order_by(PremiumRequest.created_at.desc()).all()
    return render_template(
        "admin/premium_requests.html",
        requests=requests,
        status_filter=status_filter,
        email_filter=email_filter,
        start_date=start_date,
        end_date=end_date,
    )


@bp.route("/premium-requests/<int:request_id>/approve", methods=["POST"])
@admin_required
def approve_premium_request(request_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.premium_requests"))

    premium_request = PremiumRequest.query.get_or_404(request_id)
    if premium_request.status != "pending":
        flash("Richiesta già gestita.", "warning")
        return redirect(url_for("admin.premium_requests"))

    admin_notes = (request.form.get("notes_admin") or "").strip() or None
    admin_user = get_current_user()

    user = premium_request.user
    if user is None:
        user = User.query.filter_by(email=premium_request.email).first()

    if user is None:
        error_message = f"Nessun utente trovato per {premium_request.email}"
        premium_request.mark_reviewed(
            "rejected", admin_user.id if admin_user else None, admin_notes or error_message
        )
        db.session.add(
            EventLog(
                user_id=None,
                event_type="premium_request.approval_failed",
                event_data=json.dumps(
                    {"request_id": premium_request.id, "email": premium_request.email}
                ),
            )
        )
        db.session.commit()
        _log_admin_action(
            "premium_request_approve",
            target_email=premium_request.email,
            status="error",
            message=error_message,
            details={"request_id": premium_request.id},
        )
        flash(error_message, "error")
        return redirect(url_for("admin.premium_requests"))

    user.activate_premium_lifetime()
    if premium_request.paypal_tx_id:
        user.donation_tx = premium_request.paypal_tx_id

    premium_request.user_id = user.id
    premium_request.mark_reviewed(
        "approved", admin_user.id if admin_user else None, admin_notes
    )

    db.session.add(
        EventLog(
            user_id=user.id,
            event_type="premium_request.approved",
            event_data=json.dumps(
                {
                    "request_id": premium_request.id,
                    "email": premium_request.email,
                    "admin_id": admin_user.id if admin_user else None,
                }
            ),
        )
    )
    db.session.commit()

    _log_admin_action(
        "premium_request_approve",
        target_user=user,
        status="success",
        message=f"Premium attivato per {premium_request.email}",
        details={"request_id": premium_request.id},
    )
    flash("Premium attivato e richiesta approvata.", "success")
    return redirect(url_for("admin.premium_requests"))


@bp.route("/premium-requests/<int:request_id>/reject", methods=["POST"])
@admin_required
def reject_premium_request(request_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.premium_requests"))

    premium_request = PremiumRequest.query.get_or_404(request_id)
    if premium_request.status != "pending":
        flash("Richiesta già gestita.", "warning")
        return redirect(url_for("admin.premium_requests"))

    admin_notes = (request.form.get("notes_admin") or "").strip() or None
    admin_user = get_current_user()
    premium_request.mark_reviewed(
        "rejected", admin_user.id if admin_user else None, admin_notes
    )

    db.session.add(
        EventLog(
            user_id=premium_request.user_id,
            event_type="premium_request.rejected",
            event_data=json.dumps(
                {
                    "request_id": premium_request.id,
                    "email": premium_request.email,
                    "admin_id": admin_user.id if admin_user else None,
                }
            ),
        )
    )
    db.session.commit()

    _log_admin_action(
        "premium_request_reject",
        target_email=premium_request.email,
        status="success",
        message="Richiesta premium rifiutata",
        details={"request_id": premium_request.id},
    )
    flash("Richiesta rifiutata.", "info")
    return redirect(url_for("admin.premium_requests"))


@bp.route("/partners", methods=["GET"])
@admin_required
def partners_dashboard():
    search_query = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    category_filter = (request.args.get("category") or "").strip()
    order_by = (request.args.get("order") or "created_desc").strip()

    try:
        ensure_partner_slug_column()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.slug column", exc_info=exc
        )

    try:
        ensure_partner_subscriptions_table()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partner_subscriptions table", exc_info=exc
        )

    try:
        ensure_partner_category_fk()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.category_id column", exc_info=exc
        )

    try:
        ensure_partner_extra_data_column()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.extra_data column", exc_info=exc
        )

    try:
        categories = (
            PartnerCategory.query.order_by(PartnerCategory.sort_order, PartnerCategory.name).all()
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        if missing_table_error(exc, "partner_categories"):
            current_app.logger.warning(
                "Partner categories table missing. Bootstrapping defaults for admin dashboard."
            )
            categories = ensure_partner_categories()
        else:  # pragma: no cover - unexpected failure propagated for visibility
            current_app.logger.exception("Unable to load partner categories", exc_info=exc)
            raise

    try:
        partners_query = Partner.query.options(
            joinedload(Partner.category),
            joinedload(Partner.subscriptions),
        )

        if search_query:
            like_value = f"%{search_query.lower()}%"
            partners_query = partners_query.filter(
                or_(
                    func.lower(Partner.name).like(like_value),
                    func.lower(Partner.email).like(like_value),
                    func.lower(Partner.website_url).like(like_value),
                )
            )

        if status_filter:
            if status_filter == "active":
                partners_query = partners_query.filter(Partner.status == "approved")
            elif status_filter in PARTNER_STATUSES:
                partners_query = partners_query.filter(Partner.status == status_filter)

        if category_filter:
            try:
                category_id = int(category_filter)
            except ValueError:
                category_id = None
            if category_id:
                partners_query = partners_query.filter(Partner.category_id == category_id)

        if order_by == "name_asc":
            partners_query = partners_query.order_by(func.lower(Partner.name).asc())
        elif order_by == "name_desc":
            partners_query = partners_query.order_by(func.lower(Partner.name).desc())
        elif order_by == "updated_desc":
            partners_query = partners_query.order_by(Partner.updated_at.desc())
        elif order_by == "created_asc":
            partners_query = partners_query.order_by(Partner.created_at.asc())
        elif order_by == "category":
            partners_query = partners_query.join(Partner.category).order_by(
                PartnerCategory.name.asc(),
                Partner.name.asc(),
            )
        elif order_by == "status":
            partners_query = partners_query.order_by(Partner.status.asc(), Partner.name.asc())
        else:
            partners_query = partners_query.order_by(Partner.created_at.desc())

        partners = partners_query.all()
    except SQLAlchemyError as exc:
        db.session.rollback()
        if missing_column_error(exc, "partners", "extra_data"):
            current_app.logger.warning(
                "partners.extra_data column missing. Attempting automatic migration."
            )
            ensure_partner_extra_data_column()
            partners = Partner.query.options(
                joinedload(Partner.category),
                joinedload(Partner.subscriptions),
            ).order_by(Partner.created_at.desc()).all()
        elif missing_table_error(exc, "partner_subscriptions"):
            current_app.logger.warning(
                "Partner subscriptions table unavailable. Showing partner list without subscriptions."
            )
            partners = Partner.query.options(joinedload(Partner.category)).order_by(
                Partner.created_at.desc()
            ).all()
        else:  # pragma: no cover
            current_app.logger.exception("Unable to load partners", exc_info=exc)
            partners = []

    usage = {category.id: slots_usage(category) for category in categories}
    category_fields = serialize_category_fields(categories)

    return render_template(
        "admin/partners_directory.html",
        categories=categories,
        partners=partners,
        usage=usage,
        category_fields=category_fields,
        filters={
            "q": search_query,
            "status": status_filter,
            "category": category_filter,
            "order": order_by,
        },
        payment_methods=current_app.config.get("PARTNER_PAYMENT_METHODS", ("paypal_manual", "cash")),
        current_year=datetime.utcnow().year,
        max_upload_bytes=int(
            current_app.config.get("MEDIA_UPLOAD_MAX_BYTES", 8 * 1024 * 1024)
        ),
    )


@bp.route("/partners/categories/<int:category_id>/slots", methods=["POST"])
@admin_required
def partners_update_slots(category_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    category = PartnerCategory.query.get_or_404(category_id)

    try:
        max_slots = int(request.form.get("max_slots", "").strip())
    except (TypeError, ValueError):
        flash("Numero di slot non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    if max_slots <= 0:
        flash("Il numero di slot deve essere positivo.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    used, _ = slots_usage(category)
    if max_slots < used:
        flash(
            f"La categoria ha già {used} partner attivi. Imposta almeno {used} slot.",
            "error",
        )
        return redirect(url_for("admin.partners_dashboard"))

    category.max_slots = max_slots
    category.updated_at = datetime.utcnow()
    db.session.commit()

    flash(f"Slot aggiornati per {category.name}.", "success")
    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners", methods=["POST"])
@admin_required
def partners_create():
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    raw_submit_actions = [
        value.strip().lower()
        for value in request.form.getlist("submit_action")
        if value
    ]
    submit_action = raw_submit_actions[-1] if raw_submit_actions else "draft"
    publish_now = submit_action == "publish"

    try:
        ensure_partner_slug_column()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.slug column before create", exc_info=exc
        )

    try:
        ensure_partner_subscriptions_table()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partner_subscriptions table before create", exc_info=exc
        )

    try:
        ensure_partner_category_fk()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.category_id column before create", exc_info=exc
        )

    try:
        ensure_partner_extra_data_column()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
        current_app.logger.exception(
            "Unable to ensure partners.extra_data column before create", exc_info=exc
        )

    name = (request.form.get("name") or "").strip()
    category_id_raw = request.form.get("category_id")
    if not name or not category_id_raw:
        flash("Nome e categoria sono obbligatori.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    try:
        category_id = int(category_id_raw)
    except (TypeError, ValueError):
        flash("Categoria non valida.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    category = PartnerCategory.query.get(category_id)
    if not category:
        flash("Categoria non trovata.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    extra_fields, error = _build_partner_extra_data(
        category=category,
        form_data=request.form,
    )
    if error:
        flash(error, "error")
        return redirect(url_for("admin.partners_dashboard"))

    slug_value = next_partner_slug(name)
    max_bytes = int(current_app.config.get("MEDIA_UPLOAD_MAX_BYTES", 8 * 1024 * 1024))
    logo_path, error = _store_partner_logo(
        request.files.get("logo"),
        slug=slug_value,
        max_bytes=max_bytes,
    )
    if error:
        flash(error, "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner(
        category=category,
        name=name,
        short_desc=(request.form.get("short_desc") or "").strip(),
        long_desc=(request.form.get("long_desc") or "").strip(),
        website_url=(request.form.get("website_url") or "").strip() or None,
        phone=(request.form.get("phone") or "").strip() or None,
        whatsapp=(request.form.get("whatsapp") or "").strip() or None,
        email=(request.form.get("email") or "").strip() or None,
        instagram=(request.form.get("instagram") or "").strip() or None,
        facebook=(request.form.get("facebook") or "").strip() or None,
        tiktok=(request.form.get("tiktok") or "").strip() or None,
        address=(request.form.get("address") or "").strip() or None,
        city=(request.form.get("city") or "").strip() or None,
        featured=bool(request.form.get("featured")),
        status="approved" if publish_now else "draft",
        extra_data=extra_fields,
        logo_path=logo_path,
    )
    partner.slug = slug_value
    if publish_now:
        partner.approved_at = datetime.utcnow()

    db.session.add(partner)
    db.session.commit()
    if publish_now:
        flash("Partner pubblicato con successo.", "success")
    else:
        flash("Partner creato in bozza.", "success")
    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners/<int:partner_id>/edit", methods=["GET", "POST"])
@admin_required
def partners_edit(partner_id: int):
    partner = Partner.query.options(
        joinedload(Partner.category),
        joinedload(Partner.subscriptions),
    ).get_or_404(partner_id)

    try:
        categories = (
            PartnerCategory.query.order_by(PartnerCategory.sort_order, PartnerCategory.name).all()
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        if missing_table_error(exc, "partner_categories"):
            current_app.logger.warning(
                "Partner categories table missing. Bootstrapping defaults for admin editor."
            )
            categories = ensure_partner_categories()
        else:  # pragma: no cover
            current_app.logger.exception("Unable to load partner categories", exc_info=exc)
            raise

    category_fields = serialize_category_fields(categories)
    max_bytes = int(current_app.config.get("MEDIA_UPLOAD_MAX_BYTES", 8 * 1024 * 1024))

    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Token CSRF non valido.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        name = (request.form.get("name") or "").strip()
        category_id_raw = request.form.get("category_id")
        if not name or not category_id_raw:
            flash("Nome e categoria sono obbligatori.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        try:
            category_id = int(category_id_raw)
        except (TypeError, ValueError):
            flash("Categoria non valida.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        category = PartnerCategory.query.get(category_id)
        if not category:
            flash("Categoria non trovata.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        extra_fields, error = _build_partner_extra_data(
            category=category,
            form_data=request.form,
        )
        if error:
            flash(error, "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        status = (request.form.get("status") or partner.status).strip()
        if status not in PARTNER_STATUSES:
            flash("Stato non valido.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        was_approved = partner.status == "approved"
        previous_category_id = partner.category_id

        partner.name = name
        partner.category = category
        partner.short_desc = (request.form.get("short_desc") or "").strip()
        partner.long_desc = (request.form.get("long_desc") or "").strip()
        partner.website_url = (request.form.get("website_url") or "").strip() or None
        partner.phone = (request.form.get("phone") or "").strip() or None
        partner.whatsapp = (request.form.get("whatsapp") or "").strip() or None
        partner.email = (request.form.get("email") or "").strip() or None
        partner.instagram = (request.form.get("instagram") or "").strip() or None
        partner.facebook = (request.form.get("facebook") or "").strip() or None
        partner.tiktok = (request.form.get("tiktok") or "").strip() or None
        partner.address = (request.form.get("address") or "").strip() or None
        partner.city = (request.form.get("city") or "").strip() or None
        partner.featured = bool(request.form.get("featured"))
        try:
            partner.sort_order = int(request.form.get("sort_order") or 0)
        except ValueError:
            flash("Ordine non valido.", "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))
        partner.extra_data = extra_fields

        if status == "approved" and (not was_approved or previous_category_id != category.id):
            if not can_approve_partner(partner):
                flash("Categoria completa. Impossibile approvare.", "error")
                return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        if status == "approved" and not was_approved:
            partner.mark_approved()
        elif status != "approved":
            partner.status = status
            partner.approved_at = None

        logo_path, logo_error = _store_partner_logo(
            request.files.get("logo"),
            slug=partner.slug,
            max_bytes=max_bytes,
        )
        if logo_error:
            flash(logo_error, "error")
            return redirect(url_for("admin.partners_edit", partner_id=partner.id))

        remove_logo = request.form.get("remove_logo") == "1"
        if logo_path:
            previous_logo = partner.logo_path
            partner.logo_path = logo_path
            if previous_logo and previous_logo != logo_path:
                _delete_partner_logo_path(previous_logo)
        elif remove_logo:
            previous_logo = partner.logo_path
            partner.logo_path = None
            _delete_partner_logo_path(previous_logo)

        db.session.commit()
        flash(f"Partner {partner.name} aggiornato.", "success")
        return redirect(url_for("admin.partners_edit", partner_id=partner.id))

    return render_template(
        "admin/partner_edit.html",
        partner=partner,
        categories=categories,
        category_fields=category_fields,
        logo_url=build_partner_media_url(partner.logo_path),
        max_upload_bytes=max_bytes,
    )


def _delete_partner_logo_path(logo_path: str | None) -> None:
    if not logo_path:
        return

    static_folder = Path(current_app.static_folder or "static")
    resolved_path = static_folder / logo_path

    try:
        if resolved_path.exists() and resolved_path.is_file():
            resolved_path.unlink()
    except OSError as exc:  # pragma: no cover - filesystem failures are non-fatal
        current_app.logger.warning(
            "Unable to remove logo %s for partner %s: %s",
            logo_path,
            "n/a",
            exc,
        )


def _delete_partner_logo(partner: Partner) -> None:
    _delete_partner_logo_path(partner.logo_path)


def _build_partner_extra_data(
    *,
    category: PartnerCategory,
    form_data: dict,
) -> tuple[dict[str, object], str | None]:
    extra_fields: dict[str, object] = {}
    definitions = CATEGORY_FORM_FIELDS.get(category.slug, [])
    for field in definitions:
        field_name = field["name"]
        raw_value = (form_data.get(field_name) or "").strip()
        if not raw_value:
            if field.get("required"):
                return {}, f"{field['label']} è obbligatorio."
            continue

        field_type = field.get("type", "text")
        if field_type == "number":
            try:
                value = int(raw_value)
            except ValueError:
                return {}, f"{field['label']} deve essere un numero valido."
            min_value = field.get("min")
            if isinstance(min_value, int) and value < min_value:
                return {}, f"{field['label']} deve essere maggiore o uguale a {min_value}."
            extra_fields[field_name] = value
        else:
            extra_fields[field_name] = raw_value
    return extra_fields, None


@bp.route("/partners/<int:partner_id>/status", methods=["POST"])
@admin_required
def partners_update_status(partner_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner.query.options(joinedload(Partner.category), joinedload(Partner.subscriptions)).get_or_404(partner_id)
    action = request.form.get("action")

    if action == "approve":
        if not can_approve_partner(partner):
            flash("Categoria completa. Impossibile approvare.", "error")
            return redirect(url_for("admin.partners_dashboard"))
        partner.mark_approved()
        db.session.commit()
        flash(f"Partner {partner.name} approvato.", "success")
    elif action == "reject":
        partner.status = "rejected"
        db.session.commit()
        flash(f"Partner {partner.name} rifiutato.", "info")
    elif action == "disable":
        partner.status = "disabled"
        db.session.commit()
        flash(f"Partner {partner.name} disabilitato.", "info")
    elif action == "expire":
        partner.mark_expired()
        db.session.commit()
        flash(f"Partner {partner.name} segnato come scaduto.", "warning")
    else:
        flash("Azione non riconosciuta.", "error")

    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners/<int:partner_id>/toggle", methods=["POST"])
@admin_required
def partners_toggle_active(partner_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner.query.options(
        joinedload(Partner.category),
        joinedload(Partner.subscriptions),
    ).get_or_404(partner_id)

    if partner.status == "disabled":
        if not can_approve_partner(partner):
            flash("Categoria completa. Impossibile riattivare.", "error")
            return redirect(url_for("admin.partners_dashboard"))
        partner.mark_approved()
        db.session.commit()
        flash(f"Partner {partner.name} riattivato.", "success")
    else:
        partner.status = "disabled"
        db.session.commit()
        flash(f"Partner {partner.name} disabilitato.", "info")

    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners/<int:partner_id>/delete", methods=["POST"])
@admin_required
def partners_delete(partner_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner.query.options(joinedload(Partner.category)).get_or_404(partner_id)

    _delete_partner_logo(partner)
    db.session.delete(partner)
    db.session.commit()

    flash(f"Partner {partner.name} eliminato.", "success")
    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners/<int:partner_id>/subscription", methods=["POST"])
@admin_required
def partners_create_subscription(partner_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner.query.options(joinedload(Partner.category), joinedload(Partner.subscriptions)).get_or_404(partner_id)
    if not can_approve_partner(partner):
        flash("Categoria completa. Impossibile creare sottoscrizione.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    try:
        year = int(request.form.get("year") or datetime.utcnow().year)
    except ValueError:
        flash("Anno non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    price_raw = request.form.get("price_eur") or "0"
    try:
        price_value = Decimal(price_raw)
    except Exception:
        flash("Prezzo non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    payment_method = request.form.get("payment_method") or "paypal_manual"
    if payment_method not in current_app.config.get("PARTNER_PAYMENT_METHODS", ("paypal_manual", "cash")):
        flash("Metodo di pagamento non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    payment_ref = (request.form.get("payment_ref") or "").strip() or None
    paid_at = datetime.utcnow()

    subscription = create_subscription(
        partner,
        year=year,
        price_eur=price_value,
        payment_method=payment_method,
        payment_ref=payment_ref,
        paid_at=paid_at,
    )

    partner.mark_approved()
    db.session.commit()

    pdf_path = generate_invoice_pdf(subscription)

    flash(
        f"Sottoscrizione registrata e partner approvato. Fattura: {pdf_path.name}",
        "success",
    )

    admin_email = current_app.config.get("ADMIN_EMAIL")
    recipients = [partner.email] if partner.email else []
    if recipients or admin_email:
        send_email(
            subject=f"Conferma attivazione partner {partner.name}",
            recipients=recipients or [admin_email],
            bcc=[admin_email] if admin_email and recipients else None,
            body=render_template(
                "email/partners/subscription_confirmation.txt",
                partner=partner,
                subscription=subscription,
            ),
            attachments=[(pdf_path.name, pdf_path.read_bytes(), "application/pdf")],
        )

    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/subscriptions/<int:subscription_id>/expire", methods=["POST"])
@admin_required
def subscriptions_expire(subscription_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    subscription = PartnerSubscription.query.options(joinedload(PartnerSubscription.partner)).get_or_404(subscription_id)
    subscription.mark_expired()
    subscription.partner.mark_expired()
    db.session.commit()
    flash("Sottoscrizione segnata come scaduta.", "warning")
    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/activate_premium/<int:user_id>", methods=["POST"])
@admin_required
def activate_premium(user_id: int):
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(url_for("admin.donations"))

    user = User.query.get_or_404(user_id)
    user.activate_premium_lifetime()
    db.session.commit()

    flash("Attivato premium lifetime.", "success")
    return redirect(url_for("admin.donations"))


@bp.route("/sponsor-analytics")
@admin_required
def sponsor_analytics():
    if (
        SponsorBanner is None
        or SponsorBannerImpression is None
        or SponsorBannerClick is None
    ):
        flash("Funzionalità sponsor non disponibile.", "error")
        return redirect(url_for("admin.admin_home"))

    today = datetime.utcnow().date()
    end_date = _parse_date_param(request.args.get("end_date"), today)
    start_default = end_date - timedelta(days=30)
    start_date = _parse_date_param(request.args.get("start_date"), start_default)
    if start_date > end_date:
        start_date = end_date

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    banner_raw = request.args.get("banner")
    selected_banner_id = None
    if banner_raw:
        try:
            selected_banner_id = int(banner_raw)
        except ValueError:
            selected_banner_id = None

    page_filter = (request.args.get("page") or "").strip()

    total_impressions = (
        _apply_tracking_filters(
            SponsorBannerImpression.query,
            SponsorBannerImpression,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .with_entities(func.count(SponsorBannerImpression.id))
        .scalar()
        or 0
    )

    total_clicks = (
        _apply_tracking_filters(
            SponsorBannerClick.query,
            SponsorBannerClick,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .with_entities(func.count(SponsorBannerClick.id))
        .scalar()
        or 0
    )

    impressions_daily_rows = (
        _apply_tracking_filters(
            db.session.query(
                func.date(SponsorBannerImpression.ts).label("day"),
                func.count(SponsorBannerImpression.id).label("count"),
            ).select_from(SponsorBannerImpression),
            SponsorBannerImpression,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by("day")
        .order_by("day")
        .all()
    )

    clicks_daily_rows = (
        _apply_tracking_filters(
            db.session.query(
                func.date(SponsorBannerClick.ts).label("day"),
                func.count(SponsorBannerClick.id).label("count"),
            ).select_from(SponsorBannerClick),
            SponsorBannerClick,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by("day")
        .order_by("day")
        .all()
    )

    daily_map = {}
    for row in impressions_daily_rows:
        day = _normalize_day(row.day)
        if day:
            daily_map[day] = {"impressions": int(row.count or 0), "clicks": 0}

    for row in clicks_daily_rows:
        day = _normalize_day(row.day)
        if day:
            stats = daily_map.setdefault(day, {"impressions": 0, "clicks": 0})
            stats["clicks"] = int(row.count or 0)

    chart_labels = []
    chart_impressions = []
    chart_clicks = []
    cursor = start_date
    while cursor <= end_date:
        stats = daily_map.get(cursor, {"impressions": 0, "clicks": 0})
        chart_labels.append(cursor.isoformat())
        chart_impressions.append(stats["impressions"])
        chart_clicks.append(stats["clicks"])
        cursor += timedelta(days=1)

    impressions_by_page_rows = (
        _apply_tracking_filters(
            db.session.query(
                SponsorBannerImpression.page.label("page"),
                func.count(SponsorBannerImpression.id).label("impressions"),
            ).select_from(SponsorBannerImpression),
            SponsorBannerImpression,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by(SponsorBannerImpression.page)
        .all()
    )

    clicks_by_page_rows = (
        _apply_tracking_filters(
            db.session.query(
                SponsorBannerClick.page.label("page"),
                func.count(SponsorBannerClick.id).label("clicks"),
            ).select_from(SponsorBannerClick),
            SponsorBannerClick,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by(SponsorBannerClick.page)
        .all()
    )

    page_stats_map = {}
    for row in impressions_by_page_rows:
        key = row.page or "Non specificata"
        page_stats_map[key] = {
            "page": key,
            "impressions": int(row.impressions or 0),
            "clicks": 0,
        }

    for row in clicks_by_page_rows:
        key = row.page or "Non specificata"
        stats = page_stats_map.setdefault(
            key,
            {"page": key, "impressions": 0, "clicks": 0},
        )
        stats["clicks"] = int(row.clicks or 0)

    for stats in page_stats_map.values():
        stats["ctr"] = (
            (stats["clicks"] / stats["impressions"] * 100)
            if stats["impressions"]
            else 0
        )

    page_stats = sorted(
        page_stats_map.values(), key=lambda item: item["impressions"], reverse=True
    )

    banner_impressions_rows = (
        _apply_tracking_filters(
            db.session.query(
                SponsorBanner.id.label("banner_id"),
                SponsorBanner.title.label("title"),
                func.count(SponsorBannerImpression.id).label("impressions"),
            )
            .select_from(SponsorBannerImpression)
            .join(SponsorBanner, SponsorBanner.id == SponsorBannerImpression.banner_id),
            SponsorBannerImpression,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by(SponsorBanner.id, SponsorBanner.title)
        .all()
    )

    banner_clicks_rows = (
        _apply_tracking_filters(
            db.session.query(
                SponsorBanner.id.label("banner_id"),
                SponsorBanner.title.label("title"),
                func.count(SponsorBannerClick.id).label("clicks"),
            )
            .select_from(SponsorBannerClick)
            .join(SponsorBanner, SponsorBanner.id == SponsorBannerClick.banner_id),
            SponsorBannerClick,
            start_dt,
            end_dt,
            selected_banner_id,
            page_filter,
        )
        .group_by(SponsorBanner.id, SponsorBanner.title)
        .all()
    )

    banner_stats_map = {}
    for row in banner_impressions_rows:
        key = row.banner_id
        banner_stats_map[key] = {
            "banner_id": key,
            "title": row.title or f"Banner #{key}",
            "impressions": int(row.impressions or 0),
            "clicks": 0,
        }

    for row in banner_clicks_rows:
        key = row.banner_id
        stats = banner_stats_map.setdefault(
            key,
            {
                "banner_id": key,
                "title": row.title or f"Banner #{key}",
                "impressions": 0,
                "clicks": 0,
            },
        )
        stats["title"] = row.title or stats["title"]
        stats["clicks"] = int(row.clicks or 0)

    for stats in banner_stats_map.values():
        stats["ctr"] = (
            (stats["clicks"] / stats["impressions"] * 100)
            if stats["impressions"]
            else 0
        )

    banner_stats = sorted(
        banner_stats_map.values(), key=lambda item: item["impressions"], reverse=True
    )

    daily_rows = []
    for label, impressions, clicks in zip(
        chart_labels, chart_impressions, chart_clicks
    ):
        ctr_value = (clicks / impressions * 100) if impressions else 0
        daily_rows.append(
            {
                "date": label,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr_value,
            }
        )

    summary = {
        "impressions": total_impressions,
        "clicks": total_clicks,
        "ctr": (total_clicks / total_impressions * 100) if total_impressions else 0,
    }

    if request.args.get("export") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["data", "impression", "click", "ctr_%"])
        for row in daily_rows:
            writer.writerow(
                [row["date"], row["impressions"], row["clicks"], f"{row['ctr']:.2f}"]
            )

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv"
        response.headers["Content-Disposition"] = (
            f"attachment; filename=sponsor-analytics-{start_date.isoformat()}-{end_date.isoformat()}.csv"
        )
        return response

    banners = SponsorBanner.query.order_by(SponsorBanner.title.asc()).all()
    selected_banner = None
    if selected_banner_id:
        selected_banner = next((b for b in banners if b.id == selected_banner_id), None)

    return render_template(
        "admin/sponsor_analytics.html",
        banners=banners,
        selected_banner=selected_banner,
        filters={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "banner_id": selected_banner_id,
            "page": page_filter,
        },
        summary=summary,
        chart_data={
            "labels": chart_labels,
            "impressions": chart_impressions,
            "clicks": chart_clicks,
        },
        daily_rows=daily_rows,
        page_stats=page_stats,
        banner_stats=banner_stats,
        page_title="Sponsor Analytics – Admin EtnaMonitor",
    )


@bp.route("/banners", methods=["GET"])
@admin_required
def banner_list():
    if SponsorBanner is None:
        flash("Gestione sponsor non disponibile.", "error")
        return redirect(url_for("admin.admin_home"))

    banners = SponsorBanner.query.order_by(SponsorBanner.created_at.desc()).all()
    return render_template("admin/banners.html", banners=banners)


@bp.route("/banners", methods=["POST"])
@admin_required
def banner_create():
    if SponsorBanner is None:
        flash("Gestione sponsor non disponibile.", "error")
        return redirect(url_for("admin.banner_list"))

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(url_for("admin.banner_list"))

    title = (request.form.get("title") or "").strip()
    image_url = (request.form.get("image_url") or "").strip()
    target_url = (request.form.get("target_url") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    active = bool(request.form.get("active"))

    if not title or not image_url or not target_url:
        flash("Compila titolo, immagine e link destinazione.", "error")
        return redirect(url_for("admin.banner_list"))

    banner = SponsorBanner(
        title=title,
        image_url=image_url,
        target_url=target_url,
        description=description,
        active=active,
    )
    db.session.add(banner)
    db.session.commit()

    flash("Banner creato con successo.", "success")
    return redirect(url_for("admin.banner_list"))


@bp.route("/banners/<int:banner_id>/toggle", methods=["POST"])
@admin_required
def banner_toggle(banner_id: int):
    if SponsorBanner is None:
        flash("Gestione sponsor non disponibile.", "error")
        return redirect(url_for("admin.banner_list"))

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(url_for("admin.banner_list"))

    banner = SponsorBanner.query.get_or_404(banner_id)
    banner.active = not banner.active
    db.session.commit()

    flash("Stato banner aggiornato.", "success")
    return redirect(url_for("admin.banner_list"))


@bp.route("/banners/<int:banner_id>/delete", methods=["POST"])
@admin_required
def banner_delete(banner_id: int):
    if SponsorBanner is None:
        flash("Gestione sponsor non disponibile.", "error")
        return redirect(url_for("admin.banner_list"))

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(url_for("admin.banner_list"))

    banner = SponsorBanner.query.get_or_404(banner_id)
    db.session.delete(banner)
    db.session.commit()

    flash("Banner eliminato.", "success")
    return redirect(url_for("admin.banner_list"))


@bp.route("/banners/<int:banner_id>/update", methods=["POST"])
@admin_required
def banner_update(banner_id: int):
    if SponsorBanner is None:
        flash("Gestione sponsor non disponibile.", "error")
        return redirect(url_for("admin.banner_list"))

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(url_for("admin.banner_list"))

    banner = SponsorBanner.query.get_or_404(banner_id)

    title = (request.form.get("title") or "").strip()
    image_url = (request.form.get("image_url") or "").strip()
    target_url = (request.form.get("target_url") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    active = bool(request.form.get("active"))

    if not title or not image_url or not target_url:
        flash("Titolo, immagine e link sono obbligatori.", "error")
        return redirect(url_for("admin.banner_list"))

    banner.title = title
    banner.image_url = image_url
    banner.target_url = target_url
    banner.description = description
    banner.active = active
    db.session.commit()

    flash("Banner aggiornato.", "success")
    return redirect(url_for("admin.banner_list"))


@bp.route("/theme_manager")
@admin_required
def theme_manager():
    """Theme manager page for admins to select site templates"""
    from sqlalchemy import func

    current_theme = current_user.theme_preference if current_user else "volcano_tech"

    stats = {
        "total_users": User.query.count(),
        "maintenance_users": User.query.filter_by(
            theme_preference="maintenance"
        ).count(),
        "volcano_users": User.query.filter_by(theme_preference="volcano_tech").count(),
        "apple_users": User.query.filter_by(theme_preference="apple_minimal").count(),
    }

    return render_template(
        "admin/theme_manager.html", current_theme=current_theme, stats=stats
    )


@bp.get("/api/cron-runs")
@admin_required
def get_cron_runs():
    limit = _coerce_int(request.args.get("limit"), default=50, minimum=1, maximum=200)
    offset = _coerce_int(request.args.get("offset"), default=0, minimum=0, maximum=5000)
    ok_filter = _coerce_bool_param(request.args.get("ok"))
    sent_gt = _coerce_int(request.args.get("sent_gt"), default=0, minimum=0, maximum=100000)
    period = (request.args.get("period") or "").strip().lower()

    query = CronRunLog.query
    if ok_filter is not None:
        query = query.filter(CronRunLog.ok.is_(ok_filter))
    if sent_gt:
        query = query.filter(CronRunLog.sent > sent_gt)
    if period in {"24h", "7d"}:
        now = datetime.now(timezone.utc)
        hours = 24 if period == "24h" else 24 * 7
        query = query.filter(CronRunLog.created_at >= now - timedelta(hours=hours))

    total = query.with_entities(func.count(CronRunLog.id)).scalar() or 0
    items = (
        query.order_by(CronRunLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "offset": offset,
        "total": int(total),
        "items": [entry.serialize_summary() for entry in items],
    }

    if (request.args.get("include_metrics") or "").strip() == "1":
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=24)
        last_run = (
            CronRunLog.query.order_by(CronRunLog.created_at.desc()).limit(1).one_or_none()
        )
        total_24h = (
            CronRunLog.query.filter(CronRunLog.created_at >= window_start)
            .with_entities(func.count(CronRunLog.id))
            .scalar()
            or 0
        )
        ok_24h = (
            CronRunLog.query.filter(
                CronRunLog.created_at >= window_start, CronRunLog.ok.is_(True)
            )
            .with_entities(func.count(CronRunLog.id))
            .scalar()
            or 0
        )
        errors_24h = (
            CronRunLog.query.filter(
                CronRunLog.created_at >= window_start, CronRunLog.ok.is_(False)
            )
            .with_entities(func.count(CronRunLog.id))
            .scalar()
            or 0
        )
        sent_24h = (
            CronRunLog.query.filter(CronRunLog.created_at >= window_start)
            .with_entities(func.coalesce(func.sum(CronRunLog.sent), 0))
            .scalar()
            or 0
        )
        ok_rate = (ok_24h / total_24h * 100) if total_24h else None
        payload["metrics"] = {
            "last_run_at": last_run.created_at.isoformat() if last_run else None,
            "last_run_ok": bool(last_run.ok) if last_run else None,
            "ok_rate_24h": round(ok_rate, 1) if ok_rate is not None else None,
            "sent_24h": int(sent_24h),
            "errors_24h": int(errors_24h),
            "total_24h": int(total_24h),
        }

    return jsonify(payload)


@bp.get("/api/cron-runs/<int:run_id>")
@admin_required
def get_cron_run_detail(run_id: int):
    entry = CronRunLog.query.get_or_404(run_id)
    return jsonify({"ok": True, "entry": entry.serialize_detail()})


@bp.route("/set_theme", methods=["POST"])
@admin_required
def set_theme():
    """Set the theme preference for the current admin user"""
    data = request.get_json()
    theme = data.get("theme")

    valid_themes = ["maintenance", "volcano_tech", "apple_minimal"]
    if theme not in valid_themes:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f'Invalid theme. Must be one of: {", ".join(valid_themes)}',
                }
            ),
            400,
        )

    current_user.theme_preference = theme
    db.session.commit()

    return jsonify(
        {"success": True, "message": f"Theme changed to {theme}", "theme": theme}
    )
