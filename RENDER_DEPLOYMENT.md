# Render Deployment Configuration

## Critical: Start Command Configuration

**IMPORTANT**: Render must be configured to use ONLY this start command:

```
python startup.py
```

## Current Issue

Render is executing this incorrect command:
```bash
bash -lc 'mkdir -p /data/log && [ -f /data/log/log.csv ] || echo "timestamp,value" > /data/log/log.csv; exec gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app'
```

This causes:
- Permission denied when trying to create `/data` directory
- `gunicorn: not found` error
- Complex bash operations that should be handled in Python code

## Fix in Render Dashboard

1. Go to your Render service dashboard
2. Navigate to "Settings" 
3. Find "Start Command" or "Build & Deploy" section
4. **Remove any custom start command**
5. Ensure it uses the Procfile: `web: python startup.py`

## Environment Variables

Set these in Render:
```
LOG_DIR=/data/log
DATA_DIR=/data
CSV_PATH=/data/curva.csv
```

## Persistent Storage

Mount a disk at `/data` for CSV file persistence.

## Health Check

Set health check path to: `/healthz` (the endpoint now include uptime, CSV metrics e stato bot)

## Verification

The app handles missing directories and files automatically in Python code - no bash commands needed in the start command.
