"""Partner model for Etna Experience directory."""

from __future__ import annotations

from datetime import datetime

from . import db


PARTNER_CATEGORIES: tuple[str, ...] = (
    "Guide",
    "Hotel",
    "Ristorante",
    "Tour",
    "Altro",
)


class Partner(db.Model):
    """Partner showcased inside the Etna Experience section."""

    __tablename__ = "partners"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.Text, nullable=False)
    category: str | None = db.Column(db.Text, nullable=True)
    description: str | None = db.Column(db.Text)
    website: str | None = db.Column(db.Text)
    contact: str | None = db.Column(db.Text)
    image_url: str | None = db.Column(db.Text)
    lat: float | None = db.Column(db.Float)
    lon: float | None = db.Column(db.Float)
    verified: bool = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    visible: bool = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        nullable=False,
    )

    def category_label(self) -> str:
        """Return the category label used on the public site."""

        # The database stores the singular "Ristorante" while the UI uses the
        # plural "Ristoranti" in filters. Keep the raw value for other
        # categories.
        if self.category == "Ristorante":
            return "Ristoranti"
        return self.category or "Altro"

