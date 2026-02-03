import csv
import hashlib
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

from backend.utils.extract_colored import download_png as download_colored_png
from backend.utils.extract_colored import extract_series_from_colored
from backend.utils.extract_png import download_png as download_white_png
from backend.utils.extract_png import clean_and_save_data, process_png_bytes_to_csv
from app.services.runlog_service import log_cron_run_external


DEFAULT_INTERVAL_SECONDS = 3600
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30
DEFAULT_STALE_THRESHOLD = 8
DEFAULT_PIPELINE_MODE = "colored"

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


def ensure_utc_aware(dt: datetime | None) -> datetime | None:
    """
    Normalize a datetime to UTC timezone-aware format.
    
    - If None, returns None
    - If naive (no tzinfo), assumes UTC and adds tzinfo
    - If aware, converts to UTC
    
    Logs a warning when converting naive datetimes to track the origin.
    """
    if dt is None:
        return None
    
    if dt.tzinfo is None:
        log.warning(
            "Converting naive datetime to UTC-aware: %s. "
            "This may indicate timestamps from legacy CSV data.",
            dt.isoformat()
        )
        return dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(timezone.utc)


def _resolve_hash_state_path() -> Path:
    data_dir = os.getenv("DATA_DIR", "data")
    return Path(os.getenv("INGV_WHITE_HASH_STATE", os.path.join(data_dir, "ingv_white_hash.json")))


def _load_hash_state() -> dict:
    path = _resolve_hash_state_path()
    if not path.exists():
        return {"hash": None, "count": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"hash": None, "count": 0}


