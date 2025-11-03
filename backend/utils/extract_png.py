import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import requests

from .time import to_iso_utc


EXTRACTION_DURATION = timedelta(days=7)


logger = logging.getLogger(__name__)

def download_png(url="https://www.ct.ingv.it/RMS_Etna/2.png"):
    """Download PNG from INGV URL returning bytes and reference UTC timestamp."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    reference_time = datetime.now(timezone.utc)
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        try:
            parsed_dt = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            parsed_dt = None

        if parsed_dt is not None:
            if parsed_dt.tzinfo is None:
                reference_time = parsed_dt.replace(tzinfo=timezone.utc)
            else:
                reference_time = parsed_dt.astimezone(timezone.utc)

    return response.content, reference_time

def extract_green_curve_from_png(
    png_bytes,
    *,
    end_time: datetime | None = None,
    duration: timedelta = EXTRACTION_DURATION,
):
    """Extract green curve from PNG using HSV masking and temporal anchoring."""
    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    cropped = img[50:-20, 100:-30]

    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([40, 40, 40]), np.array([80, 255, 255]))
    height, width = mask.shape

    if end_time is None:
        end_time = datetime.now(timezone.utc)
    elif end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    else:
        end_time = end_time.astimezone(timezone.utc)

    start_time = end_time - duration
    total_seconds = duration.total_seconds()
    steps = max(width - 1, 1)
    seconds_per_pixel = total_seconds / steps

    def pixel_to_mV(y_pixel):
        """Convert Y pixel to mV using logarithmic scale"""
        y_norm = y_pixel / height
        log_val = 1 - y_norm * 2
        return 10 ** log_val

    data = []
    for x in range(width):
        col = mask[:, x]
        y_vals = np.where(col == 255)[0]
        if len(y_vals) > 0:
            y = y_vals[-1]
            timestamp = start_time + timedelta(seconds=seconds_per_pixel * x)
            data.append((timestamp, pixel_to_mV(y)))

    if data:
        last_value = data[-1][1]
        data[-1] = (end_time, last_value)

    df = pd.DataFrame(data, columns=["timestamp", "value"])
    interval_seconds = seconds_per_pixel if width else None
    df.attrs["metadata"] = {
        "pixel_columns": width,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": total_seconds,
        "interval_seconds": interval_seconds,
    }
    return df

def clean_and_save_data(df, output_path=None):
    """Clean signal from noise/duplicates and save to CSV"""
    if output_path is None:
        DATA_DIR = os.getenv('DATA_DIR', 'data')
        output_path = os.path.join(DATA_DIR, 'curva.csv')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    df_clean = df.copy()
    df_clean.attrs = getattr(df, "attrs", {}).copy()
    df_clean["timestamp"] = pd.to_datetime(df_clean["timestamp"], utc=True, errors="coerce")
    df_clean = df_clean.dropna(subset=["timestamp"])
    df_clean = df_clean.sort_values("timestamp").drop_duplicates("timestamp")

    df_clean = df_clean[(df_clean["value"] >= 0.01) & (df_clean["value"] <= 100)]

    df_to_save = df_clean.copy()
    df_to_save["timestamp"] = df_to_save["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    df_to_save.to_csv(output_path, index=False)
    return output_path, df_clean

def process_png_to_csv(url="https://www.ct.ingv.it/RMS_Etna/2.png", output_path=None):
    """Complete pipeline: download PNG, extract curve, save CSV"""
    DATA_DIR = os.getenv('DATA_DIR', 'data')
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    png_bytes, reference_time = download_png(url)
    df = extract_green_curve_from_png(png_bytes, end_time=reference_time, duration=EXTRACTION_DURATION)

    if output_path is None:
        output_path = os.path.join(DATA_DIR, 'curva.csv')

    final_path, cleaned_df = clean_and_save_data(df, output_path)

    last_ts = None
    first_ts = None
    if not cleaned_df.empty:
        last_ts = cleaned_df['timestamp'].iloc[-1]
        first_ts = cleaned_df['timestamp'].iloc[0]

    metadata = cleaned_df.attrs.get("metadata", {}) if not cleaned_df.empty else {}
    interval_minutes = None
    if metadata.get("interval_seconds"):
        interval_minutes = metadata["interval_seconds"] / 60

    logger.info(
        "Estratti %s punti INGV start_ref=%s end_ref=%s durata=%ss colonne=%s intervallo≈%smin first_ts=%s last_ts=%s",
        len(cleaned_df),
        to_iso_utc(metadata.get("start_time")),
        to_iso_utc(metadata.get("end_time")),
        metadata.get("duration_seconds"),
        metadata.get("pixel_columns"),
        f"{interval_minutes:.2f}" if interval_minutes else "n/a",
        to_iso_utc(first_ts),
        to_iso_utc(last_ts),
    )

    return {
        "rows": len(cleaned_df),
        "first_ts": to_iso_utc(first_ts),
        "last_ts": to_iso_utc(last_ts),
        "output_path": final_path,
        "start_time": to_iso_utc(metadata.get("start_time")),
        "end_time": to_iso_utc(metadata.get("end_time")),
        "duration_minutes": (metadata.get("duration_seconds") / 60) if metadata.get("duration_seconds") else None,
        "interval_minutes": interval_minutes,
        "pixel_columns": metadata.get("pixel_columns"),
    }
