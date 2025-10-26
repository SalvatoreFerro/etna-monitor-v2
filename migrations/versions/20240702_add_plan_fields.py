"""Add plan and Telegram fields for freemium"""

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


def upgrade() -> None:
    plan_enum = sa.Enum('free', 'premium', name='plan_type_enum')
    bind = _get_bind()
    plan_enum.create(bind, checkfirst=True)

    op.add_column('users', sa.Column('plan_type', plan_enum, nullable=False, server_default='free'))
    op.add_column('users', sa.Column('telegram_chat_id', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('telegram_opt_in', sa.Boolean(), nullable=False, server_default=BOOLEAN_DEFAULT_FALSE))
    op.add_column('users', sa.Column('free_alert_consumed', sa.Boolean(), nullable=False, server_default=BOOLEAN_DEFAULT_FALSE))
    op.add_column('users', sa.Column('free_alert_event_id', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('last_alert_sent_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('alert_count_30d', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('consent_ts', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('privacy_version', sa.String(length=32), nullable=True))

    op.create_unique_constraint('uq_users_telegram_chat_id', 'users', ['telegram_chat_id'])

    op.execute(
        """
        UPDATE users
        SET plan_type = 'premium'
        WHERE COALESCE(is_premium, 0) = 1
           OR COALESCE(premium, 0) = 1
           OR COALESCE(premium_lifetime, 0) = 1
           OR LOWER(COALESCE(subscription_status, '')) IN ('active', 'trialing')
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
        SET telegram_opt_in = 1
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
