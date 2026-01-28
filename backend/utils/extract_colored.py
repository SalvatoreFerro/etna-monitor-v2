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

BBOX_PADDING_PX = 6
BBOX_DARK_RATIO = 0.35
BBOX_FALLBACK_PCT = {
    "top": 0.12,
    "bottom": 0.08,
    "left": 0.12,
    "right": 0.05,
}

MAX_DELTA_Y = 18
NEIGHBORHOOD_EXTENDED_RANGE = 3

TRUE_MASK_MIN_COLUMN_PCT = 90.0
FRAME_LINE_THICKNESS = 3


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
    (
        raw_points,
        filtered_points,
        mask_candidate,
        mask_polyline,
        reasons,
        border_components,
        mask_meta,
    ) = _extract_curve_points(cropped)

    xs_px = list(range(mask_candidate.shape[1]))

    valid_columns = sum(1 for y in filtered_points if y is not None)
    valid_ratio = (valid_columns / len(filtered_points) * 100) if filtered_points else 0.0
    missing_tail = _count_missing_tail_columns(filtered_points, tail_columns=50)
    tail_reasons = _count_tail_reasons(reasons, tail_columns=50)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - EXTRACTION_DURATION
    duration_seconds = EXTRACTION_DURATION.total_seconds()
    steps = max(mask_candidate.shape[1] - 1, 1)
    seconds_per_pixel = duration_seconds / steps

    timestamps = []
    values = []
    for x, y in zip(xs_px, filtered_points):
        if y is None:
            continue
        timestamp = start_time + timedelta(seconds=seconds_per_pixel * x)
        timestamps.append(timestamp)
        values.append(_pixel_to_mv(y, mask_candidate.shape[0]))

    debug_paths = _write_debug_artifacts(
        cropped,
        mask_candidate,
        mask_polyline,
        xs_px,
        raw_points,
        filtered_points,
    )
    logger.info(
        (
            "[INGV COLORED] valid_columns=%.1f%% (%s/%s) series_len=%s start_ref=%s end_ref=%s crop=%s"
        ),
        valid_ratio,
        valid_columns,
        len(filtered_points),
        len(values),
        start_time.isoformat(),
        end_time.isoformat(),
        offsets,
    )
    logger.info(
        (
            "[INGV COLORED][debug summary] bbox=%s columns_with_points=%.1f%% "
            "tail_empty=%s tail_empty_reasons=%s border_components_removed=%s candidate_attempts=%s"
        ),
        bbox,
        valid_ratio,
        missing_tail,
        tail_reasons,
        border_components,
        mask_meta["attempts"],
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
    list[int | None],
    np.ndarray,
    np.ndarray,
    list[str],
    int,
    dict,
]:
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    mask_candidate, border_components, mask_meta = _select_candidate_mask(gray, cropped)
    raw_white = int(np.count_nonzero(mask_candidate))
    candidate_col_pct = _column_coverage_pct(mask_candidate)
    logger.info(
        (
            "[INGV COLORED][mask] candidate_white=%s candidate_columns=%.1f%% attempts=%s"
        ),
        raw_white,
        candidate_col_pct,
        mask_meta["attempts"],
    )
    if candidate_col_pct < TRUE_MASK_MIN_COLUMN_PCT:
        logger.warning(
            "[INGV COLORED][mask] candidate coverage low (%.1f%%). Using best attempt anyway.",
            candidate_col_pct,
        )

    raw_points: list[int | None] = []
    for x in range(width):
        column = np.where(mask_candidate[:, x] == 255)[0]
        candidate_y = _robust_column_center(column)
        if candidate_y is None or candidate_y <= 0 or candidate_y >= height - 1:
            raw_points.append(None)
        else:
            raw_points.append(candidate_y)

    filtered_points: list[int | None] = []
    reasons: list[str] = []
    previous_y = None

    for x, candidate_y in enumerate(raw_points):
        if candidate_y is None:
            fallback = _interpolate_if_coherent(raw_points, x)
            if fallback is None:
                filtered_points.append(None)
                reasons.append("empty_column")
                continue
            if previous_y is not None and abs(fallback - previous_y) > MAX_DELTA_Y:
                filtered_points.append(None)
                reasons.append("continuity_reject")
                continue
            filtered_points.append(fallback)
            reasons.append("interpolate")
            previous_y = fallback
            continue

        if previous_y is not None and abs(candidate_y - previous_y) > MAX_DELTA_Y:
            fallback = _interpolate_if_coherent(raw_points, x)
            if fallback is None or abs(fallback - previous_y) > MAX_DELTA_Y:
                filtered_points.append(None)
                reasons.append("continuity_reject")
                continue
            filtered_points.append(fallback)
            reasons.append("interpolate")
            previous_y = fallback
            continue

        filtered_points.append(candidate_y)
        reasons.append("direct")
        previous_y = candidate_y

    mask_polyline = _build_polyline_mask(height, width, filtered_points)

    return (
        raw_points,
        filtered_points,
        mask_candidate,
        mask_polyline,
        reasons,
        border_components,
        mask_meta,
    )


def _build_candidate_mask(gray: np.ndarray) -> np.ndarray:
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


def _build_adaptive_candidate_mask(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    mask_raw = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        10,
    )
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_raw = cv2.dilate(mask_raw, dilate_kernel, iterations=1)
    return mask_raw


