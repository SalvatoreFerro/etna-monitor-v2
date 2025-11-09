"""Security helpers for HTTP response headers."""
from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Union

from flask import request
from flask_talisman import Talisman

CSPDirective = Dict[str, Union[List[str], str]]

SCRIPT_GOOGLE = [
    "https://www.googletagmanager.com",
    "https://www.google-analytics.com",
]

CONNECT_GOOGLE = [
    "https://www.google-analytics.com",
    "https://region1.google-analytics.com",
    "https://stats.g.doubleclick.net",
]

IMG_GOOGLE = [
    "https://www.google-analytics.com",
    "https://www.googletagmanager.com",
    "https://stats.g.doubleclick.net",
    "data:",
]

STYLE_CDNS = [
    "https://fonts.googleapis.com",
    "https://cdnjs.cloudflare.com",
]

FONT_CDNS = [
    "https://fonts.gstatic.com",
]

FRAME_GOOGLE = [
    "https://www.googletagmanager.com",
    "https://region1.google-analytics.com",
]


def _unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique_values: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


_SCRIPT_SOURCES = _unique(["'self'", *SCRIPT_GOOGLE])
_STYLE_SOURCES = _unique(["'self'", "'unsafe-inline'", *STYLE_CDNS])
_FONT_SOURCES = _unique(["'self'", *FONT_CDNS])


BASE_CSP: CSPDirective = {
    "default-src": "'self'",
    "script-src": list(_SCRIPT_SOURCES),
    "script-src-elem": list(_SCRIPT_SOURCES),
    "connect-src": [*CONNECT_GOOGLE, "'self'"],
    "img-src": [*IMG_GOOGLE, "'self'"],
    "style-src": list(_STYLE_SOURCES),
    "style-src-elem": list(_STYLE_SOURCES),
    "font-src": list(_FONT_SOURCES),
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-src": [*FRAME_GOOGLE, "'self'"],
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
        nonce_value = f"'nonce-{nonce}'"
        for directive_name in ("script-src", "script-src-elem"):
            directive = policy.get(directive_name)
            if isinstance(directive, list):
                if nonce_value not in directive:
                    directive.append(nonce_value)
            elif isinstance(directive, str):
                policy[directive_name] = f"{directive} {nonce_value}"

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
