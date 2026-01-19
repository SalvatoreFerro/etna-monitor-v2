from datetime import datetime

from . import db


class ApiClient(db.Model):
    __tablename__ = "api_clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False, unique=True)
    contact_email = db.Column(db.String(255), nullable=True)
    plan = db.Column(db.String(20), nullable=False, default="FREE")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    keys = db.relationship(
        "ApiKey",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("api_clients.id"), nullable=False)
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    prefix = db.Column(db.String(8), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=True)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    client = db.relationship("ApiClient", back_populates="keys")
    usage_entries = db.relationship(
        "ApiUsage",
        back_populates="key",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ApiUsage(db.Model):
    __tablename__ = "api_usage"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"), nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(12), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    ts = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    latency_ms = db.Column(db.Integer, nullable=False)

    key = db.relationship("ApiKey", back_populates="usage_entries")


class ApiUsageDaily(db.Model):
    __tablename__ = "api_usage_daily"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    requests_count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint("key_id", "date", name="uq_api_usage_daily_key_date"),
    )


class ApiUsageMinute(db.Model):
    __tablename__ = "api_usage_minute"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"), nullable=False)
    minute_bucket = db.Column(db.DateTime, nullable=False, index=True)
    requests_count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint(
            "key_id",
            "minute_bucket",
            name="uq_api_usage_minute_key_bucket",
        ),
    )
