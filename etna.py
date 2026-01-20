import os
import cv2
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta

URL_INGV = os.getenv(
    "INGV_RMS_URL",
    os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/0.png"),
)
GRAFICO_LOCALE = "grafici/etna_latest.png"
CSV_LOG = os.path.join(os.getenv("LOG_DIR", "log"), "log.csv")
PLOT_IMG = "static/plot.png"
DARK_THRESHOLD = int(os.getenv("INGV_DARK_THRESHOLD", "60"))
MIN_VALID_COLUMN_RATIO = 0.3
MAX_GAP = int(os.getenv("INGV_MAX_GAP", "15"))
MIN_COMPONENT_AREA = int(os.getenv("INGV_MIN_COMPONENT_AREA", "12"))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scarica_grafico(url: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        with open(GRAFICO_LOCALE, 'wb') as f:
            f.write(r.content)
        return GRAFICO_LOCALE
    return None

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
    else:
        mask = extract_green_mask(cropped)

    height, width = mask.shape
    curve = columns_to_curve(mask)
    valid_columns = np.isfinite(curve).sum()
    valid_ratio = valid_columns / width if width else 0
    gap_count = count_nan_gaps(curve)
    logger.info(
        "Curve extraction valid=%d/%d (%.1f%%) gaps=%d",
        valid_columns,
        width,
        valid_ratio * 100,
        gap_count,
    )
    curve = interpolate_small_gaps(curve)

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
        y = curve[x]
        mV = pixel_to_mV(y) if np.isfinite(y) else np.nan
        data.append((pixel_to_time(x), mV))
    return pd.DataFrame(data, columns=["timestamp", "mV"]), valid_ratio

def aggiorna_log_e_plot():
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
    if scarica_grafico(URL_INGV):
        aggiorna_log_e_plot()
        print("✅ Grafico aggiornato.")
    else:
        print("❌ Errore nel download PNG.")
