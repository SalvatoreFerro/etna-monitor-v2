"""
Database migration to add billing fields to users table and create billing tables
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from app.models import db
from app.models.user import User
from app.models.billing import Plan, Invoice, EventLog
import json

def upgrade():
    app = create_app()
    
    with app.app_context():
        db.create_all()
        
        free_plan = Plan(
            code='FREE',
            name='Free Plan',
            price_cents=0,
            currency='EUR',
            features=json.dumps([
                'Last 7 days of data',
                'Basic tremor monitoring',
                'Fixed threshold (2.0 mV)',
                'Standard refresh rate'
            ])
        )
        
        premium_plan = Plan(
            code='PREMIUM',
            name='Premium Plan',
            price_cents=999,
            currency='EUR',
            stripe_price_id='price_premium_monthly',
            features=json.dumps([
                'Complete data history',
                'Real-time monitoring',
                'Custom thresholds (0.1-10 mV)',
                'Instant alerts (Email + Telegram)',
                'Data export (CSV, PNG)',
                'Event history & logs',
                'Priority support',
                'Advanced analytics'
            ])
        )
        
        db.session.add(free_plan)
        db.session.add(premium_plan)
        db.session.commit()
        
        print("✅ Billing tables created and plans added")

def downgrade():
    app = create_app()
    
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        print("✅ Billing tables removed")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
