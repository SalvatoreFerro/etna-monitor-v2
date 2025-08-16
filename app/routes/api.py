import os
import pandas as pd
from flask import Blueprint, jsonify
from pathlib import Path

api_bp = Blueprint("api", __name__)

@api_bp.get("/api/curva")
def get_curva():
    """Return curva.csv data as JSON"""
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    
    if not os.path.exists(csv_path):
        return jsonify({
            "ok": False, 
            "error": "CSV not found", 
            "csv_path": csv_path
        }), 404
    
    try:
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        if df.empty:
            return jsonify({"ok": True, "data": [], "last_ts": None})
        
        data = df.to_dict(orient="records")
        last_ts = df["timestamp"].max()
        
        return jsonify({
            "ok": True, 
            "data": data, 
            "last_ts": last_ts.isoformat() if pd.notna(last_ts) else None
        })
    except Exception as e:
        return jsonify({
            "ok": False, 
            "error": str(e), 
            "csv_path": csv_path
        }), 500
