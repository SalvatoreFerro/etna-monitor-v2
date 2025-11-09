from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask_login import UserMixin
from sqlalchemy import func, or_
from sqlalchemy.orm import validates

from . import db

ROLE_CHOICES = ("free", "premium", "moderator", "admin")


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        db.CheckConstraint(
            "telegram_chat_id IS NULL OR telegram_chat_id > 0",
            name="ck_users_telegram_chat_id_positive",
        ),
        db.CheckConstraint(
            "chat_id IS NULL OR chat_id > 0",
            name="ck_users_chat_id_positive",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=True, default="")
    premium = db.Column(db.Boolean, default=False, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    premium_lifetime = db.Column(db.Boolean, default=False, nullable=False)
    premium_since = db.Column(db.DateTime, nullable=True)
    donation_tx = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=db.text("false"),
    )
    chat_id = db.Column(db.BigInteger, nullable=True)
    plan_type = db.Column(
        db.String(20),
        nullable=False,
        server_default="free",
        default="free",
    )
    role = db.Column(
        db.String(20),
        nullable=False,
        default="free",
        server_default="free",
    )
    telegram_chat_id = db.Column(db.BigInteger, unique=True, nullable=True)
    telegram_opt_in = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    free_alert_consumed = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    free_alert_event_id = db.Column(db.String(255), nullable=True)
    last_alert_sent_at = db.Column(db.DateTime, nullable=True)
    alert_count_30d = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    consent_ts = db.Column(db.DateTime, nullable=True)
    privacy_version = db.Column(db.String(32), nullable=True)
    threshold = db.Column(db.Float, nullable=True)
    email_alerts = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=db.text("false"),
    )
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    subscription_status = db.Column(
        db.String(20),
        default="free",
        nullable=False,
        server_default="free",
    )
    subscription_id = db.Column(db.String(100), nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    trial_end = db.Column(db.DateTime, nullable=True)
    billing_email = db.Column(db.String(120), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)
    vat_id = db.Column(db.String(50), nullable=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    name = db.Column(db.String(255), nullable=True)
    picture_url = db.Column(db.String(512), nullable=True)
    theme_preference = db.Column(
        db.String(16),
        nullable=True,
        default="system",
        server_default="system",
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    erased_at = db.Column(db.DateTime(timezone=True), nullable=True)
    _is_active = db.Column(
        "is_active",
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    posts = db.relationship(
        "CommunityPost",
        back_populates="author",
        lazy="dynamic",
        foreign_keys="CommunityPost.author_id",
    )
    moderated_posts = db.relationship(
        "CommunityPost",
        back_populates="moderator",
        lazy="dynamic",
        foreign_keys="CommunityPost.moderated_by",
    )

    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return bool(self._is_active)

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self._is_active = bool(value)

    @property
    def has_premium_access(self) -> bool:
        """Return True when the user has any form of premium entitlement."""
        return bool(
            self.plan_type == "premium"
            or self.is_premium
            or self.premium
            or self.premium_lifetime
            or (self.subscription_status or "").lower() in {"active", "trialing"}
        )

    @property
    def current_plan(self) -> str:
        """Return the normalized plan label."""
        return "premium" if self.has_premium_access else "free"

    def mark_premium_plan(self) -> None:
        """Ensure the plan_type flag mirrors the premium status."""
        self.plan_type = "premium"

    def activate_premium_lifetime(self) -> None:
        """Mark the user as lifetime premium while keeping legacy flags in sync."""
        self.is_premium = True
        self.premium = True
        self.premium_lifetime = True
        self.premium_since = datetime.utcnow()
        self.mark_premium_plan()

    @classmethod
    def premium_status_clause(cls):
        """Return a SQL expression selecting users with premium entitlements."""
        normalized_status = func.lower(func.coalesce(cls.subscription_status, ""))
        return or_(
            cls.plan_type == "premium",
            cls.is_premium.is_(True),
            cls.premium.is_(True),
            cls.premium_lifetime.is_(True),
            normalized_status.in_(["active", "trialing"]),
        )

    @validates("email")
    def _normalize_email(self, key: str, value: str | None) -> str:
        if value is None:
            raise ValueError("Email cannot be null")
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Email cannot be empty")
        return normalized

    # --- Role helpers -------------------------------------------------
    def is_moderator(self) -> bool:
        return bool(self.is_admin or self.role == "moderator")

    def has_role(self, *roles: str) -> bool:
        if self.is_admin:
            return True
        normalized = {role for role in roles if role}
        if not normalized:
            return False
        return self.role in normalized

    # --- Account lifecycle helpers ------------------------------------
    def soft_delete(self) -> None:
        now = datetime.now(timezone.utc)
        self.deleted_at = now
        self.is_active = False

    def anonymize(self) -> None:
        token = uuid4().hex
        anonymized_email = f"deleted-user-{self.id}-{token}@example.invalid"
        self.email = anonymized_email
        self.name = None
        self.picture_url = None
        self.billing_email = None
        self.chat_id = None
        self.telegram_chat_id = None
        self.telegram_opt_in = False
        self.threshold = None
        self.password_hash = ""
        self.free_alert_event_id = None
        self.alert_count_30d = 0
        self.last_alert_sent_at = None
        self.plan_type = "free"
        self.subscription_status = "canceled"
        self.role = "free"
        self.is_premium = False
        self.premium = False
        self.premium_lifetime = False

    def purge_deadline(self, ttl_days: int) -> datetime:
        reference = self.deleted_at or datetime.now(timezone.utc)
        return reference + timedelta(days=ttl_days)
