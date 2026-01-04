# Render Deployment Configuration Guide

## Build Command

**Option 1 (Recommended):** Set this as the Build Command in your Render service dashboard:

```
pip install -r requirements.txt
```

**Option 2 (Alternative):** If you need to run migrations during build (requires Flask-Migrate available on the image):

```
pip install -r requirements.txt && FLASK_APP=app:create_app flask db upgrade
```

## Environment Variables

Set these in your Render service dashboard:

```
LOG_DIR=/data/log
DATA_DIR=/data
CSV_PATH=/data/curva.csv
FLASK_ENV=production
SECRET_KEY=your-production-secret-key
CRON_SECRET=your-cron-secret
DATABASE_URL=sqlite:////data/etna_monitor.db
STATIC_ASSET_VERSION=$(git rev-parse --short HEAD)
WORKER_HEARTBEAT_INTERVAL=30
WORKER_ADVISORY_LOCK_ID=862421
RUN_DB_INIT_ON_STARTUP=1

# Stripe Billing (Production Keys)
STRIPE_PUBLIC_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PREMIUM=price_...

# For development/testing
# STRIPE_PUBLIC_KEY=pk_test_...
# STRIPE_SECRET_KEY=sk_test_...
```

## Disk Configuration

1. Go to your Render service dashboard
2. Navigate to "Settings" → "Disks"
3. Add Disk:
   - **Name**: etna-data
   - **Mount path**: /data
   - **Size**: 1 GB

## Start Command

Imposta il comando di avvio per il **web service** su:
```
python startup.py
```

Questo script esegue automaticamente il bootstrap delle directory (`DATA_DIR`, `LOG_DIR`), verifica lo stato delle migrazioni e – grazie alla variabile `ALLOW_AUTO_MIGRATE` impostata internamente – lancia `alembic upgrade` prima di avviare Gunicorn.

Configura anche un comando di **pre-deploy** su Render per applicare le migrazioni in modo deterministico prima di ogni deploy:
```
python -m scripts.run_migrations
```

Il worker resta invariato:
```
python -m app.worker
```

L'applicazione verifica lo stato delle migrazioni Alembic durante la creazione dell'app Flask (sia nel processo web che nel worker). In produzione il bootstrap fallisce se lo schema non è aggiornato a `head`; con lo script di pre-deploy e `startup.py` le migrazioni vengono applicate automaticamente evitando errori di multi-head. Il worker (`python -m app.worker`) si occupa di Telegram bot e scheduler APScheduler applicando un advisory lock Postgres per evitare istanze duplicate.

## Render Cron: aggiornamento CSV + alert batch

Per gli alert periodici non usare `app.worker`/APScheduler: crea un cron Render (ogni ora) che:

1. aggiorna `curva.csv` con lo script già presente;
2. chiama l'endpoint interno protetto per l'invio batch degli alert.

Esempio di comando cron (schedulato `0 * * * *`):

```
PYTHONPATH=/opt/render/project/src python scripts/csv_updater.py && \
curl -sS -X POST "https://your-app.onrender.com/internal/cron/check-alerts?key=$CRON_SECRET"
```

Assicurati che `CRON_SECRET` sia configurato sia nel web service (per validare la richiesta) sia nel cron job (per firmare la chiamata). L'endpoint cron esegue solo la logica di invio alert Telegram e non dipende da tabelle/admin audit.

## Health Check Configuration

Set the health check path in Render to: `/healthz`. For the worker service you can use `/internal/worker/health` (solo per chiamate interne) per verificare l'heartbeat salvato in `DATA_DIR/worker-heartbeat.json`.

## Stripe Webhook Configuration

1. **In Stripe Dashboard**, add webhook endpoint: `https://your-app.onrender.com/billing/webhook`
2. **Select events**: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`
3. **Copy webhook secret** to `STRIPE_WEBHOOK_SECRET` environment variable

## Verification Post-Deploy

After deployment, verify these items:

1. **Gunicorn startup**: Check logs for:
   ```
   [INFO] Starting gunicorn 21.2.0
   [INFO] Listening at: http://0.0.0.0:$PORT
   ```

2. **Health check**: Test endpoint:
   ```
   GET https://your-app.onrender.com/healthz
   Response: {
     "ok": true,
     "uptime_seconds": <float>,
     "csv": {...},
     "premium_users": <int>,
     "telegram_bot": {...}
   }
   ```

3. **Home page**: Verify the home page loads without 500 errors, even if CSV files don't exist (they will be created automatically)

4. **PWA installation**: Test that the app can be installed and works offline

5. **Stripe billing**: Test the pricing page loads without Stripe errors and checkout flow works

6. **No Flask dev server**: Logs should NOT show:
   ```
   * Running on http://127.0.0.1:5000
   * Debug mode: on
   ```

## Troubleshooting

### Common Issues

1. **"gunicorn: command not found"**
   - Ensure `gunicorn>=21.2` is in requirements.txt
   - Use the fallback start command above

2. **Permission denied for /data**
   - The app automatically falls back to local directories (log/, data/)
   - Ensure the disk is properly mounted at /data

3. **FileNotFoundError for CSV files**
   - The app automatically creates missing CSV files with headers
   - Check that LOG_DIR and DATA_DIR environment variables are set

4. **Port binding issues**
   - Ensure the start command uses `0.0.0.0:$PORT`
   - Do not use hardcoded ports like 5000 or 8000

### Expected File Structure

After successful deployment, the app will create:
```
/data/
├── log/
│   └── log.csv
└── curva.csv
```

If /data is not writable, fallback structure:
```
project_root/
├── log/
│   └── log.csv
└── data/
    └── curva.csv
```

## API Endpoints

### POST/GET /api/force_update

Forces an update of the tremor data by downloading the latest PNG from INGV and processing it.

**Environment Variables:**
- `INGV_URL`: PNG source URL (default: https://www.ct.ingv.it/RMS_Etna/2.png)
- `CSV_PATH`: Output CSV path (default: /data/curva.csv)

**Response:**
```json
{
  "ok": true,
  "message": "Data updated successfully",
  "rows": 1440,
  "last_ts": "2025-08-16 20:00:00",
  "output_path": "/data/curva.csv"
}
```

**Test commands:**
```bash
curl -X POST https://your-app.onrender.com/api/force_update
curl https://your-app.onrender.com/api/force_update
```

## Testing Locally

Before deploying to Render, test locally:

```bash
# Set environment variables
export LOG_DIR=/data/log
export DATA_DIR=/data
export CSV_PATH=/data/curva.csv
export INGV_URL=https://www.ct.ingv.it/RMS_Etna/2.png
export PORT=5000

# Test gunicorn startup
gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app

# Test health check
curl http://localhost:5000/healthz
# Expected: {"ok":true}

# Test API endpoint
curl -X POST http://localhost:5000/api/force_update
curl http://localhost:5000/api/force_update

# Test home page
curl http://localhost:5000/
# Expected: 200 OK (no 500 errors)

# Run tests
pytest -q tests/test_healthz.py
pytest -q tests/test_force_update_api.py
```
