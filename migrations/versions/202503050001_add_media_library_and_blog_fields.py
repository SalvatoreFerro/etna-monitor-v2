"""Add media library table and extend blog fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202503050001_add_media_library_and_blog_fields"
down_revision = "20251210_add_partner_short_desc"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    """Return True when the requested table exists."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    """Return True when the requested column exists."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _table_exists("media_assets"):
        op.create_table(
            "media_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("url", sa.String(length=1024), nullable=False),
            sa.Column("public_id", sa.String(length=255), nullable=False, unique=True),
            sa.Column("original_filename", sa.String(length=255), nullable=True),
            sa.Column("bytes", sa.Integer(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )

    if not _column_exists("blog_posts", "hero_image_url"):
        op.add_column("blog_posts", sa.Column("hero_image_url", sa.String(length=512), nullable=True))
    if not _column_exists("blog_posts", "meta_title"):
        op.add_column("blog_posts", sa.Column("meta_title", sa.String(length=190), nullable=True))
    if not _column_exists("blog_posts", "meta_description"):
        op.add_column(
            "blog_posts",
            sa.Column("meta_description", sa.String(length=300), nullable=True),
        )
    if not _column_exists("blog_posts", "published_at"):
        op.add_column("blog_posts", sa.Column("published_at", sa.DateTime(), nullable=True))

    if _column_exists("blog_posts", "hero_image_url") and _column_exists("blog_posts", "hero_image"):
        op.execute(
            sa.text(
                """
                UPDATE blog_posts
                SET hero_image_url = hero_image
                WHERE hero_image_url IS NULL
                  AND hero_image IS NOT NULL
                """
            )
        )

    if _column_exists("blog_posts", "meta_title") and _column_exists("blog_posts", "seo_title"):
        op.execute(
            sa.text(
                """
                UPDATE blog_posts
                SET meta_title = seo_title
                WHERE meta_title IS NULL
                  AND seo_title IS NOT NULL
                """
            )
        )

    if _column_exists("blog_posts", "meta_description") and _column_exists("blog_posts", "seo_description"):
        op.execute(
            sa.text(
                """
                UPDATE blog_posts
                SET meta_description = seo_description
                WHERE meta_description IS NULL
                  AND seo_description IS NOT NULL
                """
            )
        )


def downgrade() -> None:  # pragma: no cover - destructive downgrade intentionally omitted
    """Downgrade intentionally left empty to avoid accidental data loss."""
    pass
