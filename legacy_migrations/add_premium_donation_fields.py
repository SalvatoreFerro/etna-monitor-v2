"""Migration to add manual premium and donation tracking fields."""

import os
import sys

from sqlalchemy import inspect, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db


def upgrade():
    """Add new premium lifetime fields to the users table."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)

        if 'users' not in inspector.get_table_names():
            print("ℹ️  Users table not found, skipping premium fields migration.")
            return

        existing_columns = {col['name'] for col in inspector.get_columns('users')}
        columns_to_add = [
            ('is_premium', 'BOOLEAN DEFAULT FALSE NOT NULL'),
            ('premium_lifetime', 'BOOLEAN DEFAULT FALSE NOT NULL'),
            ('premium_since', 'TIMESTAMP'),
            ('donation_tx', 'VARCHAR(255)')
        ]

        added = 0
        for column_name, column_def in columns_to_add:
            if column_name in existing_columns:
                print(f"ℹ️  Column {column_name} already exists, skipping.")
                continue

            try:
                with db.engine.connect() as conn:
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}'))
                    conn.commit()
                print(f"✅ Added column {column_name} to users table")
                added += 1
            except Exception as exc:
                print(f"⚠️  Could not add column {column_name}: {exc}")

        if added == 0:
            print("ℹ️  No new columns added during this migration.")
        else:
            print(f"🎉 Added {added} premium donation columns to users table.")


def downgrade():
    """Remove the premium lifetime fields from the users table."""
    app = create_app()

    with app.app_context():
        columns_to_drop = ['is_premium', 'premium_lifetime', 'premium_since', 'donation_tx']

        for column_name in columns_to_drop:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(f'ALTER TABLE users DROP COLUMN {column_name}'))
                    conn.commit()
                print(f"✅ Dropped column {column_name} from users table")
            except Exception as exc:
                print(f"⚠️  Could not drop column {column_name}: {exc}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
