from flask import Blueprint, render_template, jsonify
import pandas as pd
import os
import pathlib
from pathlib import Path
from backend.utils.extract_png import process_png_to_csv
from ..utils.decorators import requires_premium

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            if not df.empty:
                timestamps = df["timestamp"].dt.strftime('%Y-%m-%d %H:%M:%S').tolist()
                values = df["value"].tolist()
            else:
                timestamps = []
                values = []
        except Exception as e:
            print(f"Error reading CSV: {e}")
            timestamps = []
            values = []
    else:
        timestamps = []
        values = []
    
    return render_template("index.html", labels=timestamps, values=values)

@bp.route("/pricing")
def pricing():
    return render_template("pricing.html")

@bp.route("/healthz")
def healthcheck():
    return jsonify({"status": "ok"}), 200

@bp.route("/api/force_update", methods=["GET", "POST"])
@requires_premium
def force_update():
    try:
        ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
        csv_path = os.getenv('CSV_PATH', '/var/tmp/curva.csv')
        
        result = process_png_to_csv(ingv_url, csv_path)
        
        return jsonify({
            "ok": True,
            "rows": result["rows"],
            "last_ts": result["last_ts"],
            "output_path": result["output_path"]
        }), 200
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
