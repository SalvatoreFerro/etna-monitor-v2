"""Hotspots cache model for FIRMS payloads."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from . import db


def _json_type():
    """Return a JSON column type compatible with SQLite and PostgreSQL."""

    try:
        from sqlalchemy.dialects.postgresql import JSONB  # type: ignore

        return db.JSON().with_variant(JSONB, "postgresql")
    except ModuleNotFoundError:  # pragma: no cover - fallback for limited envs
        return db.JSON()


class HotspotsCache(db.Model):
    """Persisted hotspots cache entry."""

    __tablename__ = "hotspots_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(_json_type(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HotspotsCache key={self.key} count={self.count}>"

