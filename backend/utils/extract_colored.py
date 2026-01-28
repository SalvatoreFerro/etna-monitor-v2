import json
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

BASE_MAX_DELTA_Y = 18
NEIGHBORHOOD_EXTENDED_RANGE = 3
Y_PICK_MODE = os.getenv("INGV_COLORED_Y_PICK_MODE", "adaptive").lower()
Y_PICK_PERCENTILE_THICK = int(os.getenv("INGV_COLORED_Y_PICK_PERCENTILE_THICK", "80"))
THICKNESS_THRESHOLD_PX = 2
BIAS_SAMPLE_COLUMNS = 200
BIAS_IQR_THRESHOLD = 0.7

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
    ) = _extract_curve_points(cropped, bbox)

    xs_px = list(range(mask_candidate.shape[1]))
    y_offset = offsets["top"]

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
        mask_meta["mask_raw"],
        mask_candidate,
        mask_polyline,
        xs_px,
        raw_points,
        filtered_points,
        mask_meta["column_ranges"],
        y_offset,
        debug_payload=mask_meta.get("debug_payload"),
    )
    error_stats = _estimate_column_error(mask_meta["column_ranges"], filtered_points)
    pick_modes = mask_meta["pick_modes"]
    pick_thicknesses = mask_meta["pick_thicknesses"]
    continuity_adjusted = mask_meta["continuity_adjusted"]
    bias_meta = mask_meta["bias_meta"]
    thin_count = sum(
        1
        for thickness in pick_thicknesses
        if thickness is not None and thickness <= THICKNESS_THRESHOLD_PX
    )
    thick_count = sum(
        1
        for thickness in pick_thicknesses
        if thickness is not None and thickness > THICKNESS_THRESHOLD_PX
    )
    pick_columns = max(thin_count + thick_count, 1)
    continuity_pct = continuity_adjusted / pick_columns * 100
    thickness_values = [value for value in pick_thicknesses if value is not None]
    thickness_median = float(np.median(thickness_values)) if thickness_values else 0.0
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
    logger.info(
        (
            "[INGV COLORED][debug picks] y_offset=%s y_pick_mode=%s "
            "thin_cols=%s thick_cols=%s thickness_median=%.2f p%02d max_delta_y=%s "
            "continuity_adjusted=%.1f%% mean_span=%.2f mean_offset_from_min=%.2f"
        ),
        y_offset,
        Y_PICK_MODE,
        thin_count,
        thick_count,
        thickness_median,
        Y_PICK_PERCENTILE_THICK,
        mask_meta.get("max_delta_y", BASE_MAX_DELTA_Y),
        continuity_pct,
        error_stats["mean_span"],
        error_stats["mean_offset_from_min"],
    )
    if bias_meta["applied"]:
        logger.info(
            "[INGV COLORED][bias] shift_y=%s bias_median=%.2f iqr=%.2f threshold=%.2f samples=%s",
            bias_meta["shift"],
            bias_meta["median"],
            bias_meta["iqr"],
            bias_meta["threshold"],
            bias_meta["samples"],
        )
    else:
        logger.info(
            (
                "[INGV COLORED][bias] skipped bias_median=%.2f iqr=%.2f threshold=%.2f "
                "samples=%s reason=%s"
            ),
            bias_meta["median"],
            bias_meta["iqr"],
            bias_meta["threshold"],
            bias_meta["samples"],
            bias_meta.get("disabled_reason"),
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
    bbox: tuple[int, int, int, int],
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
    mask_meta["bbox"] = bbox
    mask_raw = mask_meta["mask_raw"]
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
    column_ranges: list[tuple[int | None, int | None]] = []
    pick_modes: list[str | None] = []
    pick_thicknesses: list[int | None] = []
    continuity_adjusted = 0
    invalid_raw = 0
    previous_pick = None
    for x in range(width):
        column = np.where(mask_candidate[:, x] == 255)[0]
        (
            candidate_y,
            y_min,
            y_max,
            pick_mode,
            adjusted,
            thickness,
        ) = _pick_column_y(column, previous_pick)
        if candidate_y is None or candidate_y <= 0 or candidate_y >= height - 1:
            raw_points.append(None)
            column_ranges.append((None, None))
            pick_modes.append(None)
            pick_thicknesses.append(None)
            previous_pick = None
            if candidate_y is not None:
                invalid_raw += 1
        else:
            raw_points.append(candidate_y)
            column_ranges.append((y_min, y_max))
            pick_modes.append(pick_mode)
            pick_thicknesses.append(thickness)
            previous_pick = candidate_y
        if adjusted:
            continuity_adjusted += 1

    thickness_values = [value for value in pick_thicknesses if value is not None]
    thickness_median = float(np.median(thickness_values)) if thickness_values else 0.0
    max_delta_y = BASE_MAX_DELTA_Y

    filtered_points, reasons, continuity_rejected = _apply_continuity(
        raw_points,
        max_delta_y,
    )
    rejection_ratio = continuity_rejected / len(raw_points) if raw_points else 0.0
    if rejection_ratio > 0.7:
        max_delta_y = max(BASE_MAX_DELTA_Y, int(round(thickness_median * 4 + 6)))
        logger.warning(
            (
                "[INGV COLORED][continuity] high rejection %.1f%%, "
                "expanding MAX_DELTA_Y to %s"
            ),
            rejection_ratio * 100,
            max_delta_y,
        )
        filtered_points, reasons, continuity_rejected = _apply_continuity(
            raw_points,
            max_delta_y,
        )
        rejection_ratio_after = (
            continuity_rejected / len(raw_points) if raw_points else 0.0
        )
        logger.warning(
            (
                "[INGV COLORED][continuity] rejection before=%.1f%% after=%.1f%% "
                "max_delta_y=%s"
            ),
            rejection_ratio * 100,
            rejection_ratio_after * 100,
            max_delta_y,
        )

    pre_bias_valid = np.array([y for y in filtered_points if y is not None], dtype=float)
    pre_bias_stddev = float(np.std(pre_bias_valid)) if pre_bias_valid.size else 0.0
    corrected_points, bias_meta = _apply_bias_correction(
        filtered_points,
        cropped,
        height,
        coverage_pct=candidate_col_pct,
        y_stddev=pre_bias_stddev,
    )

    mask_polyline = _build_polyline_mask(height, width, corrected_points)
    empty_columns = sum(1 for y in raw_points if y is None)
    continuity_reject_count = sum(1 for reason in reasons if reason == "continuity_reject")
    clamped_invalid = sum(
        1
        for y in corrected_points
        if y is None or y <= 0 or y >= height - 1
    )
    valid_y = np.array([y for y in corrected_points if y is not None], dtype=float)
    y_stddev = float(np.std(valid_y)) if valid_y.size else 0.0
    y_min = float(np.min(valid_y)) if valid_y.size else 0.0
    y_max = float(np.max(valid_y)) if valid_y.size else 0.0
    logger.info(
        (
            "[INGV COLORED][extract stats] plot_bbox=%s coverage_pct=%.1f%% "
            "empty_columns=%s continuity_rejected=%s clamped_invalid=%s "
            "y_stddev=%.2f y_min=%.1f y_max=%.1f max_delta_y=%s"
        ),
        mask_meta["bbox"],
        candidate_col_pct,
        empty_columns,
        continuity_reject_count,
        clamped_invalid,
        y_stddev,
        y_min,
        y_max,
        max_delta_y,
    )
    debug_payload = {
        "bbox": mask_meta["bbox"],
        "coverage_pct": candidate_col_pct,
        "empty_cols": empty_columns,
        "rejected_by_continuity": continuity_reject_count,
        "clamped_or_invalid": clamped_invalid,
        "stddev_y": y_stddev,
        "min_y": y_min,
        "max_y": y_max,
        "shift_y": bias_meta.get("shift", 0),
        "iqr": bias_meta.get("iqr", 0.0),
        "threshold": bias_meta.get("threshold", BIAS_IQR_THRESHOLD),
        "max_delta_y": max_delta_y,
        "pick_mode": pick_modes,
        "pick_thickness": pick_thicknesses,
        "shift_disabled_reason": bias_meta.get("disabled_reason"),
    }
    if y_stddev < 0.3 or candidate_col_pct < 20.0:
        logger.error(
            "[INGV COLORED][extract stats] FATAL low signal stddev=%.2f coverage=%.1f%%",
            y_stddev,
            candidate_col_pct,
        )
        _write_debug_artifacts(
            cropped,
            mask_raw,
            mask_candidate,
            mask_polyline,
            list(range(width)),
            raw_points,
            corrected_points,
            column_ranges,
            0,
            debug_payload=debug_payload,
        )
        raise ValueError(
            "Colored PNG extraction failed: curve is flat or missing (stddev/coverage guard)."
        )

    return (
        raw_points,
        corrected_points,
        mask_candidate,
        mask_polyline,
        reasons,
        border_components,
        {
            **mask_meta,
            "column_ranges": column_ranges,
            "pick_modes": pick_modes,
            "pick_thicknesses": pick_thicknesses,
            "continuity_adjusted": continuity_adjusted,
            "bias_meta": bias_meta,
            "max_delta_y": max_delta_y,
            "invalid_raw": invalid_raw,
            "y_stddev": y_stddev,
            "y_min": y_min,
            "y_max": y_max,
            "coverage_pct": candidate_col_pct,
            "debug_payload": debug_payload,
        },
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
    best_raw = None
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
        candidate_raw = config["candidate"].copy()
        candidate = candidate_raw.copy()
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
            best_raw = candidate_raw
            best_coverage = coverage
            border_components = removed
        if coverage >= TRUE_MASK_MIN_COLUMN_PCT:
            return candidate, removed, {"attempts": attempts, "mask_raw": candidate_raw, "bbox": None}

    if best_mask is None:
        best_mask = _build_candidate_mask(gray)
        best_raw = best_mask.copy()

    return best_mask, border_components, {"attempts": attempts, "mask_raw": best_raw, "bbox": None}


def _apply_continuity(
    raw_points: list[int | None],
    max_delta_y: int,
) -> tuple[list[int | None], list[str], int]:
    filtered_points: list[int | None] = []
    reasons: list[str] = []
    continuity_rejected = 0
    previous_y = None

    for x, candidate_y in enumerate(raw_points):
        if candidate_y is None:
            fallback = _interpolate_if_coherent(raw_points, x, max_delta_y)
            if fallback is None:
                filtered_points.append(None)
                reasons.append("empty_column")
                continue
            if previous_y is not None and abs(fallback - previous_y) > max_delta_y:
                filtered_points.append(None)
                reasons.append("continuity_reject")
                continuity_rejected += 1
                continue
            filtered_points.append(fallback)
            reasons.append("interpolate")
            previous_y = fallback
            continue

        if previous_y is not None and abs(candidate_y - previous_y) > max_delta_y:
            fallback = _interpolate_if_coherent(raw_points, x, max_delta_y)
            if fallback is None or abs(fallback - previous_y) > max_delta_y:
                filtered_points.append(None)
                reasons.append("continuity_reject")
                continuity_rejected += 1
                continue
            filtered_points.append(fallback)
            reasons.append("interpolate")
            previous_y = fallback
            continue

        filtered_points.append(candidate_y)
        reasons.append("direct")
        previous_y = candidate_y

    return filtered_points, reasons, continuity_rejected


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


def _pick_column_y(
    ys: np.ndarray, previous_y: int | None
) -> tuple[int | None, int | None, int | None, str | None, bool, int | None]:
    if ys.size == 0:
        return None, None, None, None, False, None
    ys_sorted = np.sort(ys)
    y_min = int(ys_sorted[0])
    y_max = int(ys_sorted[-1])
    thickness = int(y_max - y_min)

    if thickness <= THICKNESS_THRESHOLD_PX:
        pick_mode = "median"
        y_pick = int(round(np.median(ys_sorted)))
    else:
        percentile = np.percentile(ys_sorted, Y_PICK_PERCENTILE_THICK)
        percentile_pick = int(round(percentile))
        median_pick = int(round(np.median(ys_sorted)))
        if previous_y is not None and percentile_pick > previous_y:
            pick_mode = "median"
            y_pick = median_pick
        else:
            pick_mode = "percentile"
            y_pick = percentile_pick

    adjusted = False
    if previous_y is not None:
        closest_idx = int(np.argmin(np.abs(ys_sorted - previous_y)))
        closest = int(ys_sorted[closest_idx])
        if abs(closest - previous_y) <= BASE_MAX_DELTA_Y:
            adjusted = True
            y_pick = closest
            pick_mode = "closest"

    return y_pick, y_min, y_max, pick_mode, adjusted, thickness


def _interpolate_if_coherent(
    values: list[int | None],
    idx: int,
    max_delta_y: int,
) -> int | None:
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
    if abs(prev_val - next_val) > max_delta_y * 2:
        return None
    span = next_idx - prev_idx
    if span <= 0:
        return None
    ratio = (idx - prev_idx) / span
    return int(round(prev_val + (next_val - prev_val) * ratio))


def _apply_bias_correction(
    points: list[int | None],
    cropped: np.ndarray,
    height: int,
    *,
    coverage_pct: float,
    y_stddev: float,
) -> tuple[list[int | None], dict]:
    if coverage_pct < 60.0:
        logger.warning(
            "[INGV COLORED][bias] SHIFT DISABLED coverage guard (coverage=%.1f%%)",
            coverage_pct,
        )
        return points, {
            "applied": False,
            "shift": 0,
            "median": 0.0,
            "iqr": 0.0,
            "samples": 0,
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "coverage_guard",
        }
    if y_stddev < 1.0:
        logger.warning(
            "[INGV COLORED][bias] SHIFT DISABLED stddev guard (stddev=%.2f)",
            y_stddev,
        )
        return points, {
            "applied": False,
            "shift": 0,
            "median": 0.0,
            "iqr": 0.0,
            "samples": 0,
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "stddev_guard",
        }
    available_indices = [idx for idx, y in enumerate(points) if y is not None]
    if not available_indices:
        return points, {
            "applied": False,
            "shift": 0,
            "median": 0.0,
            "iqr": 0.0,
            "samples": 0,
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "no_points",
        }

    sample_size = min(BIAS_SAMPLE_COLUMNS, len(available_indices))
    rng = np.random.default_rng(42)
    sample_indices = rng.choice(available_indices, size=sample_size, replace=False)
    black_mask = _fallback_black_curve_mask(cropped)

    diffs = []
    for idx in sample_indices:
        y_pick = points[idx]
        if y_pick is None:
            continue
        column = np.where(black_mask[:, idx] == 255)[0]
        if column.size == 0:
            continue
        closest_idx = int(np.argmin(np.abs(column - y_pick)))
        y_black = int(column[closest_idx])
        diffs.append(float(y_pick - y_black))

    if len(diffs) < 10:
        return points, {
            "applied": False,
            "shift": 0,
            "median": 0.0,
            "iqr": 0.0,
            "samples": len(diffs),
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "insufficient_samples",
        }

    median_bias = float(np.median(diffs))
    iqr = float(np.percentile(diffs, 75) - np.percentile(diffs, 25))
    if iqr >= BIAS_IQR_THRESHOLD:
        return points, {
            "applied": False,
            "shift": 0,
            "median": median_bias,
            "iqr": iqr,
            "samples": len(diffs),
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "high_iqr",
        }

    shift = int(round(median_bias))
    if shift == 0:
        return points, {
            "applied": False,
            "shift": 0,
            "median": median_bias,
            "iqr": iqr,
            "samples": len(diffs),
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "zero_shift",
        }
    if abs(shift) > 5:
        logger.warning(
            "[INGV COLORED][bias] shift %s exceeds guard; disabling shift (iqr=%.2f threshold=%.2f)",
            shift,
            iqr,
            BIAS_IQR_THRESHOLD,
        )
        return points, {
            "applied": False,
            "shift": 0,
            "median": median_bias,
            "iqr": iqr,
            "samples": len(diffs),
            "threshold": BIAS_IQR_THRESHOLD,
            "disabled_reason": "shift_guard",
        }

    corrected = []
    for y in points:
        if y is None:
            corrected.append(None)
            continue
        adjusted = int(max(0, min(height - 1, y - shift)))
        corrected.append(adjusted)

    return corrected, {
        "applied": True,
        "shift": shift,
        "median": median_bias,
        "iqr": iqr,
        "samples": len(diffs),
        "threshold": BIAS_IQR_THRESHOLD,
        "disabled_reason": None,
    }


def _pixel_to_mv(y_pixel: int, height: int) -> float:
    y_norm = y_pixel / height
    log_val = 1 - y_norm * 2
    return float(10 ** log_val)


def _write_debug_artifacts(
    cropped: np.ndarray,
    mask_raw: np.ndarray,
    mask_candidate: np.ndarray,
    mask_polyline: np.ndarray,
    xs: list[int],
    raw_points: list[int | None],
    filtered_points: list[int | None],
    column_ranges: list[tuple[int | None, int | None]],
    y_offset: int,
    *,
    debug_payload: dict | None = None,
) -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", data_dir / "debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    overlay = cropped.copy()
    segment: list[tuple[int, int]] = []
    points_available = sum(1 for y in filtered_points if y is not None)
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
    mask_raw_path = debug_dir / "mask_raw.png"
    mask_clean_path = debug_dir / "mask_clean.png"
    mask_polyline_path = debug_dir / "mask_polyline.png"
    overlay_path = debug_dir / "overlay.png"
    overlay_marker_path = debug_dir / "overlay_markers.png"
    raw_csv_path = debug_dir / "curve_points.csv"
    filtered_csv_path = debug_dir / "curve_points_filtered.csv"
    filtered_global_csv_path = debug_dir / "curve_points_filtered_global.csv"

    cv2.imwrite(str(crop_path), cropped)
    cv2.imwrite(str(mask_candidate_path), mask_candidate)
    cv2.imwrite(str(mask_raw_path), mask_raw)
    cv2.imwrite(str(mask_clean_path), mask_candidate)
    cv2.imwrite(str(mask_polyline_path), mask_polyline)
    marker_overlay = overlay.copy()
    _draw_column_markers(marker_overlay, xs, filtered_points, column_ranges)
    if all(y is None for y in filtered_points):
        cv2.putText(
            marker_overlay,
            "NO DATA EXTRACTED",
            (10, max(20, marker_overlay.shape[0] // 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    if points_available < 2:
        overlay = marker_overlay.copy()
    cv2.imwrite(str(overlay_path), overlay)
    cv2.imwrite(str(overlay_marker_path), marker_overlay)
    _write_curve_points(raw_csv_path, xs, raw_points)
    _write_curve_points(filtered_csv_path, xs, filtered_points)
    filtered_global = [
        None if y is None else int(y + y_offset) for y in filtered_points
    ]
    _write_curve_points(filtered_global_csv_path, xs, filtered_global)

    debug_json_path = None
    if debug_payload is not None:
        debug_json_path = debug_dir / "debug.json"
        debug_json_path.write_text(
            json.dumps(debug_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "crop": str(crop_path),
        "mask_raw": str(mask_raw_path),
        "mask_clean": str(mask_clean_path),
        "mask_candidate": str(mask_candidate_path),
        "mask_polyline": str(mask_polyline_path),
        "mask": str(mask_polyline_path),
        "overlay": str(overlay_path),
        "overlay_marker": str(overlay_marker_path),
        "overlay_markers": str(overlay_marker_path),
        "curve_points": str(raw_csv_path),
        "curve_points_filtered": str(filtered_csv_path),
        "curve_points_filtered_global": str(filtered_global_csv_path),
        "debug_json": str(debug_json_path) if debug_json_path else None,
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


def _draw_column_markers(
    overlay: np.ndarray,
    xs: list[int],
    points: list[int | None],
    column_ranges: list[tuple[int | None, int | None]],
) -> None:
    height, width = overlay.shape[:2]
    sample_count = min(30, width)
    if sample_count == 0:
        return
    rng = np.random.default_rng(42)
    sample_indices = rng.choice(width, size=sample_count, replace=False)
    sample_indices = np.sort(sample_indices)
    for idx in sample_indices:
        if idx >= len(points):
            continue
        y = points[idx]
        y_min, y_max = column_ranges[idx] if idx < len(column_ranges) else (None, None)
        x = xs[idx] if idx < len(xs) else idx
        if y_min is not None and y_max is not None:
            y_min = int(max(0, min(height - 1, y_min)))
            y_max = int(max(0, min(height - 1, y_max)))
            cv2.line(overlay, (x, y_min), (x, y_max), (0, 255, 255), 1, cv2.LINE_AA)
        if y is not None:
            y = int(max(0, min(height - 1, y)))
            cv2.circle(overlay, (x, y), 2, (0, 0, 255), -1, cv2.LINE_AA)


def _estimate_column_error(
    column_ranges: list[tuple[int | None, int | None]],
    points: list[int | None],
) -> dict[str, float]:
    spans = []
    offsets = []
    for (y_min, y_max), y in zip(column_ranges, points):
        if y_min is None or y_max is None or y is None:
            continue
        spans.append(y_max - y_min)
        offsets.append(y - y_min)
    mean_span = float(np.mean(spans)) if spans else 0.0
    mean_offset = float(np.mean(offsets)) if offsets else 0.0
    return {"mean_span": mean_span, "mean_offset_from_min": mean_offset}
