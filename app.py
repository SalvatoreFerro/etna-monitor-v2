import os
import sys
from pathlib import Path

if '.' not in sys.path:
    sys.path.insert(0, '.')

LOG_DIR = os.getenv("LOG_DIR", "/data/log")
DATA_DIR = os.getenv("DATA_DIR", "/data")

try:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
except PermissionError:
    LOG_DIR = "log"
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

try:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
except PermissionError:
    DATA_DIR = "data"
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
