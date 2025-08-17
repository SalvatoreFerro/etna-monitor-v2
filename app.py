import os
import pathlib
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = pathlib.Path(os.getenv("DATA_DIR", "/data"))
LOG_DIR = pathlib.Path(os.getenv("LOG_DIR", "/data/log"))
CSV_PATH = pathlib.Path(os.getenv("CSV_PATH", "/data/curva.csv"))

def ensure_path(p: pathlib.Path):
    """Create directory with fallback if /data is not writable"""
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except PermissionError:
        local = ROOT / p.relative_to("/data") if str(p).startswith("/data") else ROOT / "data_fallback"
        local.mkdir(parents=True, exist_ok=True)
        return local

LOG_DIR = ensure_path(LOG_DIR)
DATA_DIR = ensure_path(DATA_DIR)
CSV_PATH = ensure_path(CSV_PATH.parent) / CSV_PATH.name

log_csv = LOG_DIR / "log.csv"
if not log_csv.exists():
    log_csv.write_text("timestamp,value\n", encoding="utf-8")
if not CSV_PATH.exists():
    CSV_PATH.write_text("timestamp,value\n", encoding="utf-8")

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
