import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
import traceback
from requests import Response
from requests import Session
from requests.exceptions import ProxyError
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from flask_login import login_user, logout_user

from sqlalchemy import func, inspect
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)

from ..models import db
from ..models.user import User
from ..utils.auth import check_password, hash_password

bp = Blueprint("auth", __name__)
legacy_bp = Blueprint("legacy_auth", __name__ + "_legacy")


_GOOGLE_ID_COLUMN_SUPPORTED: bool | None = None


def _supports_google_id_column(force_refresh: bool = False) -> bool:
    """Return ``True`` when the users table exposes the ``google_id`` column."""

    global _GOOGLE_ID_COLUMN_SUPPORTED

    if not force_refresh and _GOOGLE_ID_COLUMN_SUPPORTED is not None:
        return _GOOGLE_ID_COLUMN_SUPPORTED

    try:
        inspector = inspect(db.engine)
        _GOOGLE_ID_COLUMN_SUPPORTED = any(
            column.get("name") == "google_id"
            for column in inspector.get_columns(User.__tablename__)
        )
    except SQLAlchemyError:
        # Failing the inspection should not break the login flow; assume the
        # column exists so the previous behaviour remains unchanged.
        current_app.logger.exception(
            "[LOGIN] Could not inspect users table for google_id column"
        )
        _GOOGLE_ID_COLUMN_SUPPORTED = True

    return _GOOGLE_ID_COLUMN_SUPPORTED


def _disable_google_id_column_usage():
    """Record that the database does not support the google_id column."""

    global _GOOGLE_ID_COLUMN_SUPPORTED
    if _GOOGLE_ID_COLUMN_SUPPORTED is not False:
        current_app.logger.warning(
            "[LOGIN] Disabling google_id usage due to runtime database error"
        )
        _GOOGLE_ID_COLUMN_SUPPORTED = False


def _google_oauth_request(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: int = 10,
) -> Response:
    """Perform a Google OAuth HTTP request with proxy fallbacks.

    Render and other hosting platforms may inject outbound proxy settings via
    environment variables. In some environments those proxies block calls to
    Google domains, leading to ``ProxyError`` exceptions and a failed sign-in
    experience. To make the login flow resilient we retry once without the
    inherited proxy configuration when a proxy failure is detected.
    """

    try:
        with Session() as session:
            return session.request(
                method,
                url,
                data=data,
                headers=headers,
                timeout=timeout,
            )
    except ProxyError as proxy_exc:
        current_app.logger.warning(
            "Google OAuth request blocked by proxy. Retrying without proxies.",
            exc_info=proxy_exc,
        )
        with Session() as session:
            session.trust_env = False
            return session.request(
                method,
                url,
                data=data,
                headers=headers,
                timeout=timeout,
            )

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _query_with_retry(query_callable):
    """Execute a SQLAlchemy query and retry once after refreshing the pool."""

    try:
        return query_callable()
    except OperationalError as exc:
        current_app.logger.warning(
            "[LOGIN] Database connection error, refreshing pool and retrying once.",
            exc_info=exc,
        )
        db.session.rollback()
        try:
            db.engine.dispose()
        except Exception:
            current_app.logger.exception(
                "[LOGIN] Failed to dispose SQLAlchemy engine after connection error"
            )
        return query_callable()


