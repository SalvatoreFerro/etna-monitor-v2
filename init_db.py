#!/usr/bin/env python3
"""Initialize database and create admin user"""

from app import create_app
from app.models import db
from app.models.user import User
from app.utils.auth import hash_password
import os

def init_database():
    app = create_app()
    
    with app.app_context():
        db.create_all()
        
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@etnamonitor.com')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        
        if not User.query.filter_by(email=admin_email).first():
            admin_user = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                is_admin=True,
                premium=True
            )
            db.session.add(admin_user)
            db.session.commit()
            print(f"Admin user created: {admin_email}")
        else:
            print("Admin user already exists")

if __name__ == '__main__':
    init_database()
