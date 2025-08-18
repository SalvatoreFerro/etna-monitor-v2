#!/usr/bin/env python3

from app import create_app
from app.models import db
from app.models.user import User

def setup_test_user():
    """Set up test Premium user for Telegram testing"""
    app = create_app()
    
    with app.app_context():
        admin = User.query.filter_by(email='admin@etnamonitor.com').first()
        if admin:
            admin.premium = True
            admin.chat_id = '123456789'  # Replace with real chat_id for testing
            admin.threshold = 1.0  # Low threshold to trigger alerts easily
            db.session.commit()
            print(f'✅ Premium user configured: {admin.email}')
            print(f'   Chat ID: {admin.chat_id}')
            print(f'   Threshold: {admin.threshold} mV')
        else:
            print('❌ Admin user not found')

if __name__ == "__main__":
    setup_test_user()
