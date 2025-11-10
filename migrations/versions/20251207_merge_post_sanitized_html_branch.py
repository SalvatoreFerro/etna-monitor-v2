"""Merge post sanitized HTML branch with community moderation chain."""

from __future__ import annotations


revision = "20251207_merge_post_sanitized_html_branch"
down_revision = (
    "202503010001",
    "20251206_account_community_moderation",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge revision."""
    pass


def downgrade() -> None:
    """No-op merge revision."""
    pass
