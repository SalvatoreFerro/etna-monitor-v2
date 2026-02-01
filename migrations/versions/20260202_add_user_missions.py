"""Add user missions table for gamification."""

from alembic import op
import sqlalchemy as sa

revision = "20260202_add_user_missions"
down_revision = "20260205_add_tremor_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_missions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mission_code", sa.String(length=64), nullable=False),
        sa.Column(
            "awarded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_user_missions_user_id",
        "user_missions",
        ["user_id"],
    )
    op.create_index(
        "ix_user_missions_mission_code",
        "user_missions",
        ["mission_code"],
    )
    op.create_index(
        "ix_user_missions_expires_at",
        "user_missions",
        ["expires_at"],
    )
    op.create_index(
        "ix_user_missions_completed_at",
        "user_missions",
        ["completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_missions_completed_at", table_name="user_missions")
    op.drop_index("ix_user_missions_expires_at", table_name="user_missions")
    op.drop_index("ix_user_missions_mission_code", table_name="user_missions")
    op.drop_index("ix_user_missions_user_id", table_name="user_missions")
    op.drop_table("user_missions")
