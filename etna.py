import os
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta

URL_INGV = "https://www.ct.ingv.it/RMS_Etna/2.png"
GRAFICO_LOCALE = "grafici/etna_latest.png"
CSV_LOG = os.path.join(os.getenv("LOG_DIR", "log"), "log.csv")
PLOT_IMG = "static/plot.png"

def scarica_grafico():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    r = requests.get(URL_INGV, headers=headers)
    if r.status_code == 200:
        with open(GRAFICO_LOCALE, 'wb') as f:
            f.write(r.content)
        return GRAFICO_LOCALE
    return None

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

def aggiorna_log_e_plot():
    df_new = estrai_dati_da_png(GRAFICO_LOCALE)
    if os.path.exists(CSV_LOG):
        df_old = pd.read_csv(CSV_LOG, parse_dates=["timestamp"])
        df = pd.concat([df_old, df_new])
    else:
        df = df_new
    df = df[df["timestamp"] >= df["timestamp"].max() - timedelta(hours=48)]
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    df.to_csv(CSV_LOG, index=False)

    plt.figure(figsize=(14, 5))
    plt.plot(df["timestamp"], df["mV"], color='green')
    plt.yscale("log")
    plt.xlabel("Data e ora")
    plt.ylabel("Tremore (mV)")
    plt.title("Tremore Etna (ultime 48 ore)")
    plt.grid(True)
    plt.tight_layout()
    plt.xticks(rotation=45)
    plt.savefig(PLOT_IMG)
    plt.close()

if __name__ == "__main__":
    if scarica_grafico():
        aggiorna_log_e_plot()
        print("✅ Grafico aggiornato.")
    else:
        print("❌ Errore nel download PNG.")
