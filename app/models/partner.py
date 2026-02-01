"""Partner directory models."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from slugify import slugify
from sqlalchemy import event, func

from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import db


def _json_type():
    """Return a JSON column type compatible with SQLite and PostgreSQL."""

    try:
        from sqlalchemy.dialects.postgresql import JSONB  # type: ignore

        return db.JSON().with_variant(JSONB, "postgresql")
    except ModuleNotFoundError:  # pragma: no cover - fallback for limited envs
        return db.JSON()


PARTNER_STATUSES = ("draft", "pending", "approved", "rejected", "expired", "disabled")
SUBSCRIPTION_STATUSES = ("paid", "expired")
PAYMENT_METHODS = ("paypal_manual", "cash")
WAITLIST_STATUSES = ("new", "contacted", "converted")


class PartnerCategory(db.Model):
    """Category grouping partners with a limited amount of slots."""

    __tablename__ = "partner_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(db.Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=True, server_default=db.text("true")
    )
    max_slots: Mapped[int] = mapped_column(
        db.Integer, nullable=False, default=10, server_default=db.text("10")
    )
    sort_order: Mapped[int] = mapped_column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    partners: Mapped[list["Partner"]] = relationship("Partner", back_populates="category")

    def available_slots(self, reference: Optional[date] = None) -> int:
        reference = reference or date.today()
        approved_partners = [
            partner
            for partner in self.partners
            if partner.is_publicly_visible(reference)
        ]
        return max(self.max_slots - len(approved_partners), 0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartnerCategory {self.slug} slots={self.max_slots}>"


class Partner(db.Model):
    """Partner entry visible inside the partner directory."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        db.ForeignKey("partner_categories.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(db.String(180), nullable=False)
    short_desc: Mapped[str | None] = mapped_column(db.String(280), nullable=True)
    long_desc: Mapped[str | None] = mapped_column(db.Text(), nullable=True)
    website_url: Mapped[str | None] = mapped_column(db.String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    instagram: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    facebook: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    tiktok: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    geo_lat: Mapped[float | None] = mapped_column(db.Numeric(9, 6), nullable=True)
    geo_lng: Mapped[float | None] = mapped_column(db.Numeric(9, 6), nullable=True)
    logo_path: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    hero_image_path: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    extra_data: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(_json_type()),
        nullable=False,
        default=dict,
    )
    images_json: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(_json_type()), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(
        db.Enum(*PARTNER_STATUSES, name="partner_status"),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    featured: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )

    category: Mapped[PartnerCategory] = relationship(
        PartnerCategory, back_populates="partners"
    )
    subscriptions: Mapped[list["PartnerSubscription"]] = relationship(
        "PartnerSubscription",
        back_populates="partner",
        order_by="PartnerSubscription.year.desc()",
        cascade="all, delete-orphan",
    )
    leads: Mapped[list["PartnerLead"]] = relationship(
        "PartnerLead",
        back_populates="partner",
        cascade="all, delete-orphan",
    )

    def ensure_slug(self) -> None:
        if self.slug:
            return
        base = slugify(self.name or "partner")[:110]
        if not base:
            base = "partner"
        candidate = base
        counter = 1
        while Partner.query.filter_by(slug=candidate).first() is not None:
            counter += 1
            candidate = f"{base}-{counter}"
        self.slug = candidate

    def has_valid_subscription(self, reference: Optional[date] = None) -> bool:
        return self.active_subscription(reference) is not None

    def active_subscription(
        self, reference: Optional[date] = None
    ) -> "PartnerSubscription | None":
        reference = reference or date.today()
        for subscription in self.subscriptions:
            if subscription.status != "paid" or not subscription.valid_to:
                continue
            if subscription.valid_from and subscription.valid_from > reference:
                continue
            if subscription.valid_to >= reference:
                return subscription
        return None

    def is_publicly_visible(self, reference: Optional[date] = None) -> bool:
        if self.status != "approved":
            return False
        return self.has_valid_subscription(reference)

    def mark_approved(self) -> None:
        self.status = "approved"
        self.approved_at = datetime.now(timezone.utc)

    def mark_expired(self) -> None:
        self.status = "expired"

    def compute_price(self, *, first_year_price: int, renewal_price: int) -> int:
        if any(sub.status == "paid" for sub in self.subscriptions):
            return renewal_price
        return first_year_price

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Partner {self.slug} status={self.status}>"


class PartnerSubscription(db.Model):
    """Subscription purchased by a partner."""

    __tablename__ = "partner_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(
        db.ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(db.Integer, nullable=False)
    price_eur: Mapped[float] = mapped_column(db.Numeric(8, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        db.Enum(*SUBSCRIPTION_STATUSES, name="partner_subscription_status"),
        nullable=False,
        default="paid",
        server_default="paid",
    )
    payment_method: Mapped[str] = mapped_column(
        db.Enum(*PAYMENT_METHODS, name="partner_payment_method"), nullable=False
    )
    payment_ref: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    valid_from: Mapped[date | None] = mapped_column(db.Date())
    valid_to: Mapped[date | None] = mapped_column(db.Date())
    invoice_number: Mapped[str] = mapped_column(
        db.String(64), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    partner: Mapped[Partner] = relationship("Partner", back_populates="subscriptions")

    def mark_expired(self) -> None:
        self.status = "expired"

    def set_validity(self, paid_at: datetime) -> None:
        self.paid_at = paid_at
        start = paid_at.date()
        self.valid_from = start
        self.valid_to = start + timedelta(days=365)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartnerSubscription {self.invoice_number} status={self.status}>"


class PartnerWaitlist(db.Model):
    """Potential partner waiting for a slot in a category."""

    __tablename__ = "partner_waitlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        db.ForeignKey("partner_categories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(db.String(180), nullable=False)
    email: Mapped[str] = mapped_column(db.String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(db.Text(), nullable=True)
    status: Mapped[str] = mapped_column(
        db.Enum(*WAITLIST_STATUSES, name="partner_waitlist_status"),
        nullable=False,
        default="new",
        server_default="new",
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    category: Mapped[PartnerCategory] = relationship(PartnerCategory)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartnerWaitlist {self.email} category={self.category_id}>"


class PartnerLead(db.Model):
    """Lead generated from the public contact form."""

    __tablename__ = "partner_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(
        db.ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(db.String(180), nullable=False)
    email: Mapped[str] = mapped_column(db.String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(db.Text(), nullable=True)
    source: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(_json_type()), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    partner: Mapped[Partner] = relationship(Partner, back_populates="leads")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartnerLead {self.partner_id} {self.email}>"


def generate_invoice_number(sequence: int, *, year: int | None = None) -> str:
    current_year = year or datetime.now(timezone.utc).year
    return f"EM-PARTNER-{current_year}-{sequence:04d}"


@event.listens_for(Partner, "before_insert")
def _partner_before_insert(mapper, connection, target) -> None:  # pragma: no cover - SQLAlchemy hook
    target.ensure_slug()
