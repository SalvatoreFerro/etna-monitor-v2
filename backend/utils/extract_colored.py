import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import requests

from backend.utils.time import to_iso_utc


EXTRACTION_DURATION = timedelta(days=7)

EDGE_MARGIN_PX = 6
BBOX_PADDING_PX = 6
BBOX_DARK_RATIO = 0.35
BBOX_FALLBACK_PCT = {
    "top": 0.12,
    "bottom": 0.08,
    "left": 0.12,
    "right": 0.05,
}

MAX_DELTA_Y = 18
HAMPEL_WINDOW = 7
HAMPEL_SIGMA = 3.0

NEIGHBORHOOD_RANGE = 2
NEIGHBORHOOD_EXTENDED_RANGE = 3

VERTICAL_OPEN_KERNEL = (1, 5)
NOISE_OPEN_KERNEL = (3, 3)
NOISE_CLOSE_KERNEL = (3, 3)
MIN_COMPONENT_AREA = 3
MIN_VALID_COLUMN_PCT = 20.0
VERTICAL_LINE_PIXEL_RATIO = 0.02


logger = logging.getLogger(__name__)


def process_colored_png_to_csv(url: str, output_path: str | Path | None = None) -> dict:
    if not url:
        raise ValueError("INGV_COLORED_URL not configured")
    png_path = download_png(url)
    timestamps, values, _ = extract_series_from_colored(png_path)
    if not timestamps or not values:
        raise ValueError("No data extracted from colored PNG")

    output_target = Path(output_path) if output_path else Path("data") / "curva_colored.csv"
    output_target.parent.mkdir(parents=True, exist_ok=True)

    with output_target.open("w", encoding="utf-8", newline="") as handle:
        handle.write("timestamp,value\n")
        for ts, value in zip(timestamps, values):
            iso_ts = to_iso_utc(ts)
            if iso_ts is None:
                continue
            handle.write(f"{iso_ts},{value}\n")

    first_ts = to_iso_utc(timestamps[0]) if timestamps else None
    last_ts = to_iso_utc(timestamps[-1]) if timestamps else None
    return {
        "output_path": str(output_target),
        "rows": len(timestamps),
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def download_png(url: str) -> Path:
    """Download PNG from INGV colored URL and persist it locally."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data_dir = Path(os.getenv("DATA_DIR", "data"))
    target_dir = Path(os.getenv("INGV_COLORED_DIR", data_dir / "ingv_colored"))
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"colored_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}.png"
    path = target_dir / filename
    path.write_bytes(response.content)
    return path


def extract_series_from_colored(path_png: str | Path):
    """Extract (timestamp, mV) series from the colored PNG."""
    image_path = Path(path_png)
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Impossibile leggere PNG colorato: {image_path}")

    cropped, offsets, bbox = _crop_plot_area(image)
    ys_px, mask_raw, mask_clean, reasons, border_components = _extract_curve_points(cropped)

    xs_px = list(range(mask_clean.shape[1]))
    ys_px = _apply_hampel_filter(ys_px, window=HAMPEL_WINDOW, sigma=HAMPEL_SIGMA)

    valid_columns = sum(1 for y in ys_px if y is not None)
    valid_ratio = (valid_columns / len(ys_px) * 100) if ys_px else 0.0
    missing_tail = _count_missing_tail_columns(ys_px, tail_columns=50)
    tail_reasons = _count_tail_reasons(reasons, tail_columns=50)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - EXTRACTION_DURATION
    duration_seconds = EXTRACTION_DURATION.total_seconds()
    steps = max(mask_clean.shape[1] - 1, 1)
    seconds_per_pixel = duration_seconds / steps

    timestamps = []
    values = []
    for x, y in zip(xs_px, ys_px):
        if y is None:
            continue
        timestamp = start_time + timedelta(seconds=seconds_per_pixel * x)
        timestamps.append(timestamp)
        values.append(_pixel_to_mv(y, mask_clean.shape[0]))

    debug_paths = _write_debug_artifacts(
        cropped,
        mask_raw,
        mask_clean,
        xs_px,
        ys_px,
    )
    logger.info(
        (
            "[INGV COLORED] valid_columns=%.1f%% (%s/%s) series_len=%s start_ref=%s end_ref=%s crop=%s"
        ),
        valid_ratio,
        valid_columns,
        len(ys_px),
        len(values),
        start_time.isoformat(),
        end_time.isoformat(),
        offsets,
    )
    logger.info(
        (
            "[INGV COLORED][debug summary] bbox=%s columns_with_points=%.1f%% "
            "tail_empty=%s tail_empty_reasons=%s border_components_removed=%s"
        ),
        bbox,
        valid_ratio,
        missing_tail,
        tail_reasons,
        border_components,
    )

    return timestamps, values, debug_paths


def _crop_plot_area(image: np.ndarray):
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bbox = _detect_plot_bbox(gray)
    if bbox is None:
        bbox = _fallback_bbox_from_pct(height, width)

    x_min, y_min, x_max, y_max = bbox
    cropped = image[y_min:y_max, x_min:x_max]
    logger.info(
        "[INGV COLORED] plot_bbox x_min=%s x_max=%s y_min=%s y_max=%s crop_size=%sx%s",
        x_min,
        x_max - 1,
        y_min,
        y_max - 1,
        cropped.shape[1],
        cropped.shape[0],
    )
    offsets = {
        "top": y_min,
        "bottom": height - y_max,
        "left": x_min,
        "right": width - x_max,
    }
    return cropped, offsets, bbox


def _detect_plot_bbox(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    height, width = gray.shape
    dark_mask = gray < 80
    if not np.any(dark_mask):
        return None

    row_ratio = dark_mask.mean(axis=1)
    col_ratio = dark_mask.mean(axis=0)
    rows = np.where(row_ratio >= BBOX_DARK_RATIO)[0]
    cols = np.where(col_ratio >= BBOX_DARK_RATIO)[0]
    if rows.size < 2 or cols.size < 2:
        return None

    top = int(rows[0])
    bottom = int(rows[-1])
    left = int(cols[0])
    right = int(cols[-1])

    top = min(max(top + BBOX_PADDING_PX, 0), height - 2)
    bottom = min(max(bottom - BBOX_PADDING_PX, top + 1), height - 1)
    left = min(max(left + BBOX_PADDING_PX, 0), width - 2)
    right = min(max(right - BBOX_PADDING_PX, left + 1), width - 1)

    return left, top, right + 1, bottom + 1


def _fallback_bbox_from_pct(height: int, width: int) -> tuple[int, int, int, int]:
    top = int(height * BBOX_FALLBACK_PCT["top"])
    bottom = int(height * (1 - BBOX_FALLBACK_PCT["bottom"]))
    left = int(width * BBOX_FALLBACK_PCT["left"])
    right = int(width * (1 - BBOX_FALLBACK_PCT["right"]))
    top = min(max(top, 0), height - 2)
    bottom = min(max(bottom, top + 1), height - 1)
    left = min(max(left, 0), width - 2)
    right = min(max(right, left + 1), width - 1)
    return left, top, right + 1, bottom + 1


def _extract_curve_points(
    cropped: np.ndarray,
) -> tuple[
    list[int | None],
    np.ndarray,
    np.ndarray,
    list[str],
    int,
]:
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    mask_raw = _build_raw_mask(gray)
    mask_clean, border_components = _clean_mask(mask_raw)
    raw_white = int(np.count_nonzero(mask_raw))
    clean_white = int(np.count_nonzero(mask_clean))
    clean_col_pct = _column_coverage_pct(mask_clean)
    logger.info(
        (
            "[INGV COLORED][mask] raw_white=%s clean_white=%s clean_columns=%.1f%%"
        ),
        raw_white,
        clean_white,
        clean_col_pct,
    )

    if clean_col_pct < MIN_VALID_COLUMN_PCT:
        fallback_mask = _fallback_black_curve_mask(cropped)
        fallback_col_pct = _column_coverage_pct(fallback_mask)
        fallback_white = int(np.count_nonzero(fallback_mask))
        logger.warning(
            (
                "[INGV COLORED][mask] cleaning too aggressive (columns=%.1f%%). "
                "Fallback black detector: white=%s columns=%.1f%%"
            ),
            clean_col_pct,
            fallback_white,
            fallback_col_pct,
        )
        if fallback_col_pct >= clean_col_pct:
            mask_clean = fallback_mask
            clean_white = fallback_white
            clean_col_pct = fallback_col_pct
            logger.info(
                "[INGV COLORED][mask] using fallback black detector mask",
            )

    points: list[int | None] = []
    reasons: list[str] = []
    previous_y = None

    for x in range(width):
        column = np.where(mask_clean[:, x] == 255)[0]
        if column.size > 0:
            candidate_y = int(np.median(column))
            if candidate_y <= 0 or candidate_y >= height - 1:
                points.append(None)
                reasons.append("edge_reject")
                continue
            points.append(candidate_y)
            reasons.append("direct")
            previous_y = candidate_y
            continue

        candidate_y = _fallback_from_neighbors(mask_clean, x)
        if candidate_y is None:
            points.append(None)
            reasons.append("empty_column")
            continue
        if previous_y is None or abs(candidate_y - previous_y) > MAX_DELTA_Y:
            points.append(None)
            reasons.append("continuity_reject")
            continue
        if candidate_y <= 0 or candidate_y >= height - 1:
            points.append(None)
            reasons.append("edge_reject")
            continue
        points.append(candidate_y)
        reasons.append("neighbor")
        previous_y = candidate_y

    return points, mask_raw, mask_clean, reasons, border_components


def _build_raw_mask(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, mask_raw = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_raw = cv2.dilate(mask_raw, dilate_kernel, iterations=1)
    return mask_raw


def _clean_mask(mask_raw: np.ndarray) -> tuple[np.ndarray, int]:
    mask_clean = mask_raw.copy()
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, VERTICAL_OPEN_KERNEL)
    vertical_lines = cv2.morphologyEx(mask_clean, cv2.MORPH_OPEN, vertical_kernel)
    vertical_ratio = np.count_nonzero(vertical_lines) / max(mask_clean.size, 1)
    if vertical_ratio > VERTICAL_LINE_PIXEL_RATIO:
        mask_clean = cv2.subtract(mask_clean, vertical_lines)
        logger.info(
            "[INGV COLORED][mask] removed vertical lines ratio=%.3f",
            vertical_ratio,
        )
    else:
        logger.info(
            "[INGV COLORED][mask] skipped vertical line removal ratio=%.3f",
            vertical_ratio,
        )

    noise_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, NOISE_OPEN_KERNEL)
    mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_OPEN, noise_kernel)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, NOISE_CLOSE_KERNEL)
    mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_CLOSE, close_kernel)

    mask_clean[:EDGE_MARGIN_PX, :] = 0
    mask_clean[-EDGE_MARGIN_PX:, :] = 0
    mask_clean[:, -EDGE_MARGIN_PX:] = 0

    num_removed = _remove_border_components(mask_clean)
    return mask_clean, num_removed


def _remove_border_components(mask: np.ndarray) -> int:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape
    removed = 0
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < MIN_COMPONENT_AREA:
            mask[labels == label] = 0
            removed += 1
            continue
        touches_border = y <= 0 or (x + w) >= width or (y + h) >= height
        if touches_border:
            mask[labels == label] = 0
            removed += 1
    return removed


def _column_coverage_pct(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    column_has_data = np.any(mask == 255, axis=0)
    return float(column_has_data.mean() * 100)


def _fallback_black_curve_mask(cropped: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    _, s, v = cv2.split(hsv)
    dark_pixels = (v < 90) & (gray < 85) & (s < 90)
    mask = np.where(dark_pixels, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    mask[:EDGE_MARGIN_PX, :] = 0
    mask[-EDGE_MARGIN_PX:, :] = 0
    mask[:, -EDGE_MARGIN_PX:] = 0
    _remove_border_components(mask)
    return mask


def _count_missing_tail_columns(values: list[int | None], tail_columns: int) -> int:
    if not values:
        return 0
    tail = values[-tail_columns:] if len(values) > tail_columns else values
    return sum(1 for value in tail if value is None)


def _count_tail_reasons(reasons: list[str], tail_columns: int) -> dict[str, int]:
    if not reasons:
        return {}
    tail = reasons[-tail_columns:] if len(reasons) > tail_columns else reasons
    summary: dict[str, int] = {}
    for reason in tail:
        if reason.startswith("direct") or reason.startswith("neighbor"):
            continue
        summary[reason] = summary.get(reason, 0) + 1
    return summary


def _fallback_from_neighbors(mask: np.ndarray, x: int) -> int | None:
    width = mask.shape[1]
    for search_range in (NEIGHBORHOOD_RANGE, NEIGHBORHOOD_EXTENDED_RANGE):
        y_values: list[int] = []
        for offset in range(-search_range, search_range + 1):
            if offset == 0:
                continue
            neighbor_x = x + offset
            if neighbor_x < 0 or neighbor_x >= width:
                continue
            ys = np.where(mask[:, neighbor_x] == 255)[0]
            if ys.size > 0:
                y_values.extend(ys.tolist())
        if y_values:
            return int(np.median(y_values))
    return None


def _apply_hampel_filter(values: list[int | None], window: int, sigma: float) -> list[int | None]:
    if window <= 1:
        return values
    half = window // 2
    filtered: list[int | None] = []
    for idx, value in enumerate(values):
        if value is None:
            filtered.append(None)
            continue
        start = max(0, idx - half)
        end = min(len(values), idx + half + 1)
        window_vals = [v for v in values[start:end] if v is not None]
        if len(window_vals) < 3:
            filtered.append(value)
            continue
        median = float(np.median(window_vals))
        mad = float(np.median([abs(v - median) for v in window_vals]))
        if mad == 0:
            filtered.append(value)
            continue
        threshold = sigma * 1.4826 * mad
        if abs(value - median) > threshold:
            filtered.append(int(round(median)))
        else:
            filtered.append(value)
    return filtered


def _pixel_to_mv(y_pixel: int, height: int) -> float:
    y_norm = y_pixel / height
    log_val = 1 - y_norm * 2
    return float(10 ** log_val)


def _write_debug_artifacts(
    cropped: np.ndarray,
    mask_raw: np.ndarray,
    mask_clean: np.ndarray,
    xs: list[int],
    ys: list[int | None],
) -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", data_dir / "debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    overlay = cropped.copy()
    segment: list[tuple[int, int]] = []
    for x, y in zip(xs, ys):
        if y is None:
            if len(segment) >= 2:
                pts = np.array(segment, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(overlay, [pts], False, (0, 0, 255), 1, cv2.LINE_AA)
            segment = []
            continue
        segment.append((x, y))
    if len(segment) >= 2:
        pts = np.array(segment, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(overlay, [pts], False, (0, 0, 255), 1, cv2.LINE_AA)

    crop_path = debug_dir / "crop_plot_area.png"
    mask_raw_path = debug_dir / "mask_raw.png"
    mask_clean_path = debug_dir / "mask_clean.png"
    overlay_path = debug_dir / "overlay.png"

    cv2.imwrite(str(crop_path), cropped)
    cv2.imwrite(str(mask_raw_path), mask_raw)
    cv2.imwrite(str(mask_clean_path), mask_clean)
    cv2.imwrite(str(overlay_path), overlay)

    return {
        "crop": str(crop_path),
        "mask_raw": str(mask_raw_path),
        "mask_clean": str(mask_clean_path),
        "mask": str(mask_clean_path),
        "overlay": str(overlay_path),
    }
