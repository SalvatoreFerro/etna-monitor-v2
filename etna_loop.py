"""
⚠️  DEPRECATED SCRIPT - DO NOT USE IN PRODUCTION ⚠️

This script is DEPRECATED and should NOT be used in production.

ISSUES:
- Writes to log/log.csv instead of canonical data/curva_colored.csv
- Uses different column names (timestamp,mV) vs canonical (timestamp,value)
- Has hardcoded base time datetime(2025, 5, 5, 23, 0) which is incorrect
- Runs parallel data pipeline that conflicts with csv_updater.py

USE INSTEAD:
- scripts/csv_updater.py for data extraction
- scripts/update_and_check_alerts.py for cron jobs

This file is kept for reference only. If you need to run it, update it to:
1. Write to data/curva_colored.csv
2. Use correct column names (timestamp, value)
3. Fix timezone handling and base time calculation
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from app.utils.logger import configure_logging
from backend.utils.archive import ArchiveManager

# ⚠️  DEPRECATED - Emit warning and exit
logger = logging.getLogger(__name__)
logger.error("=" * 80)
logger.error("⚠️  DEPRECATED SCRIPT CALLED: etna_loop.py")
logger.error("This script is deprecated and should not be used.")
logger.error("Use scripts/csv_updater.py or scripts/update_and_check_alerts.py instead.")
logger.error("=" * 80)
sys.exit(1)

os.makedirs("grafici", exist_ok=True)
os.makedirs("log", exist_ok=True)
os.makedirs("static", exist_ok=True)

URL_INGV = os.getenv(
    "INGV_RMS_URL",
    os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/0.png"),
)
GRAFICO_LOCALE = "grafici/etna_latest.png"
CSV_LOG = os.path.join(os.getenv("LOG_DIR", "log"), "log.csv")
configure_logging()
logger = logging.getLogger(__name__)
TOKEN_TELEGRAM = os.getenv("TELEGRAM_BOT_TOKEN", "")
DARK_THRESHOLD = int(os.getenv("INGV_DARK_THRESHOLD", "60"))
MIN_VALID_COLUMN_RATIO = 0.3
MAX_GAP = int(os.getenv("INGV_MAX_GAP", "15"))
MIN_COMPONENT_AREA = int(os.getenv("INGV_MIN_COMPONENT_AREA", "12"))

# Initialize archive manager
archive_manager = ArchiveManager()
last_archived_date = None

def scarica_grafico(url: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        with open(GRAFICO_LOCALE, 'wb') as f:
            f.write(r.content)
        return True
    return False

def crop_plot_area(img: np.ndarray) -> np.ndarray:
    height, width = img.shape[:2]
    top, bottom = 50, 20
    left, right = 100, 30
    # TODO: auto-detect plot area instead of using fixed margins.
    return img[top:height - bottom, left:width - right]

def detect_banded_background(cropped: np.ndarray) -> bool:
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    row_means = gray.mean(axis=1)
    diffs = np.abs(np.diff(row_means))
    transitions = np.sum(diffs > 4)
    return transitions > max(10, int(0.08 * len(row_means)))

def extract_green_mask(cropped: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([40, 40, 40]), np.array([80, 255, 255]))

def extract_dark_mask(cropped: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    mask = (gray < DARK_THRESHOLD).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)
    for label in range(1, num_labels):
        if stats[label, cv2.CC_STAT_AREA] >= MIN_COMPONENT_AREA:
            cleaned[labels == label] = 1
    return cleaned

def columns_to_curve(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    curve = np.full(width, np.nan)
    mask_bool = mask.astype(bool)
    for x in range(width):
        ys = np.where(mask_bool[:, x])[0]
        if ys.size > 0:
            curve[x] = float(np.median(ys))
    return curve

def count_nan_gaps(values: np.ndarray) -> int:
    nan_mask = np.isnan(values)
    if not nan_mask.any():
        return 0
    gaps = 0
    in_gap = False
    for is_nan in nan_mask:
        if is_nan and not in_gap:
            gaps += 1
            in_gap = True
        elif not is_nan:
            in_gap = False
    return gaps

def interpolate_small_gaps(values: np.ndarray) -> np.ndarray:
    series = pd.Series(values)
    return series.interpolate(limit=MAX_GAP, limit_area="inside").to_numpy()

def estrai_dati_da_png(filepath: str, source_url: str) -> tuple[pd.DataFrame, float]:
    img = cv2.imread(filepath)
    cropped = crop_plot_area(img)
    use_dark_mode = source_url.lower().endswith("0.png") or detect_banded_background(cropped)

    if use_dark_mode:
        mask = extract_dark_mask(cropped)
        mode_label = "dark"
    else:
        mask = extract_green_mask(cropped)
        mode_label = "green"

    height, width = mask.shape
    curve = columns_to_curve(mask)
    valid_columns = np.isfinite(curve).sum()
    valid_ratio = valid_columns / width if width else 0
    gap_count = count_nan_gaps(curve)
    logger.info(
        "Curve extraction mode=%s valid=%d/%d (%.1f%%) gaps=%d",
        mode_label,
        valid_columns,
        width,
        valid_ratio * 100,
        gap_count,
    )

    curve = interpolate_small_gaps(curve)

    def pixel_to_mV(y_pixel: float) -> float:
        y_norm = y_pixel / height
        log_val = 1 - y_norm * 2
        return 10 ** log_val

    def pixel_to_time(x_pixel: int) -> datetime:
        total_minutes = 4 * 24 * 60
        minutes = int((x_pixel / width) * total_minutes)
        base_time = datetime(2025, 5, 5, 23, 0)
        return base_time + timedelta(minutes=minutes)

    data = []
    for x in range(width):
        y = curve[x]
        mV = pixel_to_mV(y) if np.isfinite(y) else np.nan
        data.append((pixel_to_time(x), mV))
    return pd.DataFrame(data, columns=["timestamp", "mV"]), valid_ratio

def invia_notifica(messaggio):
    if not TOKEN_TELEGRAM:
        logger.warning("Telegram token not configured; skipping notification")
        return

    if not os.path.exists("utenti.csv"):
        return
    with open("utenti.csv", "r") as f:
        for riga in f:
            chat_id = riga.strip().split(",")[0]
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
            data = {"chat_id": chat_id, "text": messaggio}
            requests.post(url, data=data)

def aggiorna_log():
    df_new, valid_ratio = estrai_dati_da_png(GRAFICO_LOCALE, URL_INGV)
    if valid_ratio < MIN_VALID_COLUMN_RATIO and URL_INGV.lower().endswith("0.png"):
        fallback_url = URL_INGV[:-5] + "1.png"
        logger.warning(
            "Low valid ratio %.1f%%, retrying extraction with fallback URL %s",
            valid_ratio * 100,
            fallback_url,
        )
        if scarica_grafico(fallback_url):
            df_new, _ = estrai_dati_da_png(GRAFICO_LOCALE, fallback_url)
        else:
            logger.error("Fallback download failed for %s", fallback_url)

    if os.path.exists(CSV_LOG):
        df_old = pd.read_csv(CSV_LOG, parse_dates=["timestamp"])
        df = pd.concat([df_old, df_new])
    else:
        df = df_new
    df = df[df["timestamp"] >= df["timestamp"].max() - timedelta(hours=48)]
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    df.to_csv(CSV_LOG, index=False)

    # 🔔 INVIO NOTIFICA SE PICCO ALTO
    if df["mV"].max() > 5:
        invia_notifica("⚠️ Tremore elevato sull'Etna! Controlla il sito.")

def archive_daily_graph():
    """Archive the current graph if it's a new day."""
    global last_archived_date
    
    try:
        from datetime import timezone
        current_date = datetime.now(timezone.utc).date()
        
        # Check if we need to archive (new day or first run)
        if last_archived_date is None or current_date > last_archived_date:
            if os.path.exists(GRAFICO_LOCALE):
                # Read the current graph file
                with open(GRAFICO_LOCALE, 'rb') as f:
                    png_data = f.read()
                
                # Archive with the current date
                archive_date = datetime.now(timezone.utc)
                archive_manager.save_daily_graph(png_data, date=archive_date, compress=False)
                logger.info("Successfully archived graph for %s", current_date)
                
                # Update last archived date
                last_archived_date = current_date
                
                # Run cleanup to remove old archives
                deleted_count = archive_manager.cleanup_old_archives()
                if deleted_count > 0:
                    logger.info("Cleaned up %d old archive(s)", deleted_count)
            else:
                logger.warning("Cannot archive: %s does not exist", GRAFICO_LOCALE)
    except Exception as e:
        logger.error("Failed to archive daily graph: %s", e, exc_info=True)

if __name__ == "__main__":
    while True:
        logger.info("Download e aggiornamento in corso...")
        if scarica_grafico(URL_INGV):
            aggiorna_log()
            archive_daily_graph()  # Archive after successful download
            logger.info("Aggiornamento completato")
        else:
            logger.error("Errore nel download del PNG")
        logger.info("Attesa di 30 minuti prima del prossimo ciclo")
        time.sleep(1800)
