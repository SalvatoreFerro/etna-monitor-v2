# Render Deployment Configuration Guide

## Environment Variables

Set these in your Render service dashboard:

```
LOG_DIR=/data/log
DATA_DIR=/data
CSV_PATH=/data/curva.csv
FLASK_ENV=production
```

## Disk Configuration

1. Go to your Render service dashboard
2. Navigate to "Settings" → "Disks"
3. Add Disk:
   - **Name**: etna-data
   - **Mount path**: /data
   - **Size**: 1 GB

## Start Command

**IMPORTANT**: Leave the Start Command field **EMPTY** in the Render dashboard to use the Procfile.

If for some reason you cannot use the Procfile, set the Start Command to:
```
gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app
```

**Fallback** (only if gunicorn not found):
```
bash -lc 'python -m pip install --no-cache-dir gunicorn && exec gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app'
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

## Testing Locally

Before deploying to Render, test locally:

```bash
# Set environment variables
export LOG_DIR=/data/log
export DATA_DIR=/data
export CSV_PATH=/data/curva.csv
export PORT=5000

# Test gunicorn startup
gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app

# Test health check
curl http://localhost:5000/healthz
# Expected: {"ok":true}

# Test home page
curl http://localhost:5000/
# Expected: 200 OK (no 500 errors)

# Run tests
pytest -q tests/test_healthz.py
```
