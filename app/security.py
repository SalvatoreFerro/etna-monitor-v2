"""Security helpers for HTTP response headers."""

from __future__ import annotations

import copy
from typing import Dict, List, Union

from flask import request
from flask_talisman import Talisman

CSPDirective = Dict[str, Union[List[str], str]]

BASE_CSP: CSPDirective = {
    "default-src": "'self'",
    "script-src": ["'self'", "https://www.googletagmanager.com"],
    "connect-src": [
        "'self'",
        "https://www.google-analytics.com",
        "https://region1.google-analytics.com",
    ],
    "img-src": ["'self'", "https://www.google-analytics.com", "data:"],
    "style-src": ["'self'", "'unsafe-inline'"],
}


def apply_csp_headers(response) -> object:
    """Attach the Content-Security-Policy header to a Flask response."""

    policy_source = None
    try:
        policy_source = talisman._get_local_options().get("content_security_policy")
    except Exception:
        policy_source = None

    if (
        policy_source is not None
        and policy_source is not talisman.content_security_policy
        and "Content-Security-Policy" in response.headers
    ):
        return response

    policy = build_csp()
    nonce = getattr(request, "csp_nonce", None)
    if nonce:
        directive = policy.get("script-src")
        if isinstance(directive, list):
            directive = directive + [f"'nonce-{nonce}'"]
        elif isinstance(directive, str):
            directive = f"{directive} 'nonce-{nonce}'"
        policy["script-src"] = directive

    response.headers["Content-Security-Policy"] = serialize_csp(policy)
    return response


def build_csp() -> CSPDirective:
    """Return a deep copy of the base Content Security Policy."""

    return copy.deepcopy(BASE_CSP)


def serialize_csp(policy: CSPDirective) -> str:
    """Serialize a CSP policy dictionary into a header string."""

    parts: List[str] = []
    for directive, value in policy.items():
        if isinstance(value, str):
            parts.append(f"{directive} {value}")
        else:
            parts.append(f"{directive} {' '.join(value)}")
    return "; ".join(parts)


talisman = Talisman()
