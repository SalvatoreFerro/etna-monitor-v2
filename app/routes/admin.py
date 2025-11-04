import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, make_response, current_app
from flask_login import current_user
from sqlalchemy import and_, cast, func, or_

from ..utils.auth import admin_required
from ..models import (
    db,
    BlogPost,
    UserFeedback,
)
from ..models.user import User
from ..models.event import Event
from ..models.partner import Partner
from ..services.gamification_service import ensure_demo_profiles
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
from ..utils.partners import extract_partner_payload
from ..filters import strip_literal_breaks

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


@bp.route("/")
@admin_required
def admin_home():
    ensure_demo_profiles()
    users = User.query.all()
    return render_template("admin.html", users=users)


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

            post = BlogPost(
                title=title,
                summary=(request.form.get("summary") or "").strip() or None,
                content=content,
                hero_image=(request.form.get("hero_image") or "").strip() or None,
                published=request.form.get("published") == "1",
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
            post.hero_image = (request.form.get("hero_image") or "").strip() or None
            post.published = request.form.get("published") == "1"
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

    posts = (
        BlogPost.query.order_by(BlogPost.updated_at.desc()).all()
    )
    return render_template("admin/blog.html", posts=posts)


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

    feedback_list = (
        UserFeedback.query.order_by(UserFeedback.created_at.desc()).all()
    )
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
        return redirect(url_for('admin.admin_home'))

    user = User.query.get_or_404(user_id)
    currently_premium = user.has_premium_access

    if currently_premium:
        user.premium = False
        user.is_premium = False
        user.premium_lifetime = False
        user.plan_type = 'free'
        user.subscription_status = 'free'
        user.premium_since = None
        user.threshold = None
    else:
        user.premium = True
        user.is_premium = True
        user.mark_premium_plan()
        user.subscription_status = 'active'
        if not user.premium_since:
            user.premium_since = datetime.utcnow()

    db.session.commit()

    new_state = user.has_premium_access

    if is_json:
        return jsonify({
            "success": True,
            "premium": new_state,
            "message": f"User {user.email} {'upgraded to' if new_state else 'downgraded from'} Premium"
        })
    else:
        flash(f"User {user.email} {'upgraded to' if new_state else 'downgraded from'} Premium", "success")
        return redirect(url_for('admin.admin_home'))


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
        return redirect(url_for('admin.admin_home'))

    user = User.query.get_or_404(user_id)

    if user.is_admin:
        if request.is_json:
            return jsonify({"success": False, "message": "Cannot delete admin users"})
        else:
            flash("Cannot delete admin users", "error")
            return redirect(url_for('admin.admin_home'))

    Event.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()

    if is_json:
        return jsonify({"success": True, "message": f"User {user.email} deleted successfully"})
    else:
        flash(f"User {user.email} deleted successfully", "success")
        return redirect(url_for('admin.admin_home'))


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
            return (
                jsonify({
                    "success": False,
                    "message": "Bot Telegram non configurato. Imposta il token prima di eseguire il test.",
                }),
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
            User.plan_type == 'premium',
            User.is_premium.is_(True),
            User.premium.is_(True),
            User.premium_lifetime.is_(True),
            func.lower(func.coalesce(User.subscription_status, '')).in_(['active', 'trialing']),
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
                        event_type='test_alert',
                        message="Alert di test inviato dall'area admin",
                    )
                )

        if sent_count:
            db.session.commit()

        recent_alerts = Event.query.filter_by(event_type='alert').count()

        message_lines = [
            "Controllo completato.",
            f"Utenti Premium con Telegram: {recipients_count}",
            f"Messaggi di test inviati con successo: {sent_count}",
            f"Alert totali nel sistema: {recent_alerts}",
        ]

        return jsonify({
            "success": True,
            "message": "\n".join(message_lines)
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Errore durante il controllo: {str(e)}"
        }), 500


@bp.route("/users")
@admin_required
def users_list():
    users = User.query.all()
    return jsonify([
        {
            "id": user.id,
            "email": user.email,
            "premium": user.has_premium_access,
            "is_admin": user.is_admin,
            "plan_type": user.current_plan,
            "chat_id": user.telegram_chat_id or user.chat_id,
            "telegram_opt_in": user.telegram_opt_in,
            "free_alert_consumed": user.free_alert_consumed,
            "threshold": user.threshold,
        } for user in users])


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
        return redirect(url_for('admin.admin_home'))

    user = User.query.get_or_404(user_id)
    user.free_alert_consumed = 0
    user.free_alert_event_id = None
    user.last_alert_sent_at = None
    db.session.commit()

    if is_json:
        return jsonify({
            "success": True,
            "message": f"Alert di prova ripristinato per {user.email}",
        })

    flash(f"Prova gratuita ripristinata per {user.email}", "success")
    return redirect(url_for('admin.admin_home'))


