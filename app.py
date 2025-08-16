import os
import sys

if '.' not in sys.path:
    sys.path.insert(0, '.')

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
