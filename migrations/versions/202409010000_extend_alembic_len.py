"""Expand ``alembic_version.version_num`` to safely store long revision IDs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202409010000_extend_alembic_len"
down_revision = "202408010002_sync_partners"
branch_labels = None
depends_on = None


def _needs_resize(bind) -> tuple[bool, int | None]:
    inspector = sa.inspect(bind)
    try:
        columns = inspector.get_columns("alembic_version")
    except sa.exc.NoSuchTableError:  # pragma: no cover - defensive guard
        return False, None

    for column in columns:
        if column["name"] == "version_num":
            current_length = getattr(column["type"], "length", None)
            if current_length is None or current_length < 128:
                return True, current_length
            return False, current_length

    return False, None


def upgrade() -> None:
    bind = op.get_bind()
    should_resize, current_length = _needs_resize(bind)
    if not should_resize:
        return

    new_type = sa.String(length=128)
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("alembic_version", recreate="auto") as batch_op:
            batch_op.alter_column("version_num", type_=new_type)
    else:
        existing_type = sa.String(length=current_length or 32)
        op.alter_column(
            "alembic_version",
            "version_num",
            type_=new_type,
            existing_type=existing_type,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        columns = inspector.get_columns("alembic_version")
    except sa.exc.NoSuchTableError:  # pragma: no cover - defensive guard
        return

    for column in columns:
        if column["name"] == "version_num":
            current_length = getattr(column["type"], "length", None)
            if current_length is not None and current_length <= 32:
                return
            break
    else:
        return

    revert_type = sa.String(length=32)
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("alembic_version", recreate="auto") as batch_op:
            batch_op.alter_column("version_num", type_=revert_type)
    else:
        op.alter_column(
            "alembic_version",
            "version_num",
            type_=revert_type,
            existing_type=sa.String(length=current_length or 128),
        )
