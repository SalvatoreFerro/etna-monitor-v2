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
from sqlalchemy import text, inspect

def upgrade():
    """Upgrade database schema by adding billing fields to users table"""
    try:
        app = create_app()
        
        with app.app_context():
            print("🔄 Starting database migration...")
            
            import os
            from pathlib import Path
            data_dir = os.getenv('DATA_DIR', '/var/tmp')
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            
            inspector = inspect(db.engine)
            
            if 'users' in inspector.get_table_names():
                existing_columns = [col['name'] for col in inspector.get_columns('users')]
                print(f"📋 Existing users table columns: {existing_columns}")
                
                billing_columns = [
                    ('stripe_customer_id', 'VARCHAR(100)'),
                    ('subscription_status', 'VARCHAR(20) DEFAULT "free"'),
                    ('subscription_id', 'VARCHAR(100)'),
                    ('current_period_end', 'DATETIME'),
                    ('trial_end', 'DATETIME'),
                    ('billing_email', 'VARCHAR(120)'),
                    ('company_name', 'VARCHAR(200)'),
                    ('vat_id', 'VARCHAR(50)')
                ]
                
                columns_added = 0
                for column_name, column_def in billing_columns:
                    if column_name not in existing_columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}'))
                                conn.commit()
                            print(f"✅ Added column {column_name} to users table")
                            columns_added += 1
                        except Exception as e:
                            print(f"⚠️  Could not add column {column_name}: {e}")
                
                if columns_added == 0:
                    print("✅ All billing columns already exist")
                else:
                    print(f"✅ Added {columns_added} billing columns to users table")
            else:
                print("📋 Users table not found, will be created by db.create_all()")
            
            db.create_all()
            print("✅ All database tables created/verified")
            
            try:
                existing_plans = Plan.query.count()
                if existing_plans == 0:
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
                    print("✅ Default plans added to database")
                else:
                    print(f"✅ Plans already exist ({existing_plans} found)")
            except Exception as e:
                print(f"⚠️  Could not add plans: {e}")
            
            print("🎉 Database migration completed successfully!")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def downgrade():
    app = create_app()
    
    with app.app_context():
        billing_columns = [
            'stripe_customer_id', 'subscription_status', 'subscription_id',
            'current_period_end', 'trial_end', 'billing_email', 
            'company_name', 'vat_id'
        ]
        
        for column_name in billing_columns:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(f'ALTER TABLE users DROP COLUMN {column_name}'))
                    conn.commit()
                print(f"✅ Removed column {column_name} from users table")
            except Exception as e:
                print(f"⚠️  Could not remove column {column_name}: {e}")
        
        # Drop billing tables
        try:
            with db.engine.connect() as conn:
                conn.execute(text('DROP TABLE IF EXISTS event_logs'))
                conn.execute(text('DROP TABLE IF EXISTS invoices'))
                conn.execute(text('DROP TABLE IF EXISTS plans'))
                conn.commit()
            print("✅ Billing tables removed")
        except Exception as e:
            print(f"⚠️  Error removing billing tables: {e}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
