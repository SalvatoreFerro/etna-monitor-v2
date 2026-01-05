"""merge blog authors head"""

revision = "b761aa9e5a67"
down_revision = ('202503150001_add_blog_authors_and_sources', '8b8f38ec41db')
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
