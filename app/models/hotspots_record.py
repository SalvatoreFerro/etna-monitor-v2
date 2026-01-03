"""Hotspots record model for FIRMS entries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from . import db


class HotspotsRecord(db.Model):
    """Persisted FIRMS hotspots record."""

    __tablename__ = "hotspots_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(db.String(32), nullable=False)
    satellite: Mapped[str] = mapped_column(db.String(16), nullable=False)
    lat: Mapped[float] = mapped_column(db.Float, nullable=False)
    lon: Mapped[float] = mapped_column(db.Float, nullable=False)
    acq_datetime: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    confidence: Mapped[str | None] = mapped_column(db.String(16))
    brightness: Mapped[float | None] = mapped_column(db.Float)
    frp: Mapped[float | None] = mapped_column(db.Float)
    intensity_unit: Mapped[str | None] = mapped_column(db.String(8))
    status: Mapped[str | None] = mapped_column(db.String(16))
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HotspotsRecord fingerprint={self.fingerprint} acq_datetime={self.acq_datetime}>"

