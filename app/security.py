"""Security helpers for HTTP response headers."""

from __future__ import annotations

import copy
from typing import Dict, List, Union

from flask_talisman import Talisman

CSPDirective = Dict[str, Union[List[str], str]]

BASE_CSP: CSPDirective = {
    "default-src": "'self'",
    "script-src": [
        "'self'",
        "'nonce-%(nonce)s'",
        "https://js.stripe.com",
        "https://plausible.io",
        "https://www.googletagmanager.com",
        "https://www.google-analytics.com",
    ],
    "style-src": [
        "'self'",
        "'unsafe-inline'",
        "https://fonts.googleapis.com",
        "https://cdnjs.cloudflare.com",
    ],
    "font-src": ["'self'", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"],
    "img-src": [
        "'self'",
        "data:",
        "https:",
        "https://www.google-analytics.com",
        "https://region1.google-analytics.com",
        "https://www.googletagmanager.com",
        "https://stats.g.doubleclick.net",
    ],
    "connect-src": [
        "'self'",
        "https://api.stripe.com",
        "https://plausible.io",
        "https://www.google-analytics.com",
        "https://region1.google-analytics.com",
        "https://www.googletagmanager.com",
        "https://stats.g.doubleclick.net",
    ],
    "frame-src": [
        "'self'",
        "https://js.stripe.com",
        "https://hooks.stripe.com",
        "https://www.googletagmanager.com",
    ],
    "child-src": [
        "'self'",
        "https://js.stripe.com",
        "https://hooks.stripe.com",
        "https://www.googletagmanager.com",
    ],
    "frame-ancestors": [
        "'self'",
        "https://etnamonitor.it",
        "https://*.etnamonitor.it",
        "https://*.onrender.com",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ],
}


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
