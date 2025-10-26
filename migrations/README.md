# Database migrations

This folder is reserved for Alembic migrations generated via Flask-Migrate.

To initialize the migration environment locally run:

```bash
flask db init
```

Then create and apply migrations as needed:

```bash
flask db migrate -m "<descrizione>"
flask db upgrade
```