@bp.route("/donations")
@admin_required
def donations():
    pending_users = User.query.filter(
        User.donation_tx.isnot(None),
        User.donation_tx != '',
        User.is_premium.is_(False),
        User.premium.is_(False)
    ).order_by(User.created_at.desc()).all()
    return render_template("admin/donations.html", users=pending_users)


@bp.route("/partners", methods=["GET"])
@admin_required
def partners_dashboard():
    partners = Partner.query.order_by(Partner.created_at.desc()).all()
    category_labels = [
        ("Guide", "Guide"),
        ("Hotel", "Hotel"),
        ("Ristorante", "Ristoranti"),
        ("Tour", "Tour"),
        ("Altro", "Altro"),
    ]
    return render_template(
        "admin/partners.html",
        partners=partners,
        categories=category_labels,
    )


@bp.route("/partners", methods=["POST"])
@admin_required
def partners_create():
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido. Riprova.", "error")
        return redirect(url_for("admin.partners_dashboard"))

    payload, errors = extract_partner_payload(request.form, is_admin=True)

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("admin.partners_dashboard"))

    partner = Partner(**payload)
    db.session.add(partner)

    try:
        db.session.commit()
    except Exception:  # pragma: no cover - defensive
        current_app.logger.exception("Failed to create partner from admin")
        db.session.rollback()
        flash(
            "Errore durante la creazione del partner. Verifica i dati inseriti e riprova.",
            "error",
        )
    else:
        flash(f"Partner '{partner.name}' aggiunto con successo.", "success")

    return redirect(url_for("admin.partners_dashboard"))


@bp.route("/partners/<int:partner_id>/toggle", methods=["POST"])
@admin_required
def partners_toggle(partner_id: int):
    data = request.get_json(silent=True) or {}
    if not validate_csrf_token(data.get("csrf_token")):
        return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

    field = data.get("field")
    if field not in {"visible", "verified"}:
        return jsonify({"success": False, "message": "Campo non gestito."}), 400

    partner = Partner.query.get_or_404(partner_id)
    current_value = bool(getattr(partner, field))
    new_value = data.get("value")
    if new_value is None:
        new_value = not current_value
    else:
        new_value = bool(new_value)

    setattr(partner, field, new_value)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to toggle %s for partner %s", field, partner_id
        )
        return jsonify({"success": False, "message": "Errore durante l'aggiornamento."}), 500

    return jsonify({"success": True, "partner": _serialize_partner(partner)})


@bp.route("/partners/<int:partner_id>", methods=["DELETE"])
@admin_required
def partners_delete(partner_id: int):
    data = request.get_json(silent=True) or {}
    if not validate_csrf_token(data.get("csrf_token")):
        return jsonify({"success": False, "message": "Token CSRF non valido."}), 400

    partner = Partner.query.get_or_404(partner_id)
    db.session.delete(partner)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete partner %s", partner_id)
        return jsonify({"success": False, "message": "Errore durante l'eliminazione."}), 500

    return jsonify({"success": True})


@bp.route("/activate_premium/<int:user_id>", methods=["POST"])
@admin_required
def activate_premium(user_id: int):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido.', 'error')
        return redirect(url_for('admin.donations'))

    user = User.query.get_or_404(user_id)
    user.activate_premium_lifetime()
    db.session.commit()

    flash('Attivato premium lifetime.', 'success')
    return redirect(url_for('admin.donations'))


@bp.route("/sponsor-analytics")
@admin_required
def sponsor_analytics():
    if (
        SponsorBanner is None
        or SponsorBannerImpression is None
        or SponsorBannerClick is None
    ):
        flash('Funzionalità sponsor non disponibile.', 'error')
        return redirect(url_for('admin.admin_home'))

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
        stats["ctr"] = (stats["clicks"] / stats["impressions"] * 100) if stats["impressions"] else 0

    page_stats = sorted(page_stats_map.values(), key=lambda item: item["impressions"], reverse=True)

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
        stats["ctr"] = (stats["clicks"] / stats["impressions"] * 100) if stats["impressions"] else 0

    banner_stats = sorted(banner_stats_map.values(), key=lambda item: item["impressions"], reverse=True)

    daily_rows = []
    for label, impressions, clicks in zip(chart_labels, chart_impressions, chart_clicks):
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
            writer.writerow([row["date"], row["impressions"], row["clicks"], f"{row['ctr']:.2f}"])

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv"
        response.headers[
            "Content-Disposition"
        ] = f"attachment; filename=sponsor-analytics-{start_date.isoformat()}-{end_date.isoformat()}.csv"
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
        flash('Gestione sponsor non disponibile.', 'error')
        return redirect(url_for('admin.admin_home'))

    banners = SponsorBanner.query.order_by(SponsorBanner.created_at.desc()).all()
    return render_template("admin/banners.html", banners=banners)


