from flask import Blueprint, render_template, jsonify
import pandas as pd
import os
import pathlib
from pathlib import Path

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
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
    
    log_file = os.path.join(LOG_DIR, "log.csv")
    log_file_alt = os.path.join(LOG_DIR, "log.cvs")
    
    try:
        if os.path.exists(log_file):
            df = pd.read_csv(log_file, parse_dates=["timestamp"])
        elif os.path.exists(log_file_alt):
            df = pd.read_csv(log_file_alt, parse_dates=["timestamp"])
        else:
            empty_df = pd.DataFrame(columns=["timestamp", "mV"])
            empty_df.to_csv(log_file, index=False)
            df = empty_df
        
        if not df.empty:
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
            timestamps = df["timestamp"].tolist()
            values = df["mV"].tolist()
        else:
            timestamps = []
            values = []
    except Exception as e:
        timestamps = []
        values = []
    
    return render_template("index.html", labels=timestamps, values=values)

@bp.route("/healthz")
def healthcheck():
    """Health check endpoint for Render deployment"""
    return jsonify({"ok": True}), 200

@bp.route("/api/force_update", methods=["POST", "GET"])
def force_update():
    """Force update of PNG data and curva.csv"""
    try:
        CSV_PATH = pathlib.Path(os.getenv("CSV_PATH", "/data/curva.csv"))
        INGV_URL = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
        
        try:
            CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
            local_path = ROOT / "data" / "curva.csv"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            CSV_PATH = local_path
        
        from backend.utils.extract_png import process_png_to_csv
        result = process_png_to_csv(INGV_URL, str(CSV_PATH))
        
        return jsonify({
            "ok": True,
            "message": "Data updated successfully",
            **result
        }), 200
        
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
