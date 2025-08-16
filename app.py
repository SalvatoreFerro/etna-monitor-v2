import os
import sys
from pathlib import Path

if '.' not in sys.path:
    sys.path.insert(0, '.')

LOG_DIR = os.getenv("LOG_DIR", "log")
DATA_DIR = os.getenv("DATA_DIR", "data")
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
