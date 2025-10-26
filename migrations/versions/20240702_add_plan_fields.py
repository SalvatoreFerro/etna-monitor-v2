"""Add plan and Telegram fields for freemium.

This migration is intentionally idempotent because the production database on
Render might already contain a subset of the columns created here.  Each
operation therefore checks for the presence of the target column or constraint
before applying structural changes.
"""

from alembic import op
import sqlalchemy as sa

revision = '20240702_add_plan_fields'
down_revision = None
branch_labels = None
depends_on = None

BOOLEAN_DEFAULT_FALSE = sa.sql.expression.false()


def _get_bind():
    bind = op.get_bind()
    if bind is None:
        raise RuntimeError('Database bind not available')
    return bind


def _get_inspector():
    return sa.inspect(_get_bind())


def _constraint_missing(name: str) -> bool:
    inspector = _get_inspector()
    constraints = {c['name'] for c in inspector.get_unique_constraints('users')}
    return name not in constraints


def upgrade() -> None:
    plan_enum = sa.Enum('free', 'premium', name='plan_type_enum')
    bind = _get_bind()
    plan_enum.create(bind, checkfirst=True)

    inspector = sa.inspect(bind)
    existing_columns = {col['name'] for col in inspector.get_columns('users')}

    if 'plan_type' not in existing_columns:
        op.add_column(
            'users',
            sa.Column(
                'plan_type',
                plan_enum,
                nullable=False,
                server_default='free',
            ),
        )
    else:
        op.execute("ALTER TABLE users ALTER COLUMN plan_type SET DEFAULT 'free'")
        op.execute("UPDATE users SET plan_type = 'free' WHERE plan_type IS NULL")
        op.alter_column(
            'users',
            'plan_type',
            existing_type=plan_enum,
            nullable=False,
        )

    if 'telegram_chat_id' not in existing_columns:
        op.add_column('users', sa.Column('telegram_chat_id', sa.String(length=64), nullable=True))

    if 'telegram_opt_in' not in existing_columns:
        op.add_column(
            'users',
            sa.Column(
                'telegram_opt_in',
                sa.Boolean(),
                nullable=False,
                server_default=BOOLEAN_DEFAULT_FALSE,
            ),
        )
    else:
        op.execute("UPDATE users SET telegram_opt_in = FALSE WHERE telegram_opt_in IS NULL")
        op.execute("ALTER TABLE users ALTER COLUMN telegram_opt_in SET DEFAULT FALSE")
        op.execute("ALTER TABLE users ALTER COLUMN telegram_opt_in SET NOT NULL")

    if 'free_alert_consumed' not in existing_columns:
        op.add_column(
            'users',
            sa.Column(
                'free_alert_consumed',
                sa.Boolean(),
                nullable=False,
                server_default=BOOLEAN_DEFAULT_FALSE,
            ),
        )
    else:
        op.execute("UPDATE users SET free_alert_consumed = FALSE WHERE free_alert_consumed IS NULL")
        op.execute("ALTER TABLE users ALTER COLUMN free_alert_consumed SET DEFAULT FALSE")
        op.execute("ALTER TABLE users ALTER COLUMN free_alert_consumed SET NOT NULL")

    if 'free_alert_event_id' not in existing_columns:
        op.add_column('users', sa.Column('free_alert_event_id', sa.String(length=255), nullable=True))

    if 'last_alert_sent_at' not in existing_columns:
        op.add_column('users', sa.Column('last_alert_sent_at', sa.DateTime(), nullable=True))

    if 'alert_count_30d' not in existing_columns:
        op.add_column(
            'users',
            sa.Column(
                'alert_count_30d',
                sa.Integer(),
                nullable=False,
                server_default='0',
            ),
        )
    else:
        op.execute("UPDATE users SET alert_count_30d = 0 WHERE alert_count_30d IS NULL")
        op.execute("ALTER TABLE users ALTER COLUMN alert_count_30d SET DEFAULT 0")
        op.execute("ALTER TABLE users ALTER COLUMN alert_count_30d SET NOT NULL")

    if 'consent_ts' not in existing_columns:
        op.add_column('users', sa.Column('consent_ts', sa.DateTime(), nullable=True))

    if 'privacy_version' not in existing_columns:
        op.add_column('users', sa.Column('privacy_version', sa.String(length=32), nullable=True))

    if _constraint_missing('uq_users_telegram_chat_id'):
        op.create_unique_constraint('uq_users_telegram_chat_id', 'users', ['telegram_chat_id'])

    op.execute(
        """
        UPDATE users
        SET plan_type = 'premium'
        WHERE plan_type = 'free'
          AND (
                COALESCE(is_premium, 0) = 1
             OR COALESCE(premium, 0) = 1
             OR COALESCE(premium_lifetime, 0) = 1
             OR LOWER(COALESCE(subscription_status, '')) IN ('active', 'trialing')
          )
        """
    )
    op.execute(
        """
        UPDATE users
        SET plan_type = 'free'
        WHERE plan_type IS NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET telegram_chat_id = chat_id
        WHERE telegram_chat_id IS NULL AND chat_id IS NOT NULL AND chat_id <> ''
        """
    )
    op.execute(
        """
        UPDATE users
        SET telegram_opt_in = TRUE
        WHERE chat_id IS NOT NULL AND chat_id <> ''
        """
    )


def downgrade() -> None:
    op.drop_constraint('uq_users_telegram_chat_id', 'users', type_='unique')
    op.drop_column('users', 'privacy_version')
    op.drop_column('users', 'consent_ts')
    op.drop_column('users', 'alert_count_30d')
    op.drop_column('users', 'last_alert_sent_at')
    op.drop_column('users', 'free_alert_event_id')
    op.drop_column('users', 'free_alert_consumed')
    op.drop_column('users', 'telegram_opt_in')
    op.drop_column('users', 'telegram_chat_id')
    op.drop_column('users', 'plan_type')

    bind = _get_bind()
    plan_enum = sa.Enum('free', 'premium', name='plan_type_enum')
    plan_enum.drop(bind, checkfirst=True)
