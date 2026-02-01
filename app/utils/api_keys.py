from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from functools import wraps
from time import perf_counter
from typing import Callable, Tuple

from flask import jsonify, make_response, request, g

from ..models import ApiClient, ApiKey, ApiUsage, db
from .attribution import powered_by_payload
from .rate_limit import enforce_rate_limits


def generate_api_key() -> Tuple[str, str, str]:
    """Generate a raw API key along with its prefix and hash."""
    raw_key = secrets.token_urlsafe(32)
    while len(raw_key) < 40:
        raw_key = secrets.token_urlsafe(32)
    prefix = raw_key[:8]
    key_hash = hash_api_key(raw_key)
    return raw_key, prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _error_response(
    code: str, message: str, status_code: int, extra: dict | None = None
):
    payload = {
        "error": {"code": code, "message": message},
        "powered_by": powered_by_payload(),
    }
    if extra:
        payload.update(extra)
    return make_response(jsonify(payload), status_code)


def require_api_key(allowed_plans: list[str] | None = None):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            started_at = perf_counter()
            response = None
            api_key = None
            client = None
            try:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    response = _error_response(
                        "missing_api_key",
                        "API key mancante o non valida.",
                        401,
                    )
                    return response

                raw_key = auth_header.replace("Bearer", "", 1).strip()
                if not raw_key:
                    response = _error_response(
                        "missing_api_key",
                        "API key mancante o non valida.",
                        401,
                    )
                    return response

                key_hash = hash_api_key(raw_key)
                api_key = (
                    ApiKey.query.join(ApiClient)
                    .filter(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_revoked.is_(False),
                        ApiClient.is_active.is_(True),
                    )
                    .first()
                )

                if not api_key:
                    response = _error_response(
                        "invalid_api_key",
                        "API key non valida.",
                        401,
                    )
                    return response

                client = api_key.client
                if allowed_plans and client.plan not in allowed_plans:
                    response = _error_response(
                        "plan_not_allowed",
                        "Il piano non consente l'accesso a questa risorsa.",
                        403,
                    )
                    return response

                rate_status = enforce_rate_limits(api_key.id, client.plan)
                api_key.last_used_at = datetime.now(timezone.utc)
                if not rate_status.allowed:
                    response = _error_response(
                        "rate_limited",
                        "Limite di richieste superato per il piano.",
                        429,
                        extra={
                            "limits": {
                                "minute_limit": rate_status.minute_limit,
                                "day_limit": rate_status.day_limit,
                            },
                            "counts": {
                                "minute": rate_status.minute_count,
                                "day": rate_status.day_count,
                            },
                        },
                    )
                    return response

                g.api_key = api_key
                g.api_client = client
                response = make_response(func(*args, **kwargs))
                return response
            finally:
                if api_key is not None:
                    status_code = response.status_code if response is not None else 500
                    latency_ms = int((perf_counter() - started_at) * 1000)
                    db.session.add(
                        ApiUsage(
                            key_id=api_key.id,
                            endpoint=request.path,
                            method=request.method,
                            status_code=status_code,
                            ts=datetime.now(timezone.utc),
                            latency_ms=latency_ms,
                        )
                    )
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

        return wrapper

    return decorator