# ---------------------------------------------------------------------------
# Legacy password-based helpers (DEPRECATED)
#
# Historically the authentication blueprint exposed email/password flows such
# as `/register` and `/login` backed by `hash_password` and `check_password`
# from ``app.utils.auth``. The project has since moved to Google OAuth based
# authentication and these helpers remain only for reference. They should not
# be used for new features and can be removed once all templates stop
# referencing the old routes.
# ---------------------------------------------------------------------------


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Render the login call-to-action or handle the legacy password flow."""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            return ("Email and password are required", 400)

        user = User.query.filter_by(email=email).first()
        if not user or not check_password(password, user.password_hash or ""):
            return ("Invalid email or password", 401)

        login_user(user)
        session["user_id"] = user.id
        return redirect(url_for("dashboard.dashboard_home"))

    return render_template("auth/login.html", next_page=request.args.get("next"))


@bp.route("/register", methods=["POST"])
def register():
    """Minimal email/password registration kept for unit tests."""

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        return ("Email and password are required", 400)

    existing = User.query.filter_by(email=email).first()
    if existing:
        return ("Email already registered", 400)

    user = User(email=email, password_hash=hash_password(password))
    db.session.add(user)
    db.session.commit()

    login_user(user)
    session["user_id"] = user.id
    return redirect(url_for("dashboard.dashboard_home"))


@legacy_bp.route("/register", methods=["POST"])
def legacy_register():
    return register()


@legacy_bp.route("/login", methods=["GET", "POST"])
def legacy_login():
    return login()


@bp.route("/google", methods=["GET", "POST"])
def auth_google():
    """Kick off the Google OAuth flow."""
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    if not client_id:
        flash("Google OAuth is not configured.", "error")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    next_page = request.args.get("next") or request.form.get("next")
    if next_page:
        session["post_login_redirect"] = next_page

    # Use the redirect URI configured in the environment to match the value
    # registered with Google. Fall back to a dynamically generated URL for
    # local development when the env variable is missing.
    redirect_uri = (
        current_app.config.get("GOOGLE_REDIRECT_URI")
        or url_for("auth.auth_callback", _external=True)
    )
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "select_account consent",
        "access_type": "offline",
    }

    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    return redirect(f"{authorization_endpoint}?{urlencode(params)}")


@bp.route("/callback", methods=["GET"])
def auth_callback():
    """Exchange the authorization code for user info and log the user in."""
    error = request.args.get("error")
    if error:
        flash(f"Google OAuth failed: {error}", "error")
        return redirect(url_for("auth.login"))

    state = request.args.get("state")
    if not state or state != session.pop("oauth_state", None):
        flash("Invalid OAuth state. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("Missing authorization code from Google.", "error")
        return redirect(url_for("auth.login"))

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        flash("Google OAuth is not configured.", "error")
        return redirect(url_for("auth.login"))

    token_endpoint = "https://oauth2.googleapis.com/token"
    # Reuse the same redirect URI used during the authorization request to
    # satisfy Google's strict redirect matching rules.
    redirect_uri = (
        current_app.config.get("GOOGLE_REDIRECT_URI")
        or url_for("auth.auth_callback", _external=True)
    )
    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    try:
        token_response = _google_oauth_request(
            "POST",
            token_endpoint,
            data=token_payload,
            timeout=10,
        )
        if token_response.status_code != 200:
            current_app.logger.error(
                "Google token endpoint failed with status %s: %s",
                token_response.status_code,
                token_response.text,
            )
            flash("Could not verify Google credentials.", "error")
            return redirect(url_for("auth.login"))

        token_json = token_response.json()
        access_token = token_json.get("access_token")
        id_token = token_json.get("id_token")
        refresh_token = token_json.get("refresh_token")
        if not access_token:
            flash("Google did not return an access token.", "error")
            return redirect(url_for("auth.login"))

        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_response = _google_oauth_request(
            "GET",
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )

        if userinfo_response.status_code != 200:
            current_app.logger.error(
                "Google userinfo endpoint failed with status %s: %s",
                userinfo_response.status_code,
                userinfo_response.text,
            )
            flash("Unable to fetch Google profile information.", "error")
            return redirect(url_for("auth.login"))

        profile = userinfo_response.json()
        google_id = (profile.get("sub") or "").strip()
        email = (profile.get("email") or "").strip().lower()
        name = (profile.get("name") or "").strip()
        picture_url = (profile.get("picture") or "").strip()

        if not google_id or not email:
            flash("Google profile is missing required information.", "error")
            return redirect(url_for("auth.login"))

        google_id_supported = _supports_google_id_column()
        user = None

        if google_id_supported and google_id:
            try:
                user = _query_with_retry(
                    lambda: User.query.filter_by(google_id=google_id).first()
                )
            except ProgrammingError:
                current_app.logger.exception(
                    "[LOGIN] google_id lookup failed; falling back to email only"
                )
                _disable_google_id_column_usage()
                google_id_supported = False
                user = None

        if not user and email:
            user = _query_with_retry(
                lambda: User.query.filter(func.lower(User.email) == email).first()
            )
            if user and google_id_supported and google_id:
                user.google_id = google_id

        if user:
            if google_id_supported and google_id:
                user.google_id = google_id
            if not user.name and name:
                user.name = name
            if not user.picture_url and picture_url:
                user.picture_url = picture_url
            if user.password_hash is None:
                user.password_hash = ""
        else:
            user = User(
                email=email,
                name=name or None,
                picture_url=picture_url or None,
                password_hash="",
                plan_type="free",
                created_at=datetime.now(timezone.utc),
            )
            if google_id_supported and google_id:
                user.google_id = google_id
            db.session.add(user)

        admin_set = current_app.config.get("ADMIN_EMAILS_SET", set())
        if user.id is None and email and email in admin_set:
            user.is_admin = True

        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            current_app.logger.error(
                "[LOGIN] Integrity error while storing Google login: %s",
                getattr(exc, "orig", exc),
                exc_info=exc,
            )
            flash("Servizio in aggiornamento, riprova tra qualche minuto.", "error")
            return redirect(url_for("auth.login"))
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "[LOGIN] Database error during Google OAuth commit"
            )
            flash("Servizio in aggiornamento, riprova tra qualche minuto.", "error")
            return redirect(url_for("auth.login"))

        login_user(user)
        session["user_id"] = user.id
        session["google_access_token"] = access_token
        if refresh_token:
            session["google_refresh_token"] = refresh_token
        if id_token:
            session["google_id_token"] = id_token
        flash("Login effettuato con Google!", "success")

        next_page = session.pop("post_login_redirect", None) or request.args.get("next")
        if next_page:
            return redirect(next_page)
        return redirect(url_for("dashboard.dashboard_home"))
    except Exception:
        current_app.logger.exception("OAuth callback failed")
        current_app.logger.debug("Full traceback: %s", traceback.format_exc())
        flash("We could not complete the Google sign-in. Please try again.", "error")
        return redirect(url_for("auth.login"))


@bp.route("/logout", methods=["GET"])
def logout():
    logout_user()
    session.pop("user_id", None)
    session.pop("oauth_state", None)
    session.clear()
    flash("Sei stato disconnesso.", "info")
    return redirect(url_for("main.index"))

