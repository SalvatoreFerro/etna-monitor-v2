#!/usr/bin/env python3

from app import create_app
from app.models import db
from sqlalchemy import text

def migrate_database():
    """Add email_alerts column to users table if it doesn't exist"""
    app = create_app()
    
    with app.app_context():
        try:
            with db.engine.connect() as connection:
                result = connection.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result]
                
                if 'email_alerts' not in columns:
                    print("Adding email_alerts column...")
                    connection.execute(text('ALTER TABLE users ADD COLUMN email_alerts BOOLEAN DEFAULT 0 NOT NULL'))
                    connection.commit()
                    print("✅ email_alerts column added successfully")
                else:
                    print("✅ email_alerts column already exists")
                    
                result = connection.execute(text('PRAGMA table_info(users)'))
                columns = [row[1] for row in result]
                print(f"Current columns: {columns}")
            
        except Exception as e:
            print(f"❌ Migration error: {e}")
            return False
    
    return True

if __name__ == "__main__":
    migrate_database()
