import os
import time
from datetime import datetime
from pathlib import Path

from backend.utils.extract_png import process_png_to_csv
from app.utils.logger import configure_logging, get_logger
from app.utils.metrics import record_csv_update


DEFAULT_INTERVAL_SECONDS = 3600
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30


def _read_csv_last_timestamp(csv_path: Path) -> datetime | None:
    try:
        import pandas as pd
    except ImportError:
        return None

    if not csv_path.exists():
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    if "timestamp" not in df.columns or df.empty:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    if df.empty:
        return None
    return df["timestamp"].iloc[-1].to_pydatetime()


def run_update(ingv_url: str, csv_path: Path) -> dict:
    logger = get_logger("csv_updater")
    result = process_png_to_csv(ingv_url, str(csv_path))
    logger.info(
        "[CSV] update complete rows=%s last_ts=%s output=%s",
        result.get("rows"),
        result.get("last_ts"),
        result.get("output_path"),
    )
    return result


def update_with_retries(ingv_url: str, csv_path: Path) -> None:
    logger = get_logger("csv_updater")
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = run_update(ingv_url, csv_path)
        except Exception as exc:
            last_error = str(exc)
            logger.exception("[CSV] update failed (attempt %s/%s)", attempt, MAX_RETRIES)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue

        last_ts = _read_csv_last_timestamp(csv_path)
        record_csv_update(result.get("rows"), last_ts)
        return

    last_ts = _read_csv_last_timestamp(csv_path)
    record_csv_update(None, last_ts, error_message=last_error or "update_failed")


def main() -> None:
    log_dir = os.getenv("LOG_DIR")
    configure_logging(log_dir)

    ingv_url = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    csv_path = Path(os.getenv("CSV_PATH", "/data/curva.csv"))
    interval_seconds = int(os.getenv("CSV_UPDATE_INTERVAL", str(DEFAULT_INTERVAL_SECONDS)))
    run_once = os.getenv("RUN_ONCE", "").lower() in {"1", "true", "yes"}

    while True:
        update_with_retries(ingv_url, csv_path)
        if run_once:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
