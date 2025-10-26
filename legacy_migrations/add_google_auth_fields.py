"""Database migration to support Google OAuth fields and optional passwords"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db
from sqlalchemy import inspect, text


def _alter_password_nullable(conn, dialect):
    if dialect == 'postgresql':
        conn.execute(text('ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL'))
    elif dialect == 'mysql':
        conn.execute(text('ALTER TABLE users MODIFY password_hash VARCHAR(128) NULL'))
    elif dialect == 'sqlite':
        # SQLite does not easily support altering nullability; rely on application schema for new deployments
        print('⚠️  Skipping password_hash nullability change on SQLite (handled via SQLAlchemy metadata).')
    else:
        raise RuntimeError(f'Unsupported database dialect: {dialect}')


def _ensure_unique_google_id(conn, dialect, inspector):
    existing_uniques = {constraint['name'] for constraint in inspector.get_unique_constraints('users')}
    existing_indexes = {index['name'] for index in inspector.get_indexes('users')}

    if dialect == 'postgresql':
        if 'uq_users_google_id' not in existing_uniques:
            conn.execute(text('ALTER TABLE users ADD CONSTRAINT uq_users_google_id UNIQUE (google_id)'))
    elif dialect == 'mysql':
        if 'uq_users_google_id' not in existing_indexes:
            conn.execute(text('ALTER TABLE users ADD UNIQUE INDEX uq_users_google_id (google_id)'))
    elif dialect == 'sqlite':
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_id ON users (google_id)'))
    else:
        raise RuntimeError(f'Unsupported database dialect: {dialect}')


def _drop_unique_google_id(conn, dialect):
    if dialect == 'postgresql':
        conn.execute(text('ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_google_id'))
    elif dialect == 'mysql':
        conn.execute(text('ALTER TABLE users DROP INDEX uq_users_google_id'))
    elif dialect == 'sqlite':
        conn.execute(text('DROP INDEX IF EXISTS uq_users_google_id'))
    else:
        raise RuntimeError(f'Unsupported database dialect: {dialect}')


def upgrade():
    """Upgrade database schema by making password optional and adding Google OAuth fields"""
    app = create_app()

    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name
        inspector = inspect(engine)

        existing_columns = []
        if 'users' in inspector.get_table_names():
            existing_columns = [column['name'] for column in inspector.get_columns('users')]
        else:
            print('📋 Users table not found; running db.create_all() instead.')
            db.create_all()
            return

        with engine.connect() as conn:
            if 'password_hash' in existing_columns:
                try:
                    _alter_password_nullable(conn, dialect)
                    conn.commit()
                    print('✅ Updated users.password_hash to allow NULL values')
                except Exception as exc:
                    conn.rollback()
                    print(f'⚠️  Could not alter password_hash nullability: {exc}')

            new_columns = {
                'google_id': 'VARCHAR(255)',
                'name': 'VARCHAR(255)',
                'picture_url': 'VARCHAR(512)'
            }

            for column_name, column_type in new_columns.items():
                if column_name not in existing_columns:
                    try:
                        conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_type}'))
                        conn.commit()
                        print(f'✅ Added column {column_name} to users table')
                    except Exception as exc:
                        conn.rollback()
                        print(f'⚠️  Could not add column {column_name}: {exc}')
                else:
                    print(f'ℹ️  Column {column_name} already exists on users table')

            try:
                _ensure_unique_google_id(conn, dialect, inspector)
                conn.commit()
                print('✅ Ensured unique constraint on users.google_id')
            except Exception as exc:
                conn.rollback()
                print(f'⚠️  Could not ensure unique constraint on google_id: {exc}')


def downgrade():
    """Downgrade database schema by removing Google OAuth fields and reinstating password requirement"""
    app = create_app()

    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name

        with engine.connect() as conn:
            try:
                _drop_unique_google_id(conn, dialect)
                conn.commit()
                print('✅ Removed unique constraint on users.google_id')
            except Exception as exc:
                conn.rollback()
                print(f'⚠️  Could not remove unique constraint on google_id: {exc}')

            for column_name in ['picture_url', 'name', 'google_id']:
                try:
                    conn.execute(text(f'ALTER TABLE users DROP COLUMN {column_name}'))
                    conn.commit()
                    print(f'✅ Dropped column {column_name} from users table')
                except Exception as exc:
                    conn.rollback()
                    print(f'⚠️  Could not drop column {column_name}: {exc}')

            try:
                if dialect == 'postgresql':
                    conn.execute(text('ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL'))
                elif dialect == 'mysql':
                    conn.execute(text('ALTER TABLE users MODIFY password_hash VARCHAR(128) NOT NULL'))
                elif dialect == 'sqlite':
                    print('⚠️  Skipping password_hash nullability revert on SQLite (requires table rebuild).')
                else:
                    raise RuntimeError(f'Unsupported database dialect: {dialect}')
                conn.commit()
                print('✅ Reinstated NOT NULL constraint on users.password_hash')
            except Exception as exc:
                conn.rollback()
                print(f'⚠️  Could not reinstate password_hash NOT NULL constraint: {exc}')


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
