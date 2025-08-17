import os
import pandas as pd
from flask import Blueprint, jsonify, request
from pathlib import Path
from backend.utils.extract_png import process_png_to_csv

api_bp = Blueprint("api", __name__)

@api_bp.get("/api/curva")
def get_curva():
    """Return curva.csv data as JSON with no-cache headers"""
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) <= 20:
        try:
            ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
            result = process_png_to_csv(ingv_url, csv_path)
            print(f"Auto-generated data: {result['rows']} points")
        except Exception as e:
            print(f"Failed to auto-generate data: {e}")
            return jsonify({
                "ok": True, 
                "data": [], 
                "last_ts": None,
                "rows": 0
            })
    
    try:
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        if df.empty:
            return jsonify({
                "ok": True, 
                "data": [], 
                "last_ts": None,
                "rows": 0
            })
        
        data = df.to_dict(orient="records")
        last_ts = df["timestamp"].max()
        
        response = jsonify({
            "ok": True, 
            "data": data, 
            "last_ts": last_ts.isoformat() if pd.notna(last_ts) else None,
            "rows": len(data)
        })
        
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        return jsonify({
            "ok": False, 
            "error": str(e), 
            "csv_path": csv_path
        }), 500

@api_bp.route("/api/status")
def get_status():
    """Return current status and metrics"""
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    threshold = float(os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))
    
    try:
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            if not df.empty:
                current_value = float(df["value"].iloc[-1])
                above_threshold = current_value > threshold
                last_update = df["timestamp"].max().isoformat()
                
                return jsonify({
                    "ok": True,
                    "current_value": current_value,
                    "above_threshold": above_threshold,
                    "threshold": threshold,
                    "last_update": last_update,
                    "total_points": len(df)
                })
        
        return jsonify({
            "ok": True,
            "current_value": 0.0,
            "above_threshold": False,
            "threshold": threshold,
            "last_update": None,
            "total_points": 0
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

@api_bp.route("/api/force_update", methods=["GET", "POST"])
def force_update():
    """Force update of tremor data from INGV source"""
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
