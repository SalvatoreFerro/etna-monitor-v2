from . import db

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    premium = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    chat_id = db.Column(db.String(50), nullable=True)
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
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    def __repr__(self):
        return f'<User {self.email}>'
