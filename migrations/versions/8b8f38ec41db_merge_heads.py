"""merge heads"""

revision = "8b8f38ec41db"
down_revision = ('1646bbb5fba0', '20251220_update_cron_runs_monitoring')
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
