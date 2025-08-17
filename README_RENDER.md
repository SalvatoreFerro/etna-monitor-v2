# Render Deployment Configuration Guide

## Build Command

Set this as the Build Command in your Render service dashboard:

```
pip install -r requirements.txt && python migrations/add_billing_fields.py
```

## Environment Variables

Set these in your Render service dashboard:

```
LOG_DIR=/data/log
DATA_DIR=/data
CSV_PATH=/data/curva.csv
FLASK_ENV=production
SECRET_KEY=your-production-secret-key
DATABASE_URL=sqlite:////data/etna_monitor.db
```

## Disk Configuration

1. Go to your Render service dashboard
2. Navigate to "Settings" → "Disks"
3. Add Disk:
   - **Name**: etna-data
   - **Mount path**: /data
   - **Size**: 1 GB

## Start Command

Set the Start Command in your Render service dashboard to:
```
gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app
```

**Alternative** (if you prefer using Procfile):
Leave the Start Command field **EMPTY** and ensure Procfile contains:
```
web: gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app
```

## Health Check Configuration

Set the health check path in Render to: `/healthz`

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
   Response: {"ok": true} with 200 status
   ```

3. **Home page**: Verify the home page loads without 500 errors, even if CSV files don't exist (they will be created automatically)

4. **No Flask dev server**: Logs should NOT show:
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
