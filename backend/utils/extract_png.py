import os
import cv2
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta
from pathlib import Path

def download_png(url="https://www.ct.ingv.it/RMS_Etna/2.png"):
    """Download PNG from INGV URL"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content

def extract_green_curve_from_png(png_bytes):
    """Extract green curve from PNG using HSV masking"""
    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    cropped = img[50:-20, 100:-30]
    
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([40, 40, 40]), np.array([80, 255, 255]))
    height, width = mask.shape

    def pixel_to_mV(y_pixel):
        """Convert Y pixel to mV using logarithmic scale"""
        y_norm = y_pixel / height
        log_val = 1 - y_norm * 2
        return 10 ** log_val

    def pixel_to_time(x_pixel):
        """Convert X pixel to timestamp (4 days of data)"""
        total_minutes = 4 * 24 * 60
        minutes = int((x_pixel / width) * total_minutes)
        base_time = datetime.now() - timedelta(days=4)
        return base_time + timedelta(minutes=minutes)

    data = []
    for x in range(width):
        col = mask[:, x]
        y_vals = np.where(col == 255)[0]
        if len(y_vals) > 0:
            y = y_vals[-1]
            data.append((pixel_to_time(x), pixel_to_mV(y)))
    
    return pd.DataFrame(data, columns=["timestamp", "value"])

def clean_and_save_data(df, output_path=None):
    """Clean signal from noise/duplicates and save to CSV"""
    if output_path is None:
        DATA_DIR = os.getenv('DATA_DIR', 'data')
        output_path = os.path.join(DATA_DIR, 'curva.csv')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    
    df = df[(df["value"] >= 0.01) & (df["value"] <= 100)]
    
    df.to_csv(output_path, index=False)
    return output_path

def process_png_to_csv(url="https://www.ct.ingv.it/RMS_Etna/2.png", output_path=None):
    """Complete pipeline: download PNG, extract curve, save CSV"""
    DATA_DIR = os.getenv('DATA_DIR', 'data')
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    
    png_bytes = download_png(url)
    df = extract_green_curve_from_png(png_bytes)
    
    if output_path is None:
        output_path = os.path.join(DATA_DIR, 'curva.csv')
    return clean_and_save_data(df, output_path)
