import logging
import os
import time
from datetime import datetime, timedelta

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from app.utils.logger import configure_logging
from backend.utils.archive import ArchiveManager

os.makedirs("grafici", exist_ok=True)
os.makedirs("log", exist_ok=True)
os.makedirs("static", exist_ok=True)

URL_INGV = "https://www.ct.ingv.it/RMS_Etna/2.png"
GRAFICO_LOCALE = "grafici/etna_latest.png"
CSV_LOG = os.path.join(os.getenv("LOG_DIR", "log"), "log.csv")
configure_logging()
logger = logging.getLogger(__name__)
TOKEN_TELEGRAM = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Initialize archive manager
archive_manager = ArchiveManager()
last_archived_date = None

def scarica_grafico():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.get(URL_INGV, headers=headers)
    if r.status_code == 200:
        with open(GRAFICO_LOCALE, 'wb') as f:
            f.write(r.content)
        return True
    return False

def estrai_dati_da_png(filepath):
    img = cv2.imread(filepath)
    cropped = img[50:-20, 100:-30]
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([40, 40, 40]), np.array([80, 255, 255]))
    height, width = mask.shape

    def pixel_to_mV(y_pixel):
        y_norm = y_pixel / height
        log_val = 1 - y_norm * 2
        return 10 ** log_val

    def pixel_to_time(x_pixel):
        total_minutes = 4 * 24 * 60
        minutes = int((x_pixel / width) * total_minutes)
        base_time = datetime(2025, 5, 5, 23, 0)
        return base_time + timedelta(minutes=minutes)

    data = []
    for x in range(width):
        col = mask[:, x]
        y_vals = np.where(col == 255)[0]
        if len(y_vals) > 0:
            y = y_vals[-1]
            data.append((pixel_to_time(x), pixel_to_mV(y)))
    return pd.DataFrame(data, columns=["timestamp", "mV"])

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
    df_new = estrai_dati_da_png(GRAFICO_LOCALE)
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
        current_date = datetime.now().date()
        
        # Check if we need to archive (new day or first run)
        if last_archived_date is None or current_date > last_archived_date:
            if os.path.exists(GRAFICO_LOCALE):
                # Read the current graph file
                with open(GRAFICO_LOCALE, 'rb') as f:
                    png_data = f.read()
                
                # Archive with the current date
                archive_date = datetime.now()
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
        if scarica_grafico():
            aggiorna_log()
            archive_daily_graph()  # Archive after successful download
            logger.info("Aggiornamento completato")
        else:
            logger.error("Errore nel download del PNG")
        logger.info("Attesa di 30 minuti prima del prossimo ciclo")
        time.sleep(1800)
