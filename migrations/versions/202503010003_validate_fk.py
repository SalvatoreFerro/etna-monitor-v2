"""Validate partners.category_id foreign key."""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "202503010003"
down_revision = "202503010002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if os.getenv("ALEMBIC_SKIP_BACKFILL"):
        return

    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '5min'")
        op.execute(text("ALTER TABLE partners VALIDATE CONSTRAINT fk_partners_category"))


def downgrade() -> None:
    # Downgrading does not un-validate the constraint; no action required.
    pass
