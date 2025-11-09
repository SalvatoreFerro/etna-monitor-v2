"""Add sanitized HTML column for community posts."""

from __future__ import annotations

import re

import bleach
from alembic import op
import sqlalchemy as sa

revision = "202502140001_add_post_sanitized_html"
down_revision = "20251026_add_missing_user_alert_columns"
branch_labels = None
depends_on = None


EVENT_HANDLER_RE = re.compile(
    r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
    flags=re.IGNORECASE,
)
UNSAFE_URI_RE = re.compile(
    r"(?i)(href|src)\s*=\s*(['\"])(?:javascript:|data:)[^'\"]*\2",
)

ALLOWED_TAGS = [
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


def _sanitize_html(html: str | None) -> str:
    if not html:
        return ""
    stripped = EVENT_HANDLER_RE.sub("", html)
    cleaned = bleach.clean(
        stripped,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    cleaned = UNSAFE_URI_RE.sub("", cleaned)
    return cleaned


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "body_html_sanitized",
            sa.Text(),
            nullable=True,
            server_default="",
        ),
    )

    conn = op.get_bind()
    posts_table = sa.table(
        "posts",
        sa.column("id", sa.Integer()),
        sa.column("body", sa.Text()),
    )

    for post_id, body in conn.execute(sa.select(posts_table.c.id, posts_table.c.body)):
        sanitized = _sanitize_html(body)
        conn.execute(
            sa.text(
                "UPDATE posts SET body_html_sanitized = :sanitized WHERE id = :post_id"
            ),
            {"sanitized": sanitized, "post_id": post_id},
        )

    op.alter_column(
        "posts",
        "body_html_sanitized",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
    )

    op.drop_constraint(
        "ck_moderation_actions_action",
        "moderation_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_moderation_actions_action",
        "moderation_actions",
        "action IN ('approve','reject','hide','restore','auto_hide_xss')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_moderation_actions_action",
        "moderation_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_moderation_actions_action",
        "moderation_actions",
        "action IN ('approve','reject','hide','restore')",
    )

    op.drop_column("posts", "body_html_sanitized")
