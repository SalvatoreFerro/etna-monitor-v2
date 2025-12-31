import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

from backend.utils.extract_png import process_png_to_csv
from app.utils.logger import configure_logging, get_logger


DEFAULT_INTERVAL_SECONDS = 3600
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30


def _resolve_csv_metrics_path() -> Path:
    data_dir = os.getenv("DATA_DIR", "data")
    return Path(os.getenv("CSV_METRICS_PATH", os.path.join(data_dir, "csv_metrics.json")))


def _record_csv_update(
    rows: int | None,
    last_timestamp: datetime | None,
    *,
    error_message: str | None = None,
) -> None:
    payload = {
        "last_update_at": datetime.utcnow().isoformat(),
        "row_count": rows,
        "last_data_timestamp": last_timestamp.isoformat() if last_timestamp else None,
        "last_error": error_message,
    }
    path = _resolve_csv_metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_csv_last_timestamp(csv_path: Path) -> datetime | None:
    if not csv_path.exists():
        return None

    try:
        with csv_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            last_ts = None
            for row in reader:
                ts = row.get("timestamp")
                if not ts:
                    continue
                candidate = _parse_iso_timestamp(ts)
                if candidate is not None:
                    last_ts = candidate
            return last_ts
    except Exception:
        return None


def _parse_iso_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


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
        _record_csv_update(result.get("rows"), last_ts)
        return

    last_ts = _read_csv_last_timestamp(csv_path)
    _record_csv_update(None, last_ts, error_message=last_error or "update_failed")


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
