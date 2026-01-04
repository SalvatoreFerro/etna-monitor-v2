import csv
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.utils.extract_png import process_png_to_csv
from app.services.runlog_service import log_cron_run_external


DEFAULT_INTERVAL_SECONDS = 3600
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30

log = logging.getLogger("csv_updater")


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
    result = process_png_to_csv(ingv_url, str(csv_path))
    log.info(
        "[CSV] update complete rows=%s last_ts=%s output=%s",
        result.get("rows"),
        result.get("last_ts"),
        result.get("output_path"),
    )
    return result


def update_with_retries(ingv_url: str, csv_path: Path) -> bool:
    last_error = None
    last_exception = None
    last_traceback = None
    started_at = perf_counter()
    pipeline_id = (os.getenv("CRON_PIPELINE_ID") or "").strip() or None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = run_update(ingv_url, csv_path)
            last_exception = None
        except Exception as exc:
            last_error = str(exc)
            last_exception = exc
            last_traceback = traceback.format_exc()
            log.exception("[CSV] update failed (attempt %s/%s)", attempt, MAX_RETRIES)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue

        last_ts = _read_csv_last_timestamp(csv_path)
        _record_csv_update(result.get("rows"), last_ts)
        _log_cron_run(
            csv_path,
            ok=True,
            reason="completed",
            duration_ms=(perf_counter() - started_at) * 1000,
            pipeline_id=pipeline_id,
            payload={
                "ingv_url": ingv_url,
                "attempts": attempt,
                "rows": result.get("rows"),
                "first_ts": result.get("first_ts"),
                "last_ts": result.get("last_ts"),
                "start_ref": result.get("start_time"),
                "end_ref": result.get("end_time"),
                "interval_minutes": result.get("interval_minutes"),
                "pixel_columns": result.get("pixel_columns"),
                "output_path": result.get("output_path"),
            },
        )
        return True

    last_ts = _read_csv_last_timestamp(csv_path)
    _record_csv_update(None, last_ts, error_message=last_error or "update_failed")
    log.error("[CSV] update failed after %s attempts", MAX_RETRIES)
    _log_cron_run(
        csv_path,
        ok=False,
        reason="update_failed",
        duration_ms=(perf_counter() - started_at) * 1000,
        pipeline_id=pipeline_id,
        error=last_exception,
        error_traceback=last_traceback,
        payload={
            "ingv_url": ingv_url,
            "attempts": MAX_RETRIES,
            "error": last_error or "update_failed",
        },
    )
    return False


def _log_cron_run(
    csv_path: Path,
    *,
    ok: bool,
    reason: str,
    duration_ms: float,
    pipeline_id: str | None,
    payload: dict | None = None,
    error: Exception | None = None,
    error_traceback: str | None = None,
) -> None:
    try:
        stat = csv_path.stat() if csv_path.exists() else None
    except OSError:
        stat = None
    csv_mtime = (
        datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc) if stat else None
    )
    csv_size_bytes = stat.st_size if stat else None
    last_point_ts = None
    if payload and payload.get("last_ts"):
        last_point_ts = _parse_iso_timestamp(payload.get("last_ts", ""))

    finished_at = datetime.now(timezone.utc)
    started_at = finished_at - timedelta(milliseconds=duration_ms)
    cron_payload = {
        "pipeline_id": pipeline_id,
        "job_type": "csv_updater",
        "ok": bool(ok),
        "status": "success" if ok else "error",
        "reason": reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round(duration_ms, 1),
        "csv_path": str(csv_path),
        "csv_mtime": csv_mtime,
        "csv_size_bytes": csv_size_bytes,
        "last_point_ts": last_point_ts,
        "payload": payload,
        "diagnostic_json": payload,
        "error_type": type(error).__name__ if error else None,
        "error_message": str(error) if error else None,
        "traceback": error_traceback,
    }

    try:
        log_cron_run_external(cron_payload)
    except Exception:  # pragma: no cover - defensive logging
        log.exception("[CSV] Failed to persist cron run log")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ingv_url = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    csv_path = Path(os.getenv("CSV_PATH", "/data/curva.csv"))
    interval_seconds = int(os.getenv("CSV_UPDATE_INTERVAL", str(DEFAULT_INTERVAL_SECONDS)))
    run_once = os.getenv("RUN_ONCE", "").lower() in {"1", "true", "yes"}

    while True:
        success = update_with_retries(ingv_url, csv_path)
        if not success:
            sys.exit(1)
        if run_once:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
