"""Merge admin action logs branch with blog authors head."""

revision = "20251223_merge_admin_action_heads"
down_revision = ("20251222_add_admin_action_logs", "b761aa9e5a67")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
