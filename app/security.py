"""Security helpers for HTTP response headers."""
from __future__ import annotations

import copy
from typing import Dict, List, Union

from flask import request
from flask_talisman import Talisman

CSPDirective = Dict[str, Union[List[str], str]]

BASE_CSP: CSPDirective = {
    "default-src": "'self'",
    "script-src": [
        "'self'",
        "https://www.googletagmanager.com",
        "https://www.google-analytics.com",
        "https://www.googletagmanager.com/gtag/js",
    ],
    "connect-src": [
        "'self'",
        "https://www.google-analytics.com",
        "https://region1.google-analytics.com",
        "https://stats.g.doubleclick.net",
    ],
    "img-src": [
        "'self'",
        "https://www.google-analytics.com",
        "https://www.googletagmanager.com",
        "https://stats.g.doubleclick.net",
        "data:",
    ],
    "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
    "font-src": ["'self'", "https://fonts.gstatic.com"],
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-src": [
        "'self'",
        "https://www.googletagmanager.com",
        "https://region1.google-analytics.com",
    ],
}


def apply_csp_headers(response) -> object:
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

    policy = copy.deepcopy(BASE_CSP)

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


def serialize_csp(policy: CSPDirective) -> str:
    parts: List[str] = []
    for directive, value in policy.items():
        if isinstance(value, str):
            parts.append(f"{directive} {value}")
        else:
            parts.append(f"{directive} {' '.join(value)}")
    return "; ".join(parts)


talisman = Talisman()
