"""WSGI entry-point for gunicorn deployments."""

import os

from app import create_app

os.environ.setdefault("FLASK_APP", "app:create_app")

app = create_app()

if __name__ == "__main__":
    app.run()
