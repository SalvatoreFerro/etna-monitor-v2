import secrets
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

from ..models import db
from ..models.user import User
from ..utils.auth import check_password, hash_password
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

bp = Blueprint("auth", __name__)
legacy_bp = Blueprint("legacy_auth", __name__ + "_legacy")


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
        google_id = profile.get("sub")
        email = profile.get("email")

        if not google_id or not email:
            flash("Google profile is missing required information.", "error")
            return redirect(url_for("auth.login"))

        user = User.query.filter_by(google_id=google_id).first()
        if not user and email:
            user = User.query.filter_by(email=email).first()

        if user:
            user.google_id = google_id
            user.email = email or user.email
            user.name = profile.get("name")
            user.picture_url = profile.get("picture")
            if user.password_hash is None:
                user.password_hash = ""
        else:
            user = User(
                email=email,
                google_id=google_id,
                name=profile.get("name"),
                picture_url=profile.get("picture"),
                password_hash="",
                plan_type="free",
            )
            db.session.add(user)

        admin_set = current_app.config.get("ADMIN_EMAILS_SET", set())
        if email and email.lower() in admin_set:
            user.is_admin = True
        current_app.logger.info(
            f"[LOGIN] user={email} is_admin={getattr(user, 'is_admin', None)} in_set={email and email.lower() in admin_set}"
        )

        if getattr(user, "plan_type", None) is None:
            user.plan_type = "free"

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing_user = None
            if email:
                existing_user = User.query.filter_by(email=email).first()
            if not existing_user and google_id:
                existing_user = User.query.filter_by(google_id=google_id).first()

            if not existing_user:
                raise

            existing_user.google_id = google_id
            existing_user.email = email or existing_user.email
            existing_user.name = profile.get("name")
            existing_user.picture_url = profile.get("picture")
            if existing_user.password_hash is None:
                existing_user.password_hash = ""

            db.session.add(existing_user)

            admin_set = current_app.config.get("ADMIN_EMAILS_SET", set())
            if email and email.lower() in admin_set:
                existing_user.is_admin = True
            current_app.logger.info(
                f"[LOGIN] user={email} is_admin={getattr(existing_user, 'is_admin', None)} in_set={email and email.lower() in admin_set}"
            )

            if getattr(existing_user, "plan_type", None) is None:
                existing_user.plan_type = "free"
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception(
                    "[LOGIN] Database error while merging Google account"
                )
                flash("Servizio in aggiornamento, riprova tra qualche minuto.", "error")
                return redirect(url_for("auth.login"))

            user = existing_user
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "[LOGIN] Database error during Google OAuth commit"
            )
            flash("Servizio in aggiornamento, riprova tra qualche minuto.", "error")
            return redirect(url_for("auth.login"))

        # Persist the OAuth session information to simplify future API calls or
        # refresh flows. Tokens remain in the server-side session.
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
    session.pop("user_id", None)
    session.pop("oauth_state", None)
    session.clear()
    flash("Sei stato disconnesso.", "info")
    return redirect(url_for("main.index"))
