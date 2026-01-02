"""Security helpers for HTTP response headers."""
from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Union

from flask import request
from flask_talisman import Talisman

CSPDirective = Dict[str, Union[List[str], str]]

GOOGLE_REQUIRED_DOMAINS = [
    "https://www.googletagmanager.com",
    "https://www.google-analytics.com",
    "https://www.doubleclick.net",
    "https://*.doubleclick.net",
    "https://www.google.com",
    "https://*.google.com",
    "https://www.gstatic.com",
    "https://*.gstatic.com",
    "https://pagead2.googlesyndication.com",
    "https://googleads.g.doubleclick.net",
]

GOOGLE_SCRIPT_SOURCES = [
    *GOOGLE_REQUIRED_DOMAINS,
    "https://*.googletagmanager.com",
    "https://*.google-analytics.com",
    "https://region1.google-analytics.com",
    "https://stats.g.doubleclick.net",
    "https://cdn.plot.ly",
]

CONNECT_ENDPOINTS = [
    *GOOGLE_SCRIPT_SOURCES,
    "https://www.google.it",
    "https://*.google.it",
]

IMG_TRACKING_ENDPOINTS = [
    *GOOGLE_REQUIRED_DOMAINS,
    "https://*.googletagmanager.com",
    "https://*.google-analytics.com",
    "https://region1.google-analytics.com",
    "https://stats.g.doubleclick.net",
    "https://www.google.it",
    "https://*.google.it",
    "https://tpc.googlesyndication.com",
]

STYLE_CDNS = [
    "https://fonts.googleapis.com",
    "https://cdnjs.cloudflare.com",
    "https://unpkg.com",
]

FONT_CDNS = [
    "https://fonts.gstatic.com",
    "https://cdnjs.cloudflare.com",
]

FRAME_GOOGLE = [
    *GOOGLE_REQUIRED_DOMAINS,
    "https://*.googletagmanager.com",
    "https://*.google-analytics.com",
    "https://region1.google-analytics.com",
    "https://www.google.it",
    "https://*.google.it",
    "https://tpc.googlesyndication.com",
    "https://cdn.plot.ly",
]


def _unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique_values: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


_SCRIPT_SOURCES = _unique(["'self'", *GOOGLE_SCRIPT_SOURCES, "https://unpkg.com"])
_STYLE_SOURCES = _unique(["'self'", "'unsafe-inline'", *STYLE_CDNS])
_FONT_SOURCES = _unique(["'self'", *FONT_CDNS])
_CONNECT_SOURCES = _unique(["'self'", *CONNECT_ENDPOINTS])
_IMG_SOURCES = _unique(["'self'", "data:", "https:", *IMG_TRACKING_ENDPOINTS])
_FRAME_SOURCES = _unique(["'self'", *FRAME_GOOGLE])


BASE_CSP: CSPDirective = {
    "default-src": "'self'",
    "script-src": list(_SCRIPT_SOURCES),
    "script-src-elem": list(_SCRIPT_SOURCES),
    "connect-src": list(_CONNECT_SOURCES),
    "img-src": list(_IMG_SOURCES),
    "style-src": list(_STYLE_SOURCES),
    "style-src-elem": list(_STYLE_SOURCES),
    "font-src": list(_FONT_SOURCES),
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-src": list(_FRAME_SOURCES),
}


def apply_csp_headers(response) -> object:
    if getattr(response, "_csp_header_applied", False):
        return response

    policy = copy.deepcopy(BASE_CSP)
    nonce = getattr(request, "csp_nonce", None)
    if nonce:
        nonce_fragment = f"'nonce-{nonce}'"
        for directive in ("script-src", "script-src-elem"):
            sources = policy.get(directive)
            if isinstance(sources, list) and nonce_fragment not in sources:
                sources.append(nonce_fragment)

    response.headers.set("Content-Security-Policy", serialize_csp(policy))
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
    setattr(response, "_csp_header_applied", True)
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
