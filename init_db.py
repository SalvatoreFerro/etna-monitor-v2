#!/usr/bin/env python3
"""Initialize database and create admin user"""

from app import create_app
from app.models import db
from app.models.user import User
import os

def init_database():
    app = create_app()
    
    with app.app_context():
        db.create_all()
        
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@etnamonitor.com')
        admin_google_id = os.getenv('ADMIN_GOOGLE_ID')
        
        if not User.query.filter_by(email=admin_email).first():
            admin_user = User(
                email=admin_email,
                is_admin=True,
                premium=True
            )
            if admin_google_id:
                admin_user.google_id = admin_google_id
            db.session.add(admin_user)
            db.session.commit()
            print(f"Admin user created: {admin_email}")
        else:
            print("Admin user already exists")

if __name__ == '__main__':
    init_database()
