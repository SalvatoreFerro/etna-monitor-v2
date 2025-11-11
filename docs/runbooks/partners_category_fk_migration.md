# Runbook: partners.category_id backfill and FK hardening

This runbook covers the safe execution of Alembic revision `202503010002`,
which backfills the `partners.category_id` column, creates the supporting
composite index and enforces the foreign key to `partner_categories` once the
data is in place. Follow these steps to minimise downtime and be ready to roll
back if anything goes wrong.

## 1. Pre-flight checklist

- [ ] Confirm that application traffic is low (ideally schedule a maintenance
      window).
- [ ] Ensure the `partner_categories` table contains the expected slugs — the
      migration maps historical `partners.category` values to these slugs.
- [ ] Verify that the Alembic head matches production (`flask db current`).

## 2. Back up the database

1. Trigger a fresh logical backup before applying the migration:
   ```bash
   pg_dump "$DATABASE_URL" \
     --format=custom \
     --file=backup/partners-category-fk_$(date +%Y%m%d%H%M).dump
   ```
2. Record the generated file name together with the migration revision ID in the
   release notes.

## 3. Estimate migration duration

The migration updates partners in chunks of 500 rows. Estimate the runtime with:

```sql
SELECT CEIL(COUNT(*) / 500.0) AS chunks
FROM partners
WHERE category IS NOT NULL AND category_id IS NULL;
```

Each chunk performs one `UPDATE` statement; expect roughly 1–2 seconds per
chunk on production hardware. Add a safety margin for the index creation
(typically <5 seconds with `CREATE INDEX CONCURRENTLY`).

## 4. Execute the migration

1. Export `FLASK_APP=app:create_app` (or source the deployment profile).
2. Apply migrations: `flask db upgrade 202503010002`.
3. Watch the application logs; the error handler now rolls back any failed
   sessions automatically, so the UI should recover gracefully from transient
   issues.

## 5. Post-migration validation

- Spot-check a few partners in the admin panel to ensure categories render.
- Run the smoke test: `flask shell -c "from app.models.partner import Partner; print(Partner.query.filter(Partner.category_id.is_(None)).count())"`. The result should be `0` or match the expected number of legacy rows without a matching category.
- Confirm the new index exists: `\di+ ix_partners_category_status_featured_sort` in `psql`.

## 6. Rollback strategy

If the migration needs to be reverted:

1. Take note of the failure reason and pause incoming admin writes.
2. Restore the pre-migration backup with `pg_restore --clean --if-exists` to a
   fresh database or, if downtime is acceptable, directly on the production
   database.
3. Alternatively, use Alembic to downgrade **before** restoring from backup:
   `flask db downgrade 202503010001`. This drops the foreign key, the index and
   the `category_id` column introduced by this migration.
4. Once the database is back to a consistent state, re-run the upgrade after
   addressing the root cause.

Keep this runbook alongside the deployment checklist so the on-call engineer
can execute the procedure without guesswork.
