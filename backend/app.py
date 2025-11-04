import sys
import os
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, jsonify, send_file
from backend.utils.extract_png import process_png_to_csv
from backend.utils.archive import ArchiveManager
import pandas as pd
import io

app = Flask(__name__)

# Initialize archive manager
archive_manager = ArchiveManager()

@app.route('/api/force_update', methods=['POST', 'GET'])
def force_update():
    """Force update of PNG data and curva.csv"""
    try:
        ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
        
        DATA_DIR = os.getenv('DATA_DIR', 'data')
        result = process_png_to_csv(ingv_url, os.path.join(DATA_DIR, "curva.csv"))

        return jsonify({
            "ok": True,
            "message": f"Data updated successfully in {result['output_path']}",
            "rows": result.get("rows"),
            "first_ts": result.get("first_ts"),
            "last_ts": result.get("last_ts"),
            "output_path": result.get("output_path"),
        })
    
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/archives/list', methods=['GET'])
def list_archives():
    """List available archived graphs"""
    try:
        from flask import request
        from datetime import timezone
        
        # Parse optional date filters from query parameters
        start_date = None
        end_date = None
        
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        if start_date_str:
            try:
                # Parse date and make it timezone-aware
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({"ok": False, "error": "Invalid start_date format. Use ISO format (YYYY-MM-DD)"}), 400
        
        if end_date_str:
            try:
                # Parse date and make it timezone-aware
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({"ok": False, "error": "Invalid end_date format. Use ISO format (YYYY-MM-DD)"}), 400
        
        archives = archive_manager.list_archives(
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({
            "ok": True,
            "count": len(archives),
            "archives": archives
        })
    
    except Exception as e:
        app.logger.exception("Failed to list archives")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/archives/graph/<date_str>', methods=['GET'])
def get_archive_graph(date_str):
    """Retrieve specific archived graph"""
    try:
        # Parse date from URL parameter (format: YYYY-MM-DD)
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Get archived PNG data
        png_data = archive_manager.get_archive(date)
        
        if png_data is None:
            return jsonify({"ok": False, "error": f"Archive not found for date {date_str}"}), 404
        
        # Return PNG image
        return send_file(
            io.BytesIO(png_data),
            mimetype='image/png',
            as_attachment=False,
            download_name=f'etna_{date_str}.png'
        )
    
    except Exception as e:
        app.logger.exception("Failed to retrieve archive graph")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/archives/data/<date_str>', methods=['GET'])
def get_archive_data(date_str):
    """Get processed data for a specific date"""
    try:
        # Parse date from URL parameter
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Get archived PNG data
        png_data = archive_manager.get_archive(date)
        
        if png_data is None:
            return jsonify({"ok": False, "error": f"Archive not found for date {date_str}"}), 404
        
        # Process PNG to extract data
        from backend.utils.extract_png import extract_green_curve_from_png
        df = extract_green_curve_from_png(png_data, end_time=date)
        
        if df.empty:
            return jsonify({
                "ok": True,
                "date": date_str,
                "data": [],
                "count": 0
            })
        
        # Convert to JSON-friendly format
        df_copy = df.copy()
        df_copy['timestamp'] = df_copy['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        data_list = df_copy.to_dict('records')
        
        return jsonify({
            "ok": True,
            "date": date_str,
            "count": len(data_list),
            "data": data_list
        })
    
    except Exception as e:
        app.logger.exception("Failed to retrieve archive data")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
