from flask import Blueprint, render_template, jsonify
import pandas as pd
import os
import pathlib
from pathlib import Path

bp = Blueprint("main", __name__)

def _tmp_base():
    return Path(os.getenv("DATA_DIR") or os.getenv("TMPDIR") or "/var/tmp")

BASE_DIR = _tmp_base()
LOG_DIR = Path(os.getenv("LOG_DIR") or BASE_DIR / "log")
CSV_PATH = Path(os.getenv("CSV_PATH") or BASE_DIR / "curva.csv")

for p in [BASE_DIR, LOG_DIR]:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        BASE_DIR = Path("/var/tmp")
        LOG_DIR = BASE_DIR / "log"
        CSV_PATH = BASE_DIR / "curva.csv"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        break

@bp.route("/")
def index():
    return render_template("index.html")

@bp.route("/healthz")
def healthcheck():
    """Health check endpoint for Render deployment"""
    return jsonify({"ok": True}), 200

@bp.route("/api/force_update", methods=["POST", "GET"])
def force_update():
    """Force update of PNG data and curva.csv"""
    try:
        INGV_URL = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
        
        from backend.utils.extract_png import process_png_to_csv
        result = process_png_to_csv(INGV_URL, str(CSV_PATH))
        
        return jsonify({
            "ok": True,
            "message": "Data updated successfully",
            **result
        }), 200
        
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/api/curva")
def api_curva():
    """Return curva.csv data as JSON"""
    try:
        df = pd.read_csv(CSV_PATH)
        return jsonify(ok=True, rows=df.to_dict(orient="records"))
    except FileNotFoundError:
        return jsonify(ok=False, error="curva.csv not found"), 404
