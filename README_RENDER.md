# Render Deployment Configuration

## Start Command
```
gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app
```

## Environment Variables
- `PORT`: Automatically set by Render
- `LOG_DIR`: Optional, defaults to "log" 
- `DATA_DIR`: Optional, defaults to "data"

## Health Check
- Path: `/healthz`
- Returns: `{"status": "ok"}` with 200 status

## Persistent Storage
- Mount `/data` as persistent disk
- Set `DATA_DIR=/data` to use persistent storage
- CSV files will be stored in `/data/curva.csv` and `/data/log/log.csv`

## Local Testing
```bash
# Install dependencies
pip install -r requirements.txt

# Test Flask development server
PORT=5000 python app.py

# Test gunicorn production server
PORT=5000 gunicorn -b 0.0.0.0:$PORT app:app

# Test health check
curl http://localhost:5000/healthz
```
