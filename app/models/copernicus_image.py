"""Copernicus Sentinel-2 image metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from . import db


def _json_type() -> db.JSON:
    return db.JSON().with_variant(JSONB, "postgresql")


class CopernicusImage(db.Model):
    """Persisted Copernicus Sentinel-2 imagery metadata."""

    __tablename__ = "copernicus_images"
    __table_args__ = (
        db.Index("ix_copernicus_images_acquired_at", "acquired_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    acquired_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(db.String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(db.String(128), nullable=False)
    cloud_cover: Mapped[float | None] = mapped_column(db.Float)
    bbox: Mapped[dict | list | None] = mapped_column(_json_type())
    image_path: Mapped[str | None] = mapped_column(db.String(256))
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CopernicusImage product_id={self.product_id} acquired_at={self.acquired_at}>"
