import base64
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dataclasses import asdict
from decimal import Decimal
from math import isfinite
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
from sqlalchemy import and_, cast, func, or_, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..utils.auth import admin_required, get_current_user, is_owner_or_admin
from ..utils.config import get_curva_csv_path, get_curva_csv_status, load_curva_dataframe
from backend.utils.extract_colored import download_png as download_colored_png
from backend.utils.extract_colored import extract_series_from_colored
from ..utils.metrics import get_csv_metrics
from ..utils.ingv_bands import load_cached_thresholds
from ..utils.plotly_helpers import build_tremor_figure
from plotly import offline as plotly_offline
from ..models import (
    db,
    BlogPost,
    MediaAsset,
    UserFeedback,
    AdminActionLog,
    CommunityPost,
    ForumThread,
    ForumReply,
    CronRun,
    UserBadge,
    UserGamificationProfile,
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
from ..services.copernicus import resolve_copernicus_bbox
from ..services.copernicus_preview import (
    extract_copernicus_assets,
    fetch_latest_copernicus_item,
    select_preview_asset,
)
from ..services.copernicus_smart_view import (
    build_copernicus_view_payload,
    load_copernicus_log,
    load_copernicus_status,
)
from ..services.copernicus_swir import refresh_swir_image
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
from ..services.badge_service import recompute_badges_for_user
from ..services.tremor_summary import build_tremor_summary, get_ai_cache_status
from ..services.sentieri_geojson import (
    parse_geojson_text,
    read_geojson_file,
    validate_feature_collection,
)
from ..extensions import cache

bp = Blueprint("admin", __name__)

TEST_COLORED_CACHE_TTL = int(os.getenv("INGV_COLORED_TEST_CACHE_TTL", "300"))


def _require_owner_user() -> bool:
    user = get_current_user()
    owner_email = (os.getenv("OWNER_EMAIL") or "").strip().lower()
    if not owner_email or not user:
        return False
    return (user.email or "").strip().lower() == owner_email


@bp.get("/admin/debug-copernicus-item")
def debug_copernicus_item():
    if not _require_owner_user():
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    bbox = resolve_copernicus_bbox(None)
    item = fetch_latest_copernicus_item(bbox, current_app.logger)
    if not item:
        return jsonify({"ok": False, "error": "Nessun item Copernicus disponibile"}), 404

    assets = extract_copernicus_assets(item)
    selected = select_preview_asset(assets)
    return jsonify(
        {
            "ok": True,
            "bbox": bbox,
            "item": item,
            "assets": [asdict(asset) for asset in assets],
            "selected_asset": asdict(selected) if selected else None,
        }
    )


@bp.get("/admin/test-copernicus-preview")
def test_copernicus_preview():
    if not _require_owner_user():
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    status = load_copernicus_status()
    payload = build_copernicus_view_payload()
    log_text = load_copernicus_log()
    return render_template(
        "admin/copernicus_preview_test.html",
        copernicus_status=status,
        copernicus_payload=payload,
        copernicus_log=log_text,
    )


@bp.get("/admin/debug-static-copernicus")
def debug_static_copernicus():
    if not _require_owner_user():
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    static_path = Path(current_app.static_folder).resolve()
    copernicus_dir = static_path / "copernicus"
    copernicus_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for entry in sorted(copernicus_dir.iterdir()):
        if not entry.is_file():
            continue
        stat = entry.stat()
        files.append(
            {
                "name": entry.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    def _file_meta(path: Path) -> dict:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {
            "exists": True,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    return jsonify(
        {
            "cwd": os.getcwd(),
            "static_path": str(static_path),
            "copernicus_dir": str(copernicus_dir),
            "files": files,
            "s1_latest": _file_meta(copernicus_dir / "s1_latest.png"),
            "s2_latest": _file_meta(copernicus_dir / "s2_latest.png"),
        }
    )


@bp.get("/refresh-observatory")
def refresh_observatory():
    if not _require_owner_user():
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    result = refresh_swir_image(force=True)
    updated_at = (result.updated_at or datetime.now(timezone.utc)).isoformat()
    return jsonify({"ok": result.ok, "updated_at": updated_at})


@bp.get("/debug-observatory")
def debug_observatory():
    if not _require_owner_user():
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    routes_found = []
    for rule in current_app.url_map.iter_rules():
        if "observatory" in rule.rule.lower():
            routes_found.append(
                {
                    "rule": rule.rule,
                    "endpoint": rule.endpoint,
                    "methods": sorted(method for method in rule.methods if method != "HEAD"),
                }
            )

    static_folder = current_app.static_folder
    static_url_path = current_app.static_url_path
    expected_png_path = Path(static_folder) / "copernicus" / "s2_latest.png"
    file_exists = expected_png_path.exists()
    file_size = expected_png_path.stat().st_size if file_exists else None
    file_mtime = (
        datetime.fromtimestamp(expected_png_path.stat().st_mtime, tz=timezone.utc).isoformat()
        if file_exists
        else None
    )

    return jsonify(
        {
            "routes_found": routes_found,
            "static_folder": static_folder,
            "static_url_path": static_url_path,
            "expected_png_path": str(expected_png_path.resolve()),
            "file_exists": file_exists,
            "file_size": file_size,
            "file_mtime": file_mtime,
        }
    )


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
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Rome"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_sources(value: str | None) -> list[str] | None:
    if not value:
        return None
    sources = [line.strip() for line in value.splitlines()]
    sources = [source for source in sources if source]
    return sources or None


def _parse_datetime_param(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_event_meta(event: Event) -> str:
    parts: list[str] = []
    if event.message:
        parts.append(event.message)
    if event.value is not None:
        parts.append(f"value={event.value}")
    if event.threshold is not None:
        parts.append(f"threshold={event.threshold}")
    return " | ".join(parts) if parts else "—"


def _parse_range_window(value: str | None) -> timedelta:
    if not value:
        return timedelta(hours=24)
    normalized = value.strip().lower()
    if normalized.endswith("h"):
        try:
            return timedelta(hours=int(normalized[:-1]))
        except ValueError:
            return timedelta(hours=24)
    if normalized.endswith("d"):
        try:
            return timedelta(days=int(normalized[:-1]))
        except ValueError:
            return timedelta(days=1)
    return timedelta(hours=24)


def _is_owner(user: User | None) -> bool:
    if user is None:
        return False
    owner_email = (os.getenv("OWNER_EMAIL") or "").strip().lower()
    if not owner_email:
        return bool(user.is_admin)
    return (user.email or "").strip().lower() == owner_email


def _encode_image_base64(path: str | Path | None) -> str | None:
    if not path:
        return None
    image_path = Path(path)
    if not image_path.exists():
        return None
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _test_colored_cache_key() -> str:
    user = get_current_user()
    user_id = str(getattr(user, "id", None) or "owner")
    full_path = request.full_path or request.path or "/admin/test-colored"
    full_path = full_path.rstrip("?")
    return f"admin::test-colored::{user_id}::{full_path}"


def _load_latest_colored_debug() -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", data_dir / "debug"))
    colored_dir = Path(os.getenv("INGV_COLORED_DIR", data_dir / "ingv_colored"))
    debug_json_path = debug_dir / "debug.json"
    latest_png = None
    if colored_dir.exists():
        png_candidates = sorted(
            colored_dir.glob("colored_*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if png_candidates:
            latest_png = png_candidates[0]

    return {
        "raw_png": latest_png,
        "overlay": debug_dir / "overlay.png",
        "mask": debug_dir / "mask_polyline.png",
        "mask_raw": debug_dir / "mask_raw.png",
        "mask_ink": debug_dir / "mask_ink.png",
        "mask_pretty": debug_dir / "mask_pretty.png",
        "crop": debug_dir / "crop_plot_area.png",
        "overlay_markers": debug_dir / "overlay_markers.png",
        "debug_json": debug_json_path if debug_json_path.exists() else None,
    }


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
    event_type = (request.args.get("event_type") or "all").lower()
    event_user_id_input = (request.args.get("event_user_id") or "").strip()
    event_user_id = (
        int(event_user_id_input) if event_user_id_input.isdigit() else None
    )

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
            "label": "Monitor sistema",
            "description": "KPI cron, timeline dei run e health checks.",
            "icon": "fa-wave-square",
            "url": url_for("admin.monitor_system"),
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
    event_query = (
        db.session.query(Event, User)
        .join(User, User.id == Event.user_id)
        .order_by(Event.timestamp.desc())
    )
    if event_type in {"login", "alert"}:
        event_query = event_query.filter(Event.event_type == event_type)
    if event_user_id is not None:
        event_query = event_query.filter(Event.user_id == event_user_id)

    maintenance_event_rows = [
        {
            "timestamp": event.timestamp.isoformat() if event.timestamp else "—",
            "user_id": event.user_id,
            "email": user.email,
            "event_type": event.event_type,
            "meta": _format_event_meta(event),
        }
        for event, user in event_query.limit(30).all()
    ]

    badge_total = db.session.query(func.count(UserBadge.id)).scalar() or 0
    top_users = (
        db.session.query(
            User.id,
            User.email,
            func.count(UserBadge.id).label("badge_count"),
            UserGamificationProfile.level,
        )
        .outerjoin(UserBadge, UserBadge.user_id == User.id)
        .outerjoin(UserGamificationProfile, UserGamificationProfile.user_id == User.id)
        .group_by(User.id, User.email, UserGamificationProfile.level)
        .order_by(func.count(UserBadge.id).desc(), User.email.asc())
        .limit(10)
        .all()
    )
    gamification_top_users = [
        {
            "user_id": user_id,
            "email": email,
            "badge_count": int(badge_count or 0),
            "level": int(level or 1),
        }
        for user_id, email, badge_count, level in top_users
    ]
    level_counts_raw = dict(
        db.session.query(
            UserGamificationProfile.level, func.count(UserGamificationProfile.id)
        )
        .group_by(UserGamificationProfile.level)
        .all()
    )
    gamification_level_counts = {
        1: int(level_counts_raw.get(1, 0)),
        2: int(level_counts_raw.get(2, 0)),
        3: int(level_counts_raw.get(3, 0)),
    }

    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    db_type = "unknown"
    if db_uri:
        try:
            db_type = make_url(db_uri).drivername.split("+")[0]
        except Exception:
            db_type = "unknown"

    curva_colored_path = Path(current_app.root_path).parent / "data" / "curva_colored.csv"
    curva_colored_mtime = None
    if curva_colored_path.exists():
        stat = curva_colored_path.stat()
        curva_colored_mtime = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()

    raw_version = (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("APP_VERSION")
        or os.getenv("GIT_COMMIT")
        or "unknown"
    )
    version_label = raw_version[:8] if raw_version != "unknown" else raw_version

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
        maintenance_event_rows=maintenance_event_rows,
        maintenance_event_type=event_type,
        maintenance_event_user_id=event_user_id_input,
        gamification_badge_total=int(badge_total),
        gamification_top_users=gamification_top_users,
        gamification_level_counts=gamification_level_counts,
        maintenance_health={
            "db_type": db_type,
            "curva_colored_mtime": curva_colored_mtime,
            "app_version": version_label,
        },
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
                author_name=(request.form.get("author_name") or "").strip()
                or BlogPost.DEFAULT_AUTHOR_NAME,
                author_slug=BlogPost.build_slug(
                    (request.form.get("author_name") or "").strip()
                    or BlogPost.DEFAULT_AUTHOR_NAME
                ),
                sources=_parse_sources(request.form.get("sources")),
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
            author_name = (request.form.get("author_name") or "").strip() or BlogPost.DEFAULT_AUTHOR_NAME
            post.author_name = author_name
            post.author_slug = BlogPost.build_slug(author_name)
            post.published = request.form.get("published") == "1"
            post.published_at = _parse_datetime_local(request.form.get("published_at"))
            post.sources = _parse_sources(request.form.get("sources"))
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
    author_name = post.author_display_name
    post_url = url_for("community.blog_detail", slug=post.slug, _external=True)
    author_url = url_for("main.author_detail", slug=post.author_display_slug, _external=True)
    body_html = render_markdown(post.content or "")
    published_ts = post.published_at or post.created_at
    updated_ts = post.updated_at or published_ts

    publisher_logo_url = url_for("static", filename="images/logo.svg", _external=True)
    return render_template(
        "blog/detail.html",
        post=post,
        post_url=post_url,
        author_name=author_name,
        author_url=author_url,
        publisher_logo_url=publisher_logo_url,
        published_timestamp_utc=published_ts,
        published_timestamp_local=published_ts,
        published_display=published_ts.strftime("%d %B %Y, %H:%M UTC") if published_ts else "",
        updated_timestamp_utc=updated_ts,
        updated_timestamp_local=updated_ts,
        updated_display=updated_ts.strftime("%d %B %Y, %H:%M UTC") if updated_ts else "",
        show_updated=bool(updated_ts and published_ts and updated_ts != published_ts),
        sources=post.sources or [],
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
                user.premium_since = datetime.now(timezone.utc)

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
    today = datetime.now(timezone.utc).date()
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
        current_year=datetime.now(timezone.utc).year,
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
    category.updated_at = datetime.now(timezone.utc)
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
        partner.approved_at = datetime.now(timezone.utc)

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
        year = int(request.form.get("year") or datetime.now(timezone.utc).year)
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
    paid_at = datetime.now(timezone.utc)

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

    today = datetime.now(timezone.utc).date()
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


@bp.route("/sentieri", methods=["GET", "POST"])
@admin_required
def admin_sentieri():
    """Admin console for trails/POI GeoJSON management (founder-only)."""
    data_dir = Path(current_app.root_path) / "static" / "data"
    trails_path = data_dir / "trails.geojson"
    pois_path = data_dir / "pois.geojson"

    trails_text = ""
    pois_text = ""
    report = None

    if request.method == "POST":
        if not _is_csrf_valid(request.form.get("csrf_token")):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("admin.admin_sentieri"))

        action = (request.form.get("action") or "").strip().lower()
        trails_text = request.form.get("trails_geojson", "")
        pois_text = request.form.get("pois_geojson", "")

        if action == "restore":
            trails_text, trails_data, trails_error = read_geojson_file(trails_path)
            pois_text, pois_data, pois_error = read_geojson_file(pois_path)
            report = {
                "ok": not (trails_error or pois_error),
                "trails_count": len(trails_data.get("features", [])) if trails_data else 0,
                "pois_count": len(pois_data.get("features", [])) if pois_data else 0,
                "errors": [
                    error
                    for error in [trails_error, pois_error]
                    if error
                ],
            }
            flash("File ricaricati dal disco.", "info")
        elif action in {"validate", "save"}:
            trails_payload, trails_error = parse_geojson_text(trails_text)
            pois_payload, pois_error = parse_geojson_text(pois_text)

            trails_report = (
                validate_feature_collection(trails_payload, kind="trails")
                if not trails_error
                else {"ok": False, "count": 0, "errors": [trails_error]}
            )
            pois_report = (
                validate_feature_collection(pois_payload, kind="pois")
                if not pois_error
                else {"ok": False, "count": 0, "errors": [pois_error]}
            )

            errors: list[dict[str, str | None]] = []
            for error in trails_report.get("errors", []):
                errors.append(
                    {
                        "message": f"trails.geojson: {error.get('message')}",
                        "line": error.get("line"),
                    }
                )
            for error in pois_report.get("errors", []):
                errors.append(
                    {
                        "message": f"pois.geojson: {error.get('message')}",
                        "line": error.get("line"),
                    }
                )

            report = {
                "ok": trails_report["ok"] and pois_report["ok"],
                "trails_count": trails_report["count"],
                "pois_count": pois_report["count"],
                "errors": errors[:10],
            }

            if action == "save" and report["ok"]:
                data_dir.mkdir(parents=True, exist_ok=True)
                trails_path.write_text(trails_text.strip() + "\n", encoding="utf-8")
                pois_path.write_text(pois_text.strip() + "\n", encoding="utf-8")
                flash("GeoJSON salvati correttamente.", "success")
            elif action == "save":
                flash("Correggi gli errori prima di salvare.", "error")
        else:
            flash("Azione non riconosciuta.", "error")

    if request.method == "GET":
        trails_text, trails_data, trails_error = read_geojson_file(trails_path)
        pois_text, pois_data, pois_error = read_geojson_file(pois_path)
        if trails_error or pois_error:
            flash("Caricamento file sentieri incompleto.", "warning")
        report = {
            "ok": not (trails_error or pois_error),
            "trails_count": len(trails_data.get("features", [])) if trails_data else 0,
            "pois_count": len(pois_data.get("features", [])) if pois_data else 0,
            "errors": [error for error in [trails_error, pois_error] if error],
        }

    _, saved_trails_data, _ = read_geojson_file(trails_path)
    _, saved_pois_data, _ = read_geojson_file(pois_path)
    current_trails = len(saved_trails_data.get("features", [])) if saved_trails_data else 0
    current_pois = len(saved_pois_data.get("features", [])) if saved_pois_data else 0

    return render_template(
        "admin/sentieri.html",
        trails_text=trails_text or "",
        pois_text=pois_text or "",
        report=report,
        current_trails=current_trails,
        current_pois=current_pois,
    )


@bp.route("/monitor")
@admin_required
def monitor_system():
    return render_template("admin/monitor.html")


@bp.route("/datasource-status")
@admin_required
def datasource_status():
    user = get_current_user()
    if not _is_owner(user):
        flash("Accesso riservato al proprietario.", "error")
        return redirect(url_for("admin.admin_home"))

    sources = [
        {"label": "Homepage", "key": "homepage", "path": get_curva_csv_path()},
        {"label": "/api/curva", "key": "api", "path": get_curva_csv_path()},
        {"label": "Telegram alerts", "key": "alerts", "path": get_curva_csv_path()},
    ]

    statuses: list[dict] = []
    for source in sources:
        status = get_curva_csv_status(source["path"])
        statuses.append({**source, **status})

    unique_paths = {item.get("csv_path_used") for item in statuses if item.get("csv_path_used")}
    mismatch = len(unique_paths) > 1

    return render_template(
        "admin/datasource_status.html",
        page_title="Datasource status",
        statuses=statuses,
        mismatch=mismatch,
    )


@bp.get("/test-ai-summary")
@admin_required
def test_ai_summary():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({"ok": False, "error": "Owner access required"}), 403

    summary = build_tremor_summary()
    cache_status = get_ai_cache_status()
    return jsonify(
        {
            "ok": True,
            "summary": summary,
            "ai_cache": cache_status,
        }
    )


@bp.route("/test-colored")
@admin_required
def test_colored_extraction():
    user = get_current_user()
    if not _is_owner(user):
        flash("Accesso riservato al proprietario.", "error")
        return redirect(url_for("admin.admin_home"))

    app = current_app
    request_id = request.headers.get("X-Request-Id") or uuid4().hex[:8]
    cache_key = _test_colored_cache_key()
    force_refresh = request.args.get("refresh") == "1"
    if not force_refresh:
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            current_app.logger.info(
                "[ADMIN] test-colored cache hit request_id=%s key=%s",
                request_id,
                cache_key,
            )
            return cached_response
    tremor_summary = build_tremor_summary()
    bands_cache = load_cached_thresholds()
    bands_debug = None
    if bands_cache:
        updated_at = bands_cache.get("updated_at")
        verification = bands_cache.get("verification") or {}
        checked_at = verification.get("checked_at")
        today = datetime.now(timezone.utc).date()
        detected_today = False
        if updated_at:
            try:
                detected_today = datetime.fromisoformat(updated_at).date() == today
            except ValueError:
                detected_today = False
        bands_debug = {
            "updated_at": updated_at,
            "detected_today": detected_today,
            "verification_status": verification.get("status"),
            "verification_checked_at": checked_at,
            "verification_notes": verification.get("notes"),
            "bands_px": bands_cache.get("bands_px") or {},
            "thresholds_mv": bands_cache.get("thresholds_mv") or {},
            "source": bands_cache.get("source"),
        }
    colored_url = (os.getenv("INGV_COLORED_URL") or "").strip()
    tail_param = request.args.get("tail", "200")
    peaks_param = request.args.get("peaks", "10")
    try:
        tail_limit = int(tail_param)
    except (TypeError, ValueError):
        tail_limit = 200
    try:
        peaks_limit = int(peaks_param)
    except (TypeError, ValueError):
        peaks_limit = 10
    tail_limit = max(1, min(tail_limit, 2000))
    peaks_limit = max(1, min(peaks_limit, 50))

    def _build_fallback_plot() -> tuple[str | None, str | None, str | None]:
        csv_path = get_curva_csv_path()
        df, reason = load_curva_dataframe(csv_path)
        if reason or df is None or df.empty:
            return None, None, None
        df = df.sort_values("timestamp")
        clean_pairs = []
        for ts, value in zip(df["timestamp"].tolist(), df["value"].tolist()):
            if value is None or not isfinite(value) or value <= 0:
                continue
            if ts is None:
                continue
            timestamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            clean_pairs.append((timestamp, float(value)))
        if not clean_pairs:
            return None, None, None
        last_ts = df["timestamp"].iloc[-1]
        last_ts_display = (
            last_ts.tz_convert("UTC").strftime("%d/%m/%Y %H:%M")
            if getattr(last_ts, "tz", None) is not None
            else last_ts.tz_localize("UTC").strftime("%d/%m/%Y %H:%M")
        )
        fallback_fig = build_tremor_figure(
            clean_pairs,
            mode="desktop",
            min_points=10,
            eps=1e-2,
        )
        fallback_plot = (
            plotly_offline.plot(
                fallback_fig, include_plotlyjs="inline", output_type="div"
            )
            if fallback_fig is not None
            else None
        )
        return fallback_plot, last_ts_display, str(csv_path)
    def _cache_response(response):
        if not force_refresh and TEST_COLORED_CACHE_TTL > 0:
            cache.set(cache_key, response, timeout=TEST_COLORED_CACHE_TTL)
        return response

    if not colored_url:
        fallback_plot_html, fallback_ts_display, fallback_csv_path = _build_fallback_plot()
        debug_assets = _load_latest_colored_debug()
        debug_json_data = None
        if debug_assets.get("debug_json"):
            try:
                debug_json_data = json.loads(
                    Path(debug_assets["debug_json"]).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                debug_json_data = None
        response = make_response(
            render_template(
                "admin/test_colored.html",
                error_message="INGV_COLORED_URL non configurato.",
                plot_html=fallback_plot_html,
                fallback_notice=bool(fallback_plot_html),
                fallback_timestamp=fallback_ts_display,
                fallback_csv_path=fallback_csv_path,
                raw_image=_encode_image_base64(debug_assets.get("raw_png")),
                overlay_image=_encode_image_base64(debug_assets.get("overlay")),
                mask_image=_encode_image_base64(debug_assets.get("mask")),
                mask_raw_image=_encode_image_base64(debug_assets.get("mask_raw")),
                mask_ink_image=_encode_image_base64(debug_assets.get("mask_ink")),
                mask_pretty_image=_encode_image_base64(debug_assets.get("mask_pretty")),
                crop_image=_encode_image_base64(debug_assets.get("crop")),
                overlay_markers_image=_encode_image_base64(
                    debug_assets.get("overlay_markers")
                ),
                debug_json=debug_json_data,
                debug_data=None,
                tremor_summary=tremor_summary,
                bands_debug=bands_debug,
            )
        )
        return _cache_response(response)

    try:
        png_path = download_colored_png(colored_url)
        timestamps, values, debug_paths = extract_series_from_colored(png_path)
        total_points = len(timestamps)
        nonfinite_count = 0
        clean_pairs = []
        for timestamp, value in zip(timestamps, values):
            if timestamp is None or value is None or not isfinite(value):
                nonfinite_count += 1
                continue
            if isinstance(timestamp, datetime):
                timestamp = timestamp.isoformat()
            elif not isinstance(timestamp, str):
                timestamp = str(timestamp)
            value_float = float(value)
            clean_pairs.append((timestamp, value_float))
        num_valid_pairs = len(clean_pairs)
        removed_pairs = total_points - num_valid_pairs
        eps = 1e-2
        clamped_count = sum(1 for _, v in clean_pairs if v < eps)
        nonpositive_count = sum(1 for _, v in clean_pairs if v <= 0)
        tail_pairs = clean_pairs[-tail_limit:] if tail_limit else []
        tail_values = [value for _, value in tail_pairs]
        tail_stats = {
            "min": min(tail_values) if tail_values else None,
            "max": max(tail_values) if tail_values else None,
            "mean": (sum(tail_values) / len(tail_values)) if tail_values else None,
        }
        peaks_pairs = sorted(tail_pairs, key=lambda item: item[1], reverse=True)[
            :peaks_limit
        ]
        debug_data = {
            "tail": [
                {"timestamp": timestamp, "value": value} for timestamp, value in tail_pairs
            ],
            "peaks": [
                {"timestamp": timestamp, "value": value}
                for timestamp, value in peaks_pairs
            ],
            "stats": tail_stats,
            "counts": {
                "total_points": total_points,
                "tail_points": len(tail_pairs),
                "removed_pairs": removed_pairs,
                "clamped_count": clamped_count,
                "nonfinite_count": nonfinite_count,
                "nonpositive_count": nonpositive_count,
            },
            "limits": {"tail": tail_limit, "peaks": peaks_limit},
        }
        current_app.logger.info(
            "[ADMIN] Colored plot data: timestamps=%s values=%s valid_pairs=%s removed=%s sample=%s",
            len(timestamps),
            len(values),
            num_valid_pairs,
            removed_pairs,
            clean_pairs[:3],
        )
        plot_error_message = None
        app.logger.info(
            f"Plotly log clamp: {clamped_count}/{len(clean_pairs)} values < {eps}"
        )
        fig = build_tremor_figure(
            clean_pairs,
            mode="desktop",
            min_points=10,
            eps=eps,
        )
        plot_html = (
            plotly_offline.plot(fig, include_plotlyjs="inline", output_type="div")
            if fig is not None
            else None
        )
        if plot_html is None:
            plot_error_message = (
                "Dati insufficienti per generare il grafico (meno di 10 punti validi)."
            )
        fallback_plot_html = None
        fallback_ts_display = None
        fallback_csv_path = None
        if plot_html is None:
            fallback_plot_html, fallback_ts_display, fallback_csv_path = _build_fallback_plot()
        raw_image = _encode_image_base64(png_path)
        overlay_image = _encode_image_base64(debug_paths.get("overlay"))
        mask_image = _encode_image_base64(debug_paths.get("mask"))
        mask_raw_image = _encode_image_base64(debug_paths.get("mask_raw"))
        mask_pretty_image = _encode_image_base64(debug_paths.get("mask_pretty"))
        crop_image = _encode_image_base64(debug_paths.get("crop"))
        overlay_markers_image = _encode_image_base64(debug_paths.get("overlay_markers"))
        debug_json_data = None
        if debug_paths.get("debug_json"):
            try:
                debug_json_data = json.loads(
                    Path(debug_paths["debug_json"]).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                debug_json_data = None
        response = make_response(
            render_template(
                "admin/test_colored.html",
                plot_html=plot_html or fallback_plot_html,
                fallback_notice=plot_html is None and bool(fallback_plot_html),
                fallback_timestamp=fallback_ts_display,
                fallback_csv_path=fallback_csv_path,
                raw_image=raw_image,
                overlay_image=overlay_image,
                mask_image=mask_image,
                mask_raw_image=mask_raw_image,
                mask_ink_image=_encode_image_base64(debug_paths.get("mask_ink")),
                mask_pretty_image=mask_pretty_image,
                crop_image=crop_image,
                overlay_markers_image=overlay_markers_image,
                error_message=plot_error_message,
                debug_data=debug_data,
                debug_json=debug_json_data,
                tremor_summary=tremor_summary,
                bands_debug=bands_debug,
            )
        )
        return _cache_response(response)
    except Exception as exc:  # pragma: no cover - debug view safety net
        current_app.logger.error(
            "[ADMIN] Colored extraction failed request_id=%s reason=%s",
            request_id,
            exc,
            exc_info=True,
        )
        fallback_plot_html, fallback_ts_display, fallback_csv_path = _build_fallback_plot()
        debug_assets = _load_latest_colored_debug()
        debug_json_data = None
        if debug_assets.get("debug_json"):
            try:
                debug_json_data = json.loads(
                    Path(debug_assets["debug_json"]).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                debug_json_data = None
        response = make_response(
            render_template(
                "admin/test_colored.html",
                error_message=str(exc),
                plot_html=fallback_plot_html,
                fallback_notice=bool(fallback_plot_html),
                fallback_timestamp=fallback_ts_display,
                fallback_csv_path=fallback_csv_path,
                raw_image=_encode_image_base64(debug_assets.get("raw_png")),
                overlay_image=_encode_image_base64(debug_assets.get("overlay")),
                mask_image=_encode_image_base64(debug_assets.get("mask")),
                mask_raw_image=_encode_image_base64(debug_assets.get("mask_raw")),
                mask_ink_image=_encode_image_base64(debug_assets.get("mask_ink")),
                mask_pretty_image=_encode_image_base64(debug_assets.get("mask_pretty")),
                crop_image=_encode_image_base64(debug_assets.get("crop")),
                overlay_markers_image=_encode_image_base64(
                    debug_assets.get("overlay_markers")
                ),
                debug_data=None,
                debug_json=debug_json_data,
                tremor_summary=tremor_summary,
                bands_debug=bands_debug,
            )
        )
        return _cache_response(response)


@bp.route("/cron/summary")
@admin_required
def cron_summary():
    now = datetime.now(timezone.utc)
    window = timedelta(hours=24)
    start_dt = now - window

    base_query = CronRun.query.filter(CronRun.job_type == "check_alerts")
    last_run = base_query.order_by(CronRun.started_at.desc()).first()

    runs_24h = base_query.filter(CronRun.started_at >= start_dt).count()
    errors_24h = (
        base_query.filter(
            CronRun.started_at >= start_dt,
            CronRun.status == "error",
        ).count()
    )
    sent_24h = (
        db.session.query(func.coalesce(func.sum(CronRun.sent_count), 0))
        .filter(
            CronRun.job_type == "check_alerts",
            CronRun.started_at >= start_dt,
        )
        .scalar()
        or 0
    )
    skipped_24h = (
        db.session.query(func.coalesce(func.sum(CronRun.skipped_count), 0))
        .filter(
            CronRun.job_type == "check_alerts",
            CronRun.started_at >= start_dt,
        )
        .scalar()
        or 0
    )

    return jsonify(
        {
            "last_run": last_run.serialize() if last_run else None,
            "runs_24h": runs_24h,
            "errors_24h": errors_24h,
            "sent_24h": int(sent_24h),
            "skipped_24h": int(skipped_24h),
        }
    )


@bp.route("/cron/runs")
@admin_required
def cron_runs():
    limit = _coerce_positive_int(request.args.get("limit"), default=50)
    range_param = request.args.get("range")
    job_type = (request.args.get("job_type") or "check_alerts").strip().lower()

    query = CronRun.query
    if job_type:
        query = query.filter(CronRun.job_type == job_type)

    if range_param:
        window = _parse_range_window(range_param)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - window
        query = query.filter(CronRun.started_at >= start_dt, CronRun.started_at <= end_dt)

    runs = query.order_by(CronRun.started_at.desc()).limit(min(limit, 250)).all()
    return jsonify({"runs": [run.serialize() for run in runs]})


def _apply_cron_run_filters(query):
    job_type = (request.args.get("job_type") or "").strip().lower()
    ok_param = (request.args.get("ok") or "").strip().lower()
    start_param = request.args.get("start")
    end_param = request.args.get("end")
    range_param = request.args.get("range")

    if job_type:
        query = query.filter(CronRun.job_type == job_type)

    if ok_param in {"true", "false"}:
        query = query.filter(CronRun.ok.is_(ok_param == "true"))

    start_dt = _parse_datetime_param(start_param)
    end_dt = _parse_datetime_param(end_param)
    if range_param and not (start_dt or end_dt):
        window = _parse_range_window(range_param)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - window

    if start_dt:
        query = query.filter(CronRun.created_at >= start_dt)
    if end_dt:
        query = query.filter(CronRun.created_at <= end_dt)
    return query


@bp.route("/api/monitor/runs")
@admin_required
def monitor_runs():
    limit = _coerce_positive_int(request.args.get("limit"), default=100)
    query = _apply_cron_run_filters(CronRun.query)
    runs = (
        query.order_by(CronRun.created_at.desc())
        .limit(min(limit, 250))
        .all()
    )
    return jsonify({"runs": [run.serialize() for run in runs]})


@bp.route("/api/monitor/runs/<int:run_id>")
@admin_required
def monitor_run_detail(run_id: int):
    run = CronRun.query.get_or_404(run_id)
    return jsonify(run.serialize(include_payload=True))


@bp.route("/api/monitor/kpis")
@admin_required
def monitor_kpis():
    window = _parse_range_window(request.args.get("range"))
    now = datetime.now(timezone.utc)
    start_dt = now - window

    base_query = CronRun.query.filter(CronRun.created_at >= start_dt)
    runs_total = base_query.count()
    failures_count = base_query.filter(CronRun.ok.is_(False)).count()
    sent_total = (
        db.session.query(func.coalesce(func.sum(CronRun.sent_count), 0))
        .filter(CronRun.created_at >= start_dt)
        .scalar()
        or 0
    )
    skipped_total = (
        db.session.query(func.coalesce(func.sum(CronRun.skipped_count), 0))
        .filter(CronRun.created_at >= start_dt)
        .scalar()
        or 0
    )

    last_run = CronRun.query.order_by(CronRun.created_at.desc()).first()
    last_csv_run = (
        CronRun.query.filter(CronRun.job_type == "csv_updater")
        .order_by(CronRun.created_at.desc())
        .first()
    )
    if not last_csv_run:
        last_csv_run = (
            CronRun.query.filter(CronRun.csv_mtime.isnot(None))
            .order_by(CronRun.created_at.desc())
            .first()
        )

    last_point_run = (
        CronRun.query.filter(CronRun.last_point_ts.isnot(None))
        .order_by(CronRun.created_at.desc())
        .first()
    )

    status = "DOWN"
    if last_run:
        age_seconds = (now - last_run.created_at).total_seconds() if last_run.created_at else None
        recent_failures = failures_count > 0
        if age_seconds is not None and age_seconds > 60 * 90:
            status = "DOWN"
        elif not last_run.ok:
            status = "DOWN"
        elif recent_failures:
            status = "DEGRADED"
        else:
            status = "OK"

    health_checks = {
        "db_reachable": True,
        "csv_exists": False,
        "csv_mtime": None,
        "telegram_configured": bool(current_app.config.get("TELEGRAM_BOT_TOKEN")),
        "premium_chat_users": 0,
    }

    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        health_checks["db_reachable"] = False

    csv_path = get_curva_csv_path()
    if csv_path.exists():
        health_checks["csv_exists"] = True
        try:
            stat = csv_path.stat()
            health_checks["csv_mtime"] = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            health_checks["csv_mtime"] = None

    premium_chat_count = (
        User.query.filter(
            User.telegram_opt_in.is_(True),
            or_(User.telegram_chat_id.isnot(None), User.chat_id.isnot(None)),
            User.premium_status_clause(),
        )
        .count()
    )
    health_checks["premium_chat_users"] = int(premium_chat_count or 0)

    return jsonify(
        {
            "range": request.args.get("range") or "24h",
            "status": status,
            "last_run": last_run.serialize() if last_run else None,
            "runs_total": runs_total,
            "failures_count": failures_count,
            "sent_total": int(sent_total),
            "skipped_total": int(skipped_total),
            "last_csv_update": last_csv_run.serialize() if last_csv_run else None,
            "last_point": last_point_run.serialize() if last_point_run else None,
            "health_checks": health_checks,
        }
    )


@bp.route("/recompute-badges", methods=["POST"])
@admin_required
def recompute_badges_admin():
    raw_user_id = request.form.get("user_id") or request.args.get("user_id")
    try:
        if raw_user_id:
            user_id = int(raw_user_id)
            recompute_badges_for_user(user_id)
            db.session.commit()
            return jsonify({"status": "ok", "user_id": user_id})

        user_ids = [user_id for (user_id,) in db.session.query(User.id).all()]
        for user_id in user_ids:
            recompute_badges_for_user(user_id)
        db.session.commit()
        return jsonify({"status": "ok", "processed": len(user_ids)})
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid user_id"}), 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to recompute badges via admin endpoint")
        return jsonify({"status": "error", "message": "Database error"}), 500


@bp.post("/recompute-badges-ui")
@admin_required
def recompute_badges_ui():
    csrf_token = request.form.get("csrf_token")
    if not _is_csrf_valid(csrf_token):
        flash("Token CSRF non valido. Riprova.", "error")
        return redirect(url_for("admin.admin_home", _anchor="maintenance-gamification"))

    raw_user_id = (request.form.get("user_id") or "").strip()
    try:
        if raw_user_id:
            user_id = int(raw_user_id)
            recompute_badges_for_user(user_id)
            db.session.commit()
            flash(f"Badge ricalcolati per l'utente {user_id}.", "success")
        else:
            user_ids = [user_id for (user_id,) in db.session.query(User.id).all()]
            for user_id in user_ids:
                recompute_badges_for_user(user_id)
            db.session.commit()
            flash(f"Badge ricalcolati per {len(user_ids)} utenti.", "success")
    except ValueError:
        flash("User ID non valido.", "error")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to recompute badges via admin UI")
        flash("Errore durante il ricalcolo dei badge.", "error")

    return redirect(url_for("admin.admin_home", _anchor="maintenance-gamification"))