def _store_hash_state(state: dict) -> None:
    path = _resolve_hash_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _update_hash_state(current_hash: str, threshold: int) -> tuple[int, bool]:
    state = _load_hash_state()
    last_hash = state.get("hash")
    count = int(state.get("count", 0))
    if current_hash == last_hash:
        count += 1
    else:
        count = 1
    state = {
        "hash": current_hash,
        "count": count,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _store_hash_state(state)
    return count, count >= threshold


def _write_csv_safely(rows: list, output_path: Path) -> dict:
    temp_path = output_path.with_suffix(".tmp")
    _, cleaned_rows = clean_and_save_data(rows, str(temp_path))
    if not cleaned_rows:
        temp_path.unlink(missing_ok=True)
        raise ValueError("Nessun punto valido estratto; CSV non aggiornato.")
    temp_path.replace(output_path)
    return {
        "rows": len(cleaned_rows),
        "first_ts": cleaned_rows[0]["timestamp"] if cleaned_rows else None,
        "last_ts": cleaned_rows[-1]["timestamp"] if cleaned_rows else None,
        "output_path": str(output_path),
        "cleaned_rows": cleaned_rows,
    }


def _process_white_png(png_bytes: bytes, reference_time: datetime, csv_path: Path) -> dict:
    temp_path = csv_path.with_suffix(".tmp")
    result = process_png_bytes_to_csv(png_bytes, reference_time, str(temp_path))
    if not result.get("rows"):
        temp_path.unlink(missing_ok=True)
        raise ValueError("Estratti 0 punti dal PNG bianco.")
    temp_path.replace(csv_path)
    result["output_path"] = str(csv_path)
    return result


def _process_colored_png(path_png: Path, csv_path: Path) -> dict:
    timestamps, values, debug_paths = extract_series_from_colored(path_png)
    rows = [
        {
            "timestamp": ts,
            "value": value,
            "value_max": value,
            "value_avg": value,
        }
        for ts, value in zip(timestamps, values)
    ]
    result = _write_csv_safely(rows, csv_path)
    result["debug_paths"] = debug_paths
    return result


def _resolve_pipeline_mode() -> str:
    mode = (os.getenv("CURVA_PIPELINE_MODE") or DEFAULT_PIPELINE_MODE).strip().lower()
    return mode if mode in {"colored", "white"} else DEFAULT_PIPELINE_MODE


def update_with_retries(ingv_url: str, colored_url: str | None, csv_path: Path) -> dict:
    last_error = None
    last_exception = None
    last_traceback = None
    started_at = perf_counter()
    pipeline_id = (os.getenv("CRON_PIPELINE_ID") or "").strip() or None
    previous_last_ts = _read_csv_last_timestamp(csv_path)
    stale_threshold = int(os.getenv("INGV_WHITE_STALE_THRESHOLD", str(DEFAULT_STALE_THRESHOLD)))
    pipeline_mode = _resolve_pipeline_mode()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if pipeline_mode == "white":
                png_bytes, reference_time = download_white_png(ingv_url)
                png_hash = hashlib.sha256(png_bytes).hexdigest()
                stale_count, is_stale = _update_hash_state(png_hash, stale_threshold)

                if is_stale:
                    if not colored_url:
                        raise ValueError("Sorgente bianca stale e INGV_COLORED_URL non configurato.")
                    colored_path = download_colored_png(colored_url)
                    result = _process_colored_png(colored_path, csv_path)
                    result["source"] = "colored"
                    result["stale_count"] = stale_count
                    log.info(
                        "[CSV] fallback colored source=colored stale_count=%s output=%s",
                        stale_count,
                        result.get("output_path"),
                    )
                else:
                    result = _process_white_png(png_bytes, reference_time, csv_path)
                    result["source"] = "white"
                    result["stale_count"] = stale_count
                    log.info(
                        "[CSV] update source=white stale_count=%s rows=%s output=%s",
                        stale_count,
                        result.get("rows"),
                        result.get("output_path"),
                    )
            else:
                if not colored_url:
                    raise ValueError("INGV_COLORED_URL non configurato.")
                colored_path = download_colored_png(colored_url)
                result = _process_colored_png(colored_path, csv_path)
                result["source"] = "colored"
                result["stale_count"] = None
                log.info(
                    "[CSV] update source=colored rows=%s output=%s",
                    result.get("rows"),
                    result.get("output_path"),
                )
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
        try:
            stat = csv_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            mtime = None
        max_ts = last_ts.isoformat() if last_ts else None
        log.info("writing CSV to %s | mtime=%s | max_ts=%s", csv_path, mtime, max_ts)
        updated = False
        # Normalize both timestamps to UTC-aware for safe comparison
        last_ts_normalized = ensure_utc_aware(last_ts)
        previous_last_ts_normalized = ensure_utc_aware(previous_last_ts)
        if last_ts_normalized and (previous_last_ts_normalized is None or last_ts_normalized > previous_last_ts_normalized):
            updated = True
        _record_csv_update(result.get("rows"), last_ts)
        _log_cron_run(
            csv_path,
            ok=True,
            reason="completed",
            duration_ms=(perf_counter() - started_at) * 1000,
            pipeline_id=pipeline_id,
            payload={
                "ingv_url": ingv_url,
                "ingv_colored_url": colored_url,
                "attempts": attempt,
                "rows": result.get("rows"),
                "first_ts": result.get("first_ts"),
                "last_ts": result.get("last_ts"),
                "start_ref": result.get("start_time"),
                "end_ref": result.get("end_time"),
                "interval_minutes": result.get("interval_minutes"),
                "pixel_columns": result.get("pixel_columns"),
                "output_path": result.get("output_path"),
                "source": result.get("source"),
                "stale_count": result.get("stale_count"),
            },
        )
        return {
            "ok": True,
            "updated": updated,
            "last_ts": last_ts,
        }

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
            "ingv_colored_url": colored_url,
            "attempts": MAX_RETRIES,
            "error": last_error or "update_failed",
        },
    )
    return {
        "ok": False,
        "updated": False,
        "last_ts": last_ts,
    }


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
    colored_url = (os.getenv("INGV_COLORED_URL") or "").strip() or None
    csv_path = Path(os.getenv("CURVA_CSV_PATH", "data/curva_colored.csv"))
    interval_seconds = int(os.getenv("CSV_UPDATE_INTERVAL", str(DEFAULT_INTERVAL_SECONDS)))
    run_once = os.getenv("RUN_ONCE", "").lower() in {"1", "true", "yes"}

    while True:
        result = update_with_retries(ingv_url, colored_url, csv_path)
        if not result.get("ok"):
            sys.exit(1)
        if run_once:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
