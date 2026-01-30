from . import db
from datetime import datetime

class Event(db.Model):
    __tablename__ = 'events'
    __table_args__ = (
        db.Index("ix_events_user_id_timestamp", "user_id", "timestamp"),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  # 'alert', 'threshold_change', 'login'
    value = db.Column(db.Float, nullable=True)  # tremor value for alerts
    threshold = db.Column(db.Float, nullable=True)  # threshold at time of event
    message = db.Column(db.String(255), nullable=True)
    
    user = db.relationship('User', backref=db.backref('events', lazy=True))
    
    def __repr__(self):
        return f'<Event {self.event_type} for {self.user_id} at {self.timestamp}>'
