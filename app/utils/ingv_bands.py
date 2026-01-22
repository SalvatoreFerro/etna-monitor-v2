from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.utils.extract_colored import _crop_plot_area, download_png
from config import Config

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
CACHE_PATH = DATA_DIR / "ingv_bands.json"
VERIFY_INTERVAL = timedelta(hours=12)

LOG_MIN = -1.0
LOG_MAX = 1.0

FALLBACK_T2 = float(os.getenv("INGV_BAND_FALLBACK_T2", str(Config.ALERT_THRESHOLD_DEFAULT)))
FALLBACK_T1 = float(os.getenv("INGV_BAND_FALLBACK_T1", f"{FALLBACK_T2 / 2}"))
FALLBACK_T3 = float(os.getenv("INGV_BAND_FALLBACK_T3", f"{FALLBACK_T2 * 2}"))


def _get_logger(logger: logging.Logger | None = None) -> logging.Logger:
    return logger or logging.getLogger(__name__)


def detect_band_boundaries_px(img_crop: np.ndarray) -> dict[str, Any]:
    height, width = img_crop.shape[:2]
    sample_width = min(30, max(8, width // 8))
    start_x = max(0, width - sample_width)
    sample = img_crop[:, start_x:width]

    median_bgr = np.median(sample, axis=1).astype(np.uint8)
    hsv = cv2.cvtColor(median_bgr[np.newaxis, :, :], cv2.COLOR_BGR2HSV)[0]

    classes: list[str | None] = []
    for y in range(height):
        classes.append(_classify_band(hsv[y]))

    classes = _fill_missing_classes(classes)
    classes_found = []
    for label in classes:
        if label and label not in classes_found:
            classes_found.append(label)

    boundaries = {
        "green_yellow": None,
        "yellow_orange": None,
        "orange_red": None,
    }

    for y in range(1, height):
        prev = classes[y - 1]
        curr = classes[y]
        if not prev or not curr or prev == curr:
            continue
        transition = {prev, curr}
        if transition == {"GREEN", "YELLOW"} and boundaries["green_yellow"] is None:
            boundaries["green_yellow"] = y
        elif transition == {"YELLOW", "ORANGE"} and boundaries["yellow_orange"] is None:
            boundaries["yellow_orange"] = y
        elif transition in ({"ORANGE", "RED"}, {"YELLOW", "RED"}) and boundaries["orange_red"] is None:
            boundaries["orange_red"] = y

    return {
        **boundaries,
        "classes_found": classes_found,
        "method": f"median-columns-right-{sample_width}px",
    }


def pixel_y_to_mv(y_px: int, height: int, log_min: float, log_max: float) -> float:
    safe_height = max(height - 1, 1)
    y_px = max(0, min(int(y_px), safe_height))
    y_norm = 1 - (y_px / safe_height)
    log_val = log_min + y_norm * (log_max - log_min)
    mv = 10 ** log_val
    return float(max(mv, 1e-6))


def load_cached_thresholds() -> dict[str, Any] | None:
    try:
        if not CACHE_PATH.exists():
            return None
        with CACHE_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def save_cached_thresholds(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def verify_cached_bands(img_crop: np.ndarray, bands_px: dict[str, int | None]) -> dict[str, Any]:
    height, width = img_crop.shape[:2]
    sample_width = min(5, max(3, width // 20))
    start_x = max(0, width - sample_width)
    sample = img_crop[:, start_x:width]
    median_bgr = np.median(sample, axis=1).astype(np.uint8)
    hsv = cv2.cvtColor(median_bgr[np.newaxis, :, :], cv2.COLOR_BGR2HSV)[0]

    checks = []
    status = "ok"
    notes = []

    def _check_boundary(key: str, expected: set[str]) -> None:
        nonlocal status
        y_boundary = bands_px.get(key)
        if y_boundary is None:
            return
        y_above = max(0, y_boundary - 2)
        y_below = min(height - 1, y_boundary + 2)
        class_above = _classify_band(hsv[y_above])
        class_below = _classify_band(hsv[y_below])
        checks.append((key, class_above, class_below))
        if not class_above or not class_below:
            status = "warning" if status == "ok" else status
            notes.append(f"{key}: colore non riconosciuto")
            return
        if {class_above, class_below} != expected:
            status = "failed"
            notes.append(f"{key}: atteso {sorted(expected)}, trovato {class_above}/{class_below}")

    _check_boundary("green_yellow", {"GREEN", "YELLOW"})
    _check_boundary("yellow_orange", {"YELLOW", "ORANGE"})
    if bands_px.get("yellow_orange") is None:
        _check_boundary("orange_red", {"YELLOW", "RED"})
    else:
        _check_boundary("orange_red", {"ORANGE", "RED"})

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notes": "; ".join(notes) if notes else "ok",
        "checks": checks,
    }


def get_ingv_band_thresholds(logger: logging.Logger | None = None) -> dict[str, Any]:
    logger = _get_logger(logger)
    cached = load_cached_thresholds()
    now = datetime.now(timezone.utc)

    if cached and _thresholds_valid(cached):
        cached = _maybe_verify_cached(cached, logger, now)
        return _normalize_cached_result(cached)

    detected = _detect_thresholds(logger)
    if detected:
        save_cached_thresholds(detected)
        return _normalize_cached_result(detected)

    fallback = _fallback_thresholds()
    logger.warning("[INGV_BANDS] Using fallback thresholds t1=%.3f t2=%.3f t3=%.3f", *fallback)
    return {
        "thresholds_mv": {"t1": fallback[0], "t2": fallback[1], "t3": fallback[2]},
        "bands_px": {},
        "detected_classes": [],
        "plot_area": {},
        "updated_at": None,
        "verification": {"status": "failed", "checked_at": None, "notes": "fallback_static"},
        "source": "fallback_static",
    }


def _detect_thresholds(logger: logging.Logger) -> dict[str, Any] | None:
    colored_url = (os.getenv("INGV_COLORED_URL") or "").strip()
    if not colored_url:
        logger.warning("[INGV_BANDS] INGV_COLORED_URL not configured")
        return None

    try:
        png_path = download_png(colored_url)
    except Exception as exc:
        logger.warning("[INGV_BANDS] PNG download failed: %s", exc)
        return None

    image = cv2.imread(str(png_path))
    if image is None:
        logger.warning("[INGV_BANDS] Failed to read PNG %s", png_path)
        return None

    cropped, offsets = _crop_plot_area(image)
    bands_px = detect_band_boundaries_px(cropped)
    thresholds = _build_thresholds_from_bands(bands_px, cropped.shape[0])
    if not thresholds:
        logger.warning("[INGV_BANDS] Failed to build thresholds from bands")
        return None

    verification = verify_cached_bands(cropped, bands_px)
    payload = {
        "plot_area": {
            "height": int(cropped.shape[0]),
            "width": int(cropped.shape[1]),
            "crop": offsets,
        },
        "bands_px": {k: bands_px.get(k) for k in ("green_yellow", "yellow_orange", "orange_red")},
        "thresholds_mv": thresholds,
        "detected_classes": bands_px.get("classes_found", []),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "verification": verification,
        "source": "ingv_0png_bands",
    }
    return payload


def _maybe_verify_cached(cached: dict[str, Any], logger: logging.Logger, now: datetime) -> dict[str, Any]:
    verification = cached.get("verification") or {}
    checked_at = verification.get("checked_at")
    if checked_at:
        try:
            checked_dt = datetime.fromisoformat(checked_at)
        except ValueError:
            checked_dt = None
    else:
        checked_dt = None

    if checked_dt and now - checked_dt < VERIFY_INTERVAL:
        return cached

    colored_url = (os.getenv("INGV_COLORED_URL") or "").strip()
    if not colored_url:
        return cached

    try:
        png_path = download_png(colored_url)
        image = cv2.imread(str(png_path))
    except Exception as exc:
        logger.warning("[INGV_BANDS] verification download failed: %s", exc)
        return cached

    if image is None:
        logger.warning("[INGV_BANDS] verification image missing")
        return cached

    cropped, _ = _crop_plot_area(image)
    bands_px = cached.get("bands_px") or {}
    verification = verify_cached_bands(cropped, bands_px)

    cached["verification"] = verification
    save_cached_thresholds(cached)

    if verification.get("status") == "ok":
        return cached

    logger.warning("[INGV_BANDS] cached bands verification failed: %s", verification.get("notes"))
    redetected = _detect_thresholds(logger)
    if not redetected:
        cached["verification"]["status"] = "warning"
        cached["verification"]["notes"] = (
            (cached["verification"].get("notes") or "") + "; detect_failed"
        ).strip("; ")
        save_cached_thresholds(cached)
        return cached

    if _thresholds_shifted(cached, redetected):
        cached["verification"]["status"] = "warning"
        cached["verification"]["notes"] = "detected_shift_too_large"
        save_cached_thresholds(cached)
        return cached

    save_cached_thresholds(redetected)
    return redetected


def _thresholds_valid(payload: dict[str, Any]) -> bool:
    thresholds = payload.get("thresholds_mv") or {}
    t1 = thresholds.get("t1")
    t2 = thresholds.get("t2")
    t3 = thresholds.get("t3")
    return _validate_thresholds(t1, t2, t3)


def _validate_thresholds(t1: float | None, t2: float | None, t3: float | None) -> bool:
    if t1 is None or t2 is None or t3 is None:
        return False
    if not all(np.isfinite([t1, t2, t3])):
        return False
    if t1 <= 0 or t2 <= 0 or t3 <= 0:
        return False
    return t1 < t2 <= t3


def _build_thresholds_from_bands(bands_px: dict[str, Any], height: int) -> dict[str, float] | None:
    y1 = bands_px.get("green_yellow")
    y2 = bands_px.get("yellow_orange")
    y3 = bands_px.get("orange_red")
    if y1 is None:
        return None
    if y2 is None and y3 is None:
        return None

    if y2 is None:
        t1 = pixel_y_to_mv(y1, height, LOG_MIN, LOG_MAX)
        t2 = pixel_y_to_mv(y3, height, LOG_MIN, LOG_MAX) if y3 is not None else t1
        t3 = t2
    elif y3 is None:
        t1 = pixel_y_to_mv(y1, height, LOG_MIN, LOG_MAX)
        t2 = pixel_y_to_mv(y2, height, LOG_MIN, LOG_MAX)
        t3 = t2
    else:
        t1 = pixel_y_to_mv(y1, height, LOG_MIN, LOG_MAX)
        t2 = pixel_y_to_mv(y2, height, LOG_MIN, LOG_MAX)
        t3 = pixel_y_to_mv(y3, height, LOG_MIN, LOG_MAX)

    if not _validate_thresholds(t1, t2, t3):
        return None
    return {"t1": float(t1), "t2": float(t2), "t3": float(t3)}


def _thresholds_shifted(cached: dict[str, Any], redetected: dict[str, Any]) -> bool:
    prev = cached.get("thresholds_mv") or {}
    new = redetected.get("thresholds_mv") or {}
    for key in ("t1", "t2", "t3"):
        prev_val = prev.get(key)
        new_val = new.get(key)
        if prev_val is None or new_val is None or prev_val == 0:
            continue
        if abs(new_val - prev_val) / prev_val > 0.6:
            return True
    return False


def _fallback_thresholds() -> tuple[float, float, float]:
    t1 = max(FALLBACK_T1, 1e-3)
    t2 = max(FALLBACK_T2, t1 + 1e-3)
    t3 = max(FALLBACK_T3, t2)
    if t1 >= t2:
        t2 = t1 + 0.1
    if t3 < t2:
        t3 = t2
    return float(t1), float(t2), float(t3)


def _normalize_cached_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "thresholds_mv": payload.get("thresholds_mv") or {},
        "bands_px": payload.get("bands_px") or {},
        "detected_classes": payload.get("detected_classes") or [],
        "plot_area": payload.get("plot_area") or {},
        "updated_at": payload.get("updated_at"),
        "verification": payload.get("verification") or {},
        "source": "ingv_0png_bands_cache",
    }


def _fill_missing_classes(classes: list[str | None]) -> list[str | None]:
    filled = classes[:]
    last = None
    for idx, value in enumerate(filled):
        if value is None and last is not None:
            filled[idx] = last
        else:
            last = value
    if filled and filled[0] is None:
        first = next((val for val in filled if val is not None), None)
        if first is not None:
            filled = [first if val is None else val for val in filled]
    return filled


def _classify_band(hsv_pixel: np.ndarray) -> str | None:
    h, s, v = (int(hsv_pixel[0]), int(hsv_pixel[1]), int(hsv_pixel[2]))
    if s < 40 or v < 40:
        return None
    if h <= 10 or h >= 170:
        return "RED"
    if 10 < h <= 20:
        return "ORANGE"
    if 20 < h <= 35:
        return "YELLOW"
    if 35 < h <= 85:
        return "GREEN"
    return None
