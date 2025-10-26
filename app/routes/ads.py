from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Tuple

from flask import Blueprint, Response, current_app, make_response, redirect, request
from itsdangerous import BadSignature, URLSafeSerializer

from ..models import db
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
from ..utils.auth import get_current_user


PIXEL_BYTES = (
    b"GIF89a"  # Header
    b"\x01\x00\x01\x00"  # Logical Screen Size 1x1
    b"\x80"  # GCT follows for 2 colors
    b"\x00"  # Background color index
    b"\x00"  # Pixel aspect ratio
    b"\x00\x00\x00"  # Color #1: black
    b"\xff\xff\xff"  # Color #2: white
    b"\x21\xf9\x04\x01\x00\x00\x00\x00"  # Graphics Control Extension
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00"  # Image Descriptor
    b"\x02\x02L\x01\x00"  # Image Data
    b";"  # Trailer
)


bp = Blueprint("ads", __name__)


@bp.route("/ads/health")
def health() -> str:
    return "ok"


def _get_secret_key() -> str:
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY is required for ad tracking")
    return secret


def _get_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(secret_key=_get_secret_key(), salt="ads-tracking")


def _get_or_create_session_id() -> Tuple[str, bool]:
    cookie_name = "em_ads_sid"
    serializer = _get_serializer()
    raw_cookie = request.cookies.get(cookie_name)
    session_id = None

    if raw_cookie:
        try:
            session_id = serializer.loads(raw_cookie)
        except BadSignature:
            session_id = None

    if not session_id:
        session_id = secrets.token_urlsafe(16)
        return session_id, True

    return session_id, False


def _hash_ip(ip: str | None) -> str:
    value = f"{_get_secret_key()}:{ip or 'unknown'}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _should_record_impression(
    banner_id: int, session_id: str, now: datetime
) -> bool:
    if SponsorBannerImpression is None:
        return False
    cutoff = now - timedelta(minutes=30)
    existing = (
        SponsorBannerImpression.query.filter_by(
            banner_id=banner_id, session_id=session_id
        )
        .filter(SponsorBannerImpression.ts >= cutoff)
        .first()
    )
    return existing is None


def _record_impression(banner: SponsorBanner, session_id: str, page: str) -> None:
    if SponsorBannerImpression is None:
        return
    now = datetime.utcnow()
    if not _should_record_impression(banner.id, session_id, now):
        return

    user = get_current_user()
    impression = SponsorBannerImpression(
        banner_id=banner.id,
        ts=now,
        page=page[:255] if page else None,
        session_id=session_id,
        user_id=user.id if user else None,
        ip_hash=_hash_ip(_client_ip()),
    )
    db.session.add(impression)
    db.session.commit()


def _record_click(banner: SponsorBanner, session_id: str, page: str) -> None:
    if SponsorBannerClick is None:
        return
    user = get_current_user()
    click = SponsorBannerClick(
        banner_id=banner.id,
        ts=datetime.utcnow(),
        page=page[:255] if page else None,
        session_id=session_id,
        user_id=user.id if user else None,
        ip_hash=_hash_ip(_client_ip()),
    )
    db.session.add(click)
    db.session.commit()


def _pixel_response() -> Response:
    response = make_response(PIXEL_BYTES)
    response.headers["Content-Type"] = "image/gif"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _build_tracking_response(session_id: str, set_cookie: bool) -> Response:
    response = _pixel_response()

    if set_cookie:
        serializer = _get_serializer()
        signed_value = serializer.dumps(session_id)
        response.set_cookie(
            "em_ads_sid",
            signed_value,
            max_age=60 * 60 * 24 * 365,
            secure=request.is_secure,
            httponly=True,
            samesite="Lax",
        )

    return response


def _decorate_with_rate_limit(limit: str):
    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = current_app.extensions.get("limiter")
            if limiter:
                return limiter.limit(limit)(func)(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    return decorator


@bp.route("/ads/i/<int:banner_id>.gif")
@_decorate_with_rate_limit("240 per hour")
def banner_impression(banner_id: int):
    if SponsorBanner is None or SponsorBannerImpression is None:
        return _pixel_response()

    try:
        banner = SponsorBanner.query.get(banner_id)
    except Exception as exc:  # pragma: no cover - defensive fallback
        current_app.logger.warning(
            "Failed to load banner %s for impression: %s", banner_id, exc
        )
        return _pixel_response()

    if not banner or not banner.active:
        return _pixel_response()

    session_id, set_cookie = _get_or_create_session_id()
    page = request.args.get("page") or request.referrer or "unknown"

    try:
        _record_impression(banner, session_id, page)
    except Exception as exc:  # pragma: no cover - fail safe
        current_app.logger.exception("Failed to record banner impression: %s", exc)

    return _build_tracking_response(session_id, set_cookie)


def _append_utm_parameters(url: str, banner_id: int) -> str:
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    utm_params = {
        "utm_source": "etnamonitor",
        "utm_medium": "banner",
        "utm_campaign": f"sponsor_{banner_id}",
    }
    for key, value in utm_params.items():
        if key not in query:
            query[key] = value
    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


@bp.route("/ads/c/<int:banner_id>")
@_decorate_with_rate_limit("240 per hour")
def banner_click(banner_id: int):
    fallback_url = request.args.get("fallback") or "/"

    if SponsorBanner is None or SponsorBannerClick is None:
        return redirect(fallback_url)

    try:
        banner = SponsorBanner.query.get(banner_id)
    except Exception as exc:  # pragma: no cover - defensive fallback
        current_app.logger.warning(
            "Failed to load banner %s for click: %s", banner_id, exc
        )
        return redirect(fallback_url)

    if not banner:
        return redirect(fallback_url)

    if not banner.active:
        return redirect(banner.target_url)

    session_id, set_cookie = _get_or_create_session_id()
    page = request.args.get("page") or request.referrer or "unknown"

    try:
        _record_click(banner, session_id, page)
    except Exception as exc:  # pragma: no cover - fail safe
        current_app.logger.exception("Failed to record banner click: %s", exc)

    target_url = _append_utm_parameters(banner.target_url, banner.id)
    response = redirect(target_url)
    if set_cookie:
        serializer = _get_serializer()
        response.set_cookie(
            "em_ads_sid",
            serializer.dumps(session_id),
            max_age=60 * 60 * 24 * 365,
            secure=request.is_secure,
            httponly=True,
            samesite="Lax",
        )

    return response
