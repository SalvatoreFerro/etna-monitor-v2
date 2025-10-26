from datetime import datetime

from . import db

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=True, default="")
    premium = db.Column(db.Boolean, default=False, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    premium_lifetime = db.Column(db.Boolean, default=False, nullable=False)
    premium_since = db.Column(db.DateTime, nullable=True)
    donation_tx = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    chat_id = db.Column(db.String(50), nullable=True)
    plan_type = db.Column(
        db.Enum('free', 'premium', name='plan_type_enum'),
        nullable=False,
        server_default='free',
        default='free'
    )
    telegram_chat_id = db.Column(db.String(64), unique=True, nullable=True)
    telegram_opt_in = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text('false')
    )
    free_alert_consumed = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text('false')
    )
    free_alert_event_id = db.Column(db.String(255), nullable=True)
    last_alert_sent_at = db.Column(db.DateTime, nullable=True)
    alert_count_30d = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default=db.text('0')
    )
    consent_ts = db.Column(db.DateTime, nullable=True)
    privacy_version = db.Column(db.String(32), nullable=True)
    threshold = db.Column(db.Float, nullable=True)
    email_alerts = db.Column(db.Boolean, default=False, nullable=False)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    subscription_status = db.Column(db.String(20), default='free', nullable=False)
    subscription_id = db.Column(db.String(100), nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    trial_end = db.Column(db.DateTime, nullable=True)
    billing_email = db.Column(db.String(120), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)
    vat_id = db.Column(db.String(50), nullable=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    name = db.Column(db.String(255), nullable=True)
    picture_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f'<User {self.email}>'

    @property
    def has_premium_access(self) -> bool:
        """Return True when the user has any form of premium entitlement."""
        return bool(
            self.plan_type == 'premium'
            or self.is_premium
            or self.premium
            or self.premium_lifetime
            or (self.subscription_status or '').lower() in {'active', 'trialing'}
        )

    @property
    def current_plan(self) -> str:
        """Return the normalized plan label."""
        return 'premium' if self.has_premium_access else 'free'

    def mark_premium_plan(self) -> None:
        """Ensure the plan_type flag mirrors the premium status."""
        self.plan_type = 'premium'

    def activate_premium_lifetime(self) -> None:
        """Mark the user as lifetime premium while keeping legacy flags in sync."""
        self.is_premium = True
        self.premium = True
        self.premium_lifetime = True
        self.premium_since = datetime.utcnow()
        self.mark_premium_plan()
