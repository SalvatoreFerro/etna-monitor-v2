"""HTML sanitization utilities for community content."""

from __future__ import annotations

import re
from typing import List

import bleach

ALLOWED_TAGS: List[str] = [
    "p",
    "br",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "a",
    "img",
    "h3",
    "h4",
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

_EVENT_HANDLER_RE = re.compile(
    r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
    flags=re.IGNORECASE,
)
_UNSAFE_URI_RE = re.compile(
    r"(?i)(href|src)\s*=\s*(['\"])(?:javascript:|data:)[^'\"]*\2",
)
_SCRIPT_BLOCK_RE = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)

_SUSPICIOUS_PATTERNS = {
    "script tag": re.compile(r"<\s*script", re.IGNORECASE),
    "event handler": re.compile(r"on[a-z]+\s*=", re.IGNORECASE),
    "javascript uri": re.compile(r"javascript:\s*", re.IGNORECASE),
    "data uri": re.compile(r"data:\s*", re.IGNORECASE),
    "svg tag": re.compile(r"<\s*svg", re.IGNORECASE),
    "eval call": re.compile(r"eval\s*\(", re.IGNORECASE),
    "encoded <script": re.compile(r"%3c\s*script|%253c\s*script", re.IGNORECASE),
    "html entity script": re.compile(r"&#x3c;script|&#60;script", re.IGNORECASE),
    "inline srcdoc": re.compile(r"srcdoc=", re.IGNORECASE),
    "double-encoding": re.compile(r"%25", re.IGNORECASE),
}


def _strip_event_handlers(html: str) -> str:
    return _EVENT_HANDLER_RE.sub("", html)


def sanitize_html(html: str | None) -> str:
    """Return a sanitized HTML representation safe for rendering."""

    if not html:
        return ""

    without_scripts = _SCRIPT_BLOCK_RE.sub("", html)
    stripped = _strip_event_handlers(without_scripts)
    cleaned = bleach.clean(
        stripped,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    cleaned = _UNSAFE_URI_RE.sub("", cleaned)
    return cleaned


def find_suspicious_html(html: str | None) -> list[str]:
    """Detect suspicious HTML patterns that indicate a potential XSS payload."""

    if not html:
        return []

    matches: list[str] = []
    for label, pattern in _SUSPICIOUS_PATTERNS.items():
        if pattern.search(html):
            matches.append(label)
    return list(dict.fromkeys(matches))


def summarize_removed_elements(raw_html: str | None, sanitized_html: str | None) -> list[str]:
    """Return a simple diff summary to highlight removed snippets."""

    if not raw_html:
        return []
    if sanitized_html is None:
        sanitized_html = ""

    highlights: list[str] = []
    suspicious = find_suspicious_html(raw_html)
    highlights.extend(suspicious)

    if raw_html.strip() and raw_html != sanitized_html:
        highlights.append("sanitized-difference")

    return list(dict.fromkeys(highlights))


__all__ = [
    "ALLOWED_TAGS",
    "ALLOWED_ATTRS",
    "ALLOWED_PROTOCOLS",
    "sanitize_html",
    "find_suspicious_html",
    "summarize_removed_elements",
]
