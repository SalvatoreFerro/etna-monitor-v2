# Data Directory

This directory contains runtime data files for the EtnaMonitor project.

## Files

### Runtime CSV Files (Generated Dynamically)

- **`curva_colored.csv`** - **SINGLE SOURCE OF TRUTH**
  - The canonical tremor data file read by all components
  - Homepage graph, API endpoints, Telegram alerts, admin tools
  - Generated and updated by the background updater thread (`startup.py`)
  - Updated every 30 minutes (configurable via `CSV_UPDATE_INTERVAL`)
  - **Not tracked in Git** (ignored in `.gitignore`)
  
- **`curva.csv`** - Legacy data file (deprecated, use `curva_colored.csv`)

### Seed Files (For Development/Testing)

- **`curva_colored.csv.seed`**
  - Bootstrap data for local development and testing
  - Used by `app/bootstrap.py::ensure_curva_csv()` when main CSV is missing
  - Tracked in Git for convenience
  - Contains sample data from August 2025

### Backup Files

- **`curva_colored.csv.backup-*`** - Manual backup files
  - Tracked in Git for emergency recovery
  - Named with backup date (e.g., `curva_colored.csv.backup-2025-08`)

## Production vs Development

### Production (Render)
- Path: `/data/curva_colored.csv` (persistent disk)
- Updated by background thread in `startup.py`
- Environment: `CURVA_CSV_PATH=/data/curva_colored.csv`

### Development (Local)
- Path: `data/curva_colored.csv` (local directory)
- Bootstrap from seed file or INGV download
- Fallback to `curva.csv` if seed not available

## Bootstrap Logic

1. Check if `curva_colored.csv` exists and is non-empty → use it
2. Try to download from INGV colored URL (if `INGV_COLORED_URL` set)
3. Copy from `curva_colored.csv.seed` if available
4. Create empty placeholder with header only

## Data Pipeline

```
INGV PNG source (https://www.ct.ingv.it/RMS_Etna/0.png)
    ↓
Background Updater Thread (startup.py)
    ↓
scripts/csv_updater.py
    ↓
backend/utils/extract_colored.py
    ↓
data/curva_colored.csv ← SINGLE SOURCE OF TRUTH
    ↓
├─→ Homepage graph (app/routes/main.py)
├─→ API endpoints (app/routes/api.py)
├─→ Telegram alerts (app/services/telegram_service.py)
└─→ Admin tools (app/routes/admin.py)
```

## Recovery Procedure

If `curva_colored.csv` becomes empty or corrupted:

1. **Quick fix**: Copy from backup
   ```bash
   cp data/curva_colored.csv.backup-2025-08 data/curva_colored.csv
   ```

2. **Or restore from seed**:
   ```bash
   cp data/curva_colored.csv.seed data/curva_colored.csv
   ```

3. **Or force re-download** (production):
   - Restart the web service (triggers background updater)
   - Or manually run: `python scripts/csv_updater.py` with `RUN_ONCE=true`

## Important Notes

⚠️ **Never commit empty CSV files** - Always use `.seed` or backup files
⚠️ **Never manually edit** `curva_colored.csv` - It's generated automatically
✅ **Always update** `curva_colored.csv.seed` with fresh sample data for testing
