"""add_theme_preference_to_users

Revision ID: 20251028_add_theme_preference
Revises: 20251101_fix_telegram_chat_ids
Create Date: 2025-10-28 09:15:50.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20251028_add_theme_preference'
down_revision = '20251101_fix_telegram_chat_ids'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('theme_preference', sa.String(50), nullable=False, server_default='volcano_tech'))


def downgrade() -> None:
    op.drop_column('users', 'theme_preference')