@bp.route("/banners", methods=["POST"])
@admin_required
def banner_create():
    if SponsorBanner is None:
        flash('Gestione sponsor non disponibile.', 'error')
        return redirect(url_for('admin.banner_list'))

    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido.', 'error')
        return redirect(url_for('admin.banner_list'))

    title = (request.form.get('title') or '').strip()
    image_url = (request.form.get('image_url') or '').strip()
    target_url = (request.form.get('target_url') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    active = bool(request.form.get('active'))

    if not title or not image_url or not target_url:
        flash('Compila titolo, immagine e link destinazione.', 'error')
        return redirect(url_for('admin.banner_list'))

    banner = SponsorBanner(
        title=title,
        image_url=image_url,
        target_url=target_url,
        description=description,
        active=active,
    )
    db.session.add(banner)
    db.session.commit()

    flash('Banner creato con successo.', 'success')
    return redirect(url_for('admin.banner_list'))


@bp.route("/banners/<int:banner_id>/toggle", methods=["POST"])
@admin_required
def banner_toggle(banner_id: int):
    if SponsorBanner is None:
        flash('Gestione sponsor non disponibile.', 'error')
        return redirect(url_for('admin.banner_list'))

    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido.', 'error')
        return redirect(url_for('admin.banner_list'))

    banner = SponsorBanner.query.get_or_404(banner_id)
    banner.active = not banner.active
    db.session.commit()

    flash('Stato banner aggiornato.', 'success')
    return redirect(url_for('admin.banner_list'))


@bp.route("/banners/<int:banner_id>/delete", methods=["POST"])
@admin_required
def banner_delete(banner_id: int):
    if SponsorBanner is None:
        flash('Gestione sponsor non disponibile.', 'error')
        return redirect(url_for('admin.banner_list'))

    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido.', 'error')
        return redirect(url_for('admin.banner_list'))

    banner = SponsorBanner.query.get_or_404(banner_id)
    db.session.delete(banner)
    db.session.commit()

    flash('Banner eliminato.', 'success')
    return redirect(url_for('admin.banner_list'))


@bp.route("/banners/<int:banner_id>/update", methods=["POST"])
@admin_required
def banner_update(banner_id: int):
    if SponsorBanner is None:
        flash('Gestione sponsor non disponibile.', 'error')
        return redirect(url_for('admin.banner_list'))

    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido.', 'error')
        return redirect(url_for('admin.banner_list'))

    banner = SponsorBanner.query.get_or_404(banner_id)

    title = (request.form.get('title') or '').strip()
    image_url = (request.form.get('image_url') or '').strip()
    target_url = (request.form.get('target_url') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    active = bool(request.form.get('active'))

    if not title or not image_url or not target_url:
        flash('Titolo, immagine e link sono obbligatori.', 'error')
        return redirect(url_for('admin.banner_list'))

    banner.title = title
    banner.image_url = image_url
    banner.target_url = target_url
    banner.description = description
    banner.active = active
    db.session.commit()

    flash('Banner aggiornato.', 'success')
    return redirect(url_for('admin.banner_list'))


@bp.route("/theme_manager")
@admin_required
def theme_manager():
    """Theme manager page for admins to select site templates"""
    from sqlalchemy import func
    
    current_theme = current_user.theme_preference if current_user else 'volcano_tech'
    
    stats = {
        'total_users': User.query.count(),
        'maintenance_users': User.query.filter_by(theme_preference='maintenance').count(),
        'volcano_users': User.query.filter_by(theme_preference='volcano_tech').count(),
        'apple_users': User.query.filter_by(theme_preference='apple_minimal').count(),
    }
    
    return render_template('admin/theme_manager.html', current_theme=current_theme, stats=stats)


@bp.route("/set_theme", methods=["POST"])
@admin_required
def set_theme():
    """Set the theme preference for the current admin user"""
    data = request.get_json()
    theme = data.get('theme')
    
    valid_themes = ['maintenance', 'volcano_tech', 'apple_minimal']
    if theme not in valid_themes:
        return jsonify({
            'success': False,
            'message': f'Invalid theme. Must be one of: {", ".join(valid_themes)}'
        }), 400
    
    current_user.theme_preference = theme
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Theme changed to {theme}',
        'theme': theme
    })