def _select_candidate_mask(
    gray: np.ndarray,
    cropped: np.ndarray,
) -> tuple[np.ndarray, int, dict]:
    attempts = []
    best_mask = None
    best_coverage = -1.0
    border_components = 0

    attempt_configs = [
        {
            "name": "otsu_close",
            "candidate": _build_candidate_mask(gray),
        },
        {
            "name": "adaptive_close",
            "candidate": _build_adaptive_candidate_mask(gray),
        },
        {
            "name": "black_fallback",
            "candidate": _fallback_black_curve_mask(cropped),
        },
    ]

    for config in attempt_configs:
        candidate = config["candidate"].copy()
        removed = _remove_frame_components(candidate)
        coverage = _column_coverage_pct(candidate)
        attempts.append(
            {
                "name": config["name"],
                "coverage": coverage,
                "removed": removed,
            }
        )
        if coverage > best_coverage:
            best_mask = candidate
            best_coverage = coverage
            border_components = removed
        if coverage >= TRUE_MASK_MIN_COLUMN_PCT:
            return candidate, removed, {"attempts": attempts}

    if best_mask is None:
        best_mask = _build_candidate_mask(gray)

    return best_mask, border_components, {"attempts": attempts}


def _remove_frame_components(mask: np.ndarray) -> int:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape
    removed = 0
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if _is_frame_component(x, y, w, h, area, height, width):
            mask[labels == label] = 0
            removed += 1
    return removed


def _is_frame_component(
    x: int,
    y: int,
    w: int,
    h: int,
    area: int,
    height: int,
    width: int,
) -> bool:
    if w == 0 or h == 0:
        return False
    touches_border = x <= 0 or y <= 0 or (x + w) >= width or (y + h) >= height
    if not touches_border:
        return False
    fill_ratio = area / max(w * h, 1)

    if h <= FRAME_LINE_THICKNESS and w >= width * 0.6:
        return True
    if w <= FRAME_LINE_THICKNESS and h >= height * 0.6:
        return True
    if (w >= width * 0.8 or h >= height * 0.8) and fill_ratio >= 0.6:
        return True
    return False


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
    _remove_frame_components(mask)
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


def _robust_column_center(ys: np.ndarray) -> int | None:
    if ys.size == 0:
        return None
    if ys.size == 1:
        return int(ys[0])
    p40 = np.percentile(ys, 40)
    p60 = np.percentile(ys, 60)
    subset = ys[(ys >= p40) & (ys <= p60)]
    if subset.size == 0:
        subset = ys
    return int(np.median(subset))


def _interpolate_if_coherent(values: list[int | None], idx: int) -> int | None:
    prev_idx = None
    next_idx = None
    for offset in range(1, NEIGHBORHOOD_EXTENDED_RANGE + 1):
        if prev_idx is None and idx - offset >= 0 and values[idx - offset] is not None:
            prev_idx = idx - offset
        if next_idx is None and idx + offset < len(values) and values[idx + offset] is not None:
            next_idx = idx + offset
        if prev_idx is not None and next_idx is not None:
            break

    if prev_idx is None or next_idx is None:
        return None
    prev_val = values[prev_idx]
    next_val = values[next_idx]
    if prev_val is None or next_val is None:
        return None
    if abs(prev_val - next_val) > MAX_DELTA_Y * 2:
        return None
    span = next_idx - prev_idx
    if span <= 0:
        return None
    ratio = (idx - prev_idx) / span
    return int(round(prev_val + (next_val - prev_val) * ratio))


def _pixel_to_mv(y_pixel: int, height: int) -> float:
    y_norm = y_pixel / height
    log_val = 1 - y_norm * 2
    return float(10 ** log_val)


def _write_debug_artifacts(
    cropped: np.ndarray,
    mask_candidate: np.ndarray,
    mask_polyline: np.ndarray,
    xs: list[int],
    raw_points: list[int | None],
    filtered_points: list[int | None],
) -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", data_dir / "debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    overlay = cropped.copy()
    segment: list[tuple[int, int]] = []
    for x, y in zip(xs, filtered_points):
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
    mask_candidate_path = debug_dir / "mask_candidate.png"
    mask_polyline_path = debug_dir / "mask_polyline.png"
    overlay_path = debug_dir / "overlay.png"
    raw_csv_path = debug_dir / "curve_points.csv"
    filtered_csv_path = debug_dir / "curve_points_filtered.csv"

    cv2.imwrite(str(crop_path), cropped)
    cv2.imwrite(str(mask_candidate_path), mask_candidate)
    cv2.imwrite(str(mask_polyline_path), mask_polyline)
    cv2.imwrite(str(overlay_path), overlay)
    _write_curve_points(raw_csv_path, xs, raw_points)
    _write_curve_points(filtered_csv_path, xs, filtered_points)

    return {
        "crop": str(crop_path),
        "mask_candidate": str(mask_candidate_path),
        "mask_polyline": str(mask_polyline_path),
        "mask": str(mask_polyline_path),
        "overlay": str(overlay_path),
        "curve_points": str(raw_csv_path),
        "curve_points_filtered": str(filtered_csv_path),
    }


def _build_polyline_mask(height: int, width: int, points: list[int | None]) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    segment: list[tuple[int, int]] = []
    for x, y in enumerate(points):
        if y is None:
            if len(segment) >= 2:
                pts = np.array(segment, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(mask, [pts], False, 255, 1, cv2.LINE_AA)
            segment = []
            continue
        segment.append((x, y))
    if len(segment) >= 2:
        pts = np.array(segment, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(mask, [pts], False, 255, 1, cv2.LINE_AA)
    return mask


def _write_curve_points(path: Path, xs: list[int], ys: list[int | None]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("x,y\n")
        for x, y in zip(xs, ys):
            y_value = "" if y is None else str(y)
            handle.write(f"{x},{y_value}\n")
