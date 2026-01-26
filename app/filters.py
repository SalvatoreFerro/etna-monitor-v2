"""Custom Jinja filters used across the EtnaMonitor application."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import bleach
import markdown2
from markupsafe import Markup
from zoneinfo import ZoneInfo

_BR_TAG_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_IMG_LOADING_PATTERN = re.compile(r"<img(?![^>]*\bloading=)([^>]*)>", re.IGNORECASE)

_DEFAULT_ALLOWED_TAGS: set[str] = set(bleach.sanitizer.ALLOWED_TAGS)
_EXTRA_TAGS: Iterable[str] = (
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "img",
    "figure",
    "figcaption",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "blockquote",
)

ALLOWED_TAGS = sorted(_DEFAULT_ALLOWED_TAGS.union(_EXTRA_TAGS))
ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "img": ["src", "alt", "title", "loading", "width", "height"],
}

for heading in ("h1", "h2", "h3", "h4", "h5", "h6"):
    existing = set(ALLOWED_ATTRS.get(heading, []))
    existing.add("id")
    ALLOWED_ATTRS[heading] = sorted(existing)


def strip_literal_breaks(text: str | None) -> str:
    """Remove literal ``<br>`` tags leftover from legacy content."""

    if not text:
        return ""
    return _BR_TAG_PATTERN.sub("", text)


def _ensure_lazy_images(html: str) -> str:
    """Guarantee that <img> tags include a ``loading="lazy"`` attribute."""

    def _inject_loading(match: re.Match[str]) -> str:
        attributes = match.group(1)
        return f'<img loading="lazy"{attributes}>'

    return _IMG_LOADING_PATTERN.sub(_inject_loading, html)


def render_markdown(text: str | None) -> str:
    """Render Markdown text into sanitized HTML safe for templates."""

    cleaned_input = strip_literal_breaks(text)
    html = markdown2.markdown(
        cleaned_input,
        extras=[
            "fenced-code-blocks",
            "tables",
            "strike",
            "header-ids",
            "footnotes",
        ],
    )
    safe_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    safe_html = _ensure_lazy_images(safe_html)
    return safe_html


def md(text: str | None) -> Markup:
    """Jinja filter that wraps :func:`render_markdown` and marks it safe."""

    return Markup(render_markdown(text))


def _to_rome(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/Rome"))


def format_datetime_rome(value: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Format a datetime value in Europe/Rome timezone for admin templates."""

    localized = _to_rome(value)
    if localized is None:
        return "—"
    return localized.strftime(fmt)


def format_datetime_input_rome(value: datetime | None) -> str:
    """Format a datetime value for datetime-local inputs in Europe/Rome."""

    return format_datetime_rome(value, fmt="%Y-%m-%dT%H:%M") if value else ""


__all__ = [
    "md",
    "render_markdown",
    "strip_literal_breaks",
    "format_datetime_rome",
    "format_datetime_input_rome",
]
