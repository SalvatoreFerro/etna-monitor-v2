"""Add author and sources fields to blog posts."""

from alembic import op
import sqlalchemy as sa

revision = "202503150001_add_blog_authors_and_sources"
down_revision = "20251220_update_cron_runs_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_posts",
        sa.Column(
            "author_name",
            sa.String(length=120),
            nullable=True,
            server_default="Salvatore Ferro",
        ),
    )
    op.add_column(
        "blog_posts",
        sa.Column(
            "author_slug",
            sa.String(length=140),
            nullable=True,
            server_default="salvatore-ferro",
        ),
    )
    op.add_column("blog_posts", sa.Column("sources", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("blog_posts", "sources")
    op.drop_column("blog_posts", "author_slug")
    op.drop_column("blog_posts", "author_name")
