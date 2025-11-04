"""Merge user schema heads after theme preference alignment."""

from __future__ import annotations


revision = "20251202_merge_user_theme_heads"
down_revision = ("20251201_align_user_schema", "20251028_theme_pref")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge revision to unify parallel heads."""
    # The 20251028_theme_pref revision introduced the ``theme_preference``
    # column with a default, while 20251201_align_user_schema refines the column
    # definition alongside other user fields. At this point both branches have
    # executed, so no additional DDL is required to reconcile them.
    pass


def downgrade() -> None:
    """No-op downgrade for the merge revision."""
    pass
