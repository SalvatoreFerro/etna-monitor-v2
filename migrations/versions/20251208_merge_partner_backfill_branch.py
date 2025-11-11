"""Merge partner backfill branch into community moderation chain."""

from __future__ import annotations


revision = "20251208_merge_partner_backfill_branch"
down_revision = ("202503010002", "20251207_merge_post_sanitized_html_branch")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge revision ensuring a single head."""
    pass


def downgrade() -> None:
    """No-op merge revision."""
    pass
