import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import cv2
import numpy as np
import requests

from .time import to_iso_utc


EXTRACTION_DURATION = timedelta(days=7)
DEFAULT_GREEN_LOWER = np.array([35, 40, 40])
DEFAULT_GREEN_UPPER = np.array([90, 255, 255])


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
    mask = cv2.inRange(hsv, DEFAULT_GREEN_LOWER, DEFAULT_GREEN_UPPER)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.dilate(mask, kernel, iterations=1)
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
    max_visible_pixel = None
    if np.any(mask == 255):
        max_visible_pixel = int(np.min(np.where(mask == 255)[0]))
    for x in range(width):
        col = mask[:, x]
        y_vals = np.where(col == 255)[0]
        if len(y_vals) > 0:
            y_peak = int(np.min(y_vals))
            y_median = float(np.median(y_vals))
            timestamp = start_time + timedelta(seconds=seconds_per_pixel * x)
            value_raw = float(pixel_to_mV(y_peak))
            value_avg = float(pixel_to_mV(y_median))
            data.append(
                {
                    "timestamp": timestamp,
                    "value": value_raw,
                    "value_max": value_raw,
                    "value_avg": value_avg,
                }
            )

    if data:
        last_value = data[-1]["value"]
        data[-1]["timestamp"] = end_time
        data[-1]["value"] = last_value

    interval_seconds = seconds_per_pixel if width else None
    metadata = {
        "pixel_columns": width,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": total_seconds,
        "interval_seconds": interval_seconds,
        "max_visible_pixel": max_visible_pixel,
        "max_visible_value": pixel_to_mV(max_visible_pixel) if max_visible_pixel is not None else None,
    }
    return data, metadata

def _to_datetime_utc(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_and_save_data(data, output_path=None):
    """Clean signal from noise/duplicates and save to CSV"""
    if output_path is None:
        DATA_DIR = os.getenv('DATA_DIR', 'data')
        output_path = os.path.join(DATA_DIR, 'curva.csv')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cleaned = {}

    for item in data:
        if not item:
            continue
        if isinstance(item, dict):
            ts_raw = item.get("timestamp")
            value = item.get("value")
            value_max = item.get("value_max", value)
            value_avg = item.get("value_avg", value)
        else:
            if len(item) < 2:
                continue
            ts_raw, value = item[0], item[1]
            value_max = value
            value_avg = value
        dt = _to_datetime_utc(ts_raw)
        if dt is None:
            continue
        try:
            numeric = float(value)
            numeric_max = float(value_max)
            numeric_avg = float(value_avg)
        except (TypeError, ValueError):
            continue
        if numeric <= 0:
            continue
        key = dt.isoformat()
        if key in cleaned and numeric <= cleaned[key]["value"]:
            continue
        cleaned[key] = {
            "timestamp": dt,
            "value": numeric,
            "value_max": max(numeric, numeric_max),
            "value_avg": numeric_avg if numeric_avg > 0 else numeric,
        }

    cleaned_rows = sorted(cleaned.values(), key=lambda row: row["timestamp"])

    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "value", "value_max", "value_avg"])
        for row in cleaned_rows:
            writer.writerow(
                [
                    _format_timestamp(row["timestamp"]),
                    f"{row['value']}",
                    f"{row['value_max']}",
                    f"{row['value_avg']}",
                ]
            )

    return output_path, cleaned_rows

def process_png_to_csv(url="https://www.ct.ingv.it/RMS_Etna/2.png", output_path=None):
    """Complete pipeline: download PNG, extract curve, save CSV"""
    DATA_DIR = os.getenv('DATA_DIR', 'data')
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    png_bytes, reference_time = download_png(url)
    data, metadata = extract_green_curve_from_png(
        png_bytes,
        end_time=reference_time,
        duration=EXTRACTION_DURATION,
    )

    if output_path is None:
        output_path = os.path.join(DATA_DIR, 'curva.csv')

    final_path, cleaned_rows = clean_and_save_data(data, output_path)

    last_ts = cleaned_rows[-1]["timestamp"] if cleaned_rows else None
    first_ts = cleaned_rows[0]["timestamp"] if cleaned_rows else None
    interval_minutes = None
    if metadata.get("interval_seconds"):
        interval_minutes = metadata["interval_seconds"] / 60

    end_time = metadata.get("end_time")
    max_7d_value = None
    max_7d_ts = None
    max_24h_value = None
    max_24h_ts = None
    if cleaned_rows:
        max_row = max(cleaned_rows, key=lambda row: row["value"])
        max_7d_value = max_row["value"]
        max_7d_ts = max_row["timestamp"]
        if end_time:
            window_start = end_time - timedelta(hours=24)
            window_rows = [row for row in cleaned_rows if row["timestamp"] >= window_start]
            if window_rows:
                max_24h_row = max(window_rows, key=lambda row: row["value"])
                max_24h_value = max_24h_row["value"]
                max_24h_ts = max_24h_row["timestamp"]

    logger.info(
        "Estratti %s punti INGV start_ref=%s end_ref=%s durata=%ss colonne=%s intervallo≈%smin first_ts=%s last_ts=%s",
        len(cleaned_rows),
        to_iso_utc(metadata.get("start_time")),
        to_iso_utc(metadata.get("end_time")),
        metadata.get("duration_seconds"),
        metadata.get("pixel_columns"),
        f"{interval_minutes:.2f}" if interval_minutes else "n/a",
        to_iso_utc(first_ts),
        to_iso_utc(last_ts),
    )
    logger.info(
        "Picchi INGV max_7d=%s@%s max_24h=%s@%s max_png=%s",
        f"{max_7d_value:.4f}" if max_7d_value else "n/a",
        to_iso_utc(max_7d_ts),
        f"{max_24h_value:.4f}" if max_24h_value else "n/a",
        to_iso_utc(max_24h_ts),
        f"{metadata.get('max_visible_value'):.4f}" if metadata.get("max_visible_value") else "n/a",
    )

    return {
        "rows": len(cleaned_rows),
        "first_ts": to_iso_utc(first_ts),
        "last_ts": to_iso_utc(last_ts),
        "output_path": final_path,
        "start_time": to_iso_utc(metadata.get("start_time")),
        "end_time": to_iso_utc(metadata.get("end_time")),
        "duration_minutes": (metadata.get("duration_seconds") / 60) if metadata.get("duration_seconds") else None,
        "interval_minutes": interval_minutes,
        "pixel_columns": metadata.get("pixel_columns"),
    }
