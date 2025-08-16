import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, jsonify
from backend.utils.extract_png import process_png_to_csv

app = Flask(__name__)

@app.route('/api/force_update', methods=['POST', 'GET'])
def force_update():
    """Force update of PNG data and curva.csv"""
    try:
        ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
        
        output_path = process_png_to_csv(ingv_url, "data/curva.csv")
        
        return jsonify({"ok": True, "message": f"Data updated successfully in {output_path}"})
    
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
