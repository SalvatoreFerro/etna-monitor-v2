"""Merge partner validation branch with community moderation chain."""

from __future__ import annotations


revision = "20251209_merge_partner_validation_branch"
down_revision = ("202503010003", "20251208_merge_partner_backfill_branch")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge revision to unify heads."""
    pass


def downgrade() -> None:
    """No-op merge revision."""
    pass
