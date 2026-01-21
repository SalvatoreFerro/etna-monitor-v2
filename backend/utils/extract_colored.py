import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import requests


EXTRACTION_DURATION = timedelta(days=7)

# Percentual crop per isolare l'area plot del PNG colorato INGV.
# Calibrato per eliminare intestazione e margini con etichette.
CROP_TOP_PCT = 0.12
CROP_BOTTOM_PCT = 0.08
CROP_LEFT_PCT = 0.12
CROP_RIGHT_PCT = 0.05

EDGE_MARGIN_PCT = 0.02
EDGE_MARGIN_PX = 12

PLOT_ROI_TOP_PCT = 0.04
PLOT_ROI_BOTTOM_PCT = 0.1

MAX_DELTA_Y = 18
VERTICAL_GRADIENT_MIN = 10
DARK_INTENSITY_THRESHOLD = 55
LOCAL_WINDOW_PX = 12
SPIKE_DELTA = 22
SPIKE_MEDIAN_WINDOW = 7

MAX_GAP_COLUMNS = 14
SMOOTHING_WINDOW = 5


logger = logging.getLogger(__name__)


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

    cropped, offsets = _crop_plot_area(image)
    ys_px, intensities, discarded_points, mask = _extract_curve_points(cropped)

    xs_px = list(range(mask.shape[1]))
    valid_columns = sum(1 for y in ys_px if y is not None)
    valid_ratio = (valid_columns / len(ys_px) * 100) if ys_px else 0.0

    spike_mask, spike_points, max_jump_px = _detect_spikes(ys_px, intensities)

    ys_px = _interpolate_gaps(ys_px, max_gap=MAX_GAP_COLUMNS)
    ys_px = _smooth_series(ys_px, window=SMOOTHING_WINDOW, spike_mask=spike_mask)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - EXTRACTION_DURATION
    duration_seconds = EXTRACTION_DURATION.total_seconds()
    steps = max(mask.shape[1] - 1, 1)
    seconds_per_pixel = duration_seconds / steps

    timestamps = []
    values = []
    for x, y in zip(xs_px, ys_px):
        if y is None:
            continue
        timestamp = start_time + timedelta(seconds=seconds_per_pixel * x)
        timestamps.append(timestamp)
        values.append(_pixel_to_mv(y, mask.shape[0]))

    debug_paths = _write_debug_artifacts(
        cropped,
        mask,
        xs_px,
        ys_px,
        image_path,
        discarded_points,
        spike_points,
    )
    logger.info(
        "[INGV COLORED] valid_columns=%.1f%% (%s/%s) series_len=%s num_spikes=%s max_jump_px=%s start_ref=%s end_ref=%s crop=%s",
        valid_ratio,
        valid_columns,
        len(ys_px),
        len(values),
        len(spike_points),
        max_jump_px,
        start_time.isoformat(),
        end_time.isoformat(),
        offsets,
    )

    return timestamps, values, debug_paths


def _crop_plot_area(image: np.ndarray):
    height, width = image.shape[:2]
    top = int(height * CROP_TOP_PCT)
    bottom = int(height * (1 - CROP_BOTTOM_PCT))
    left = int(width * CROP_LEFT_PCT)
    right = int(width * (1 - CROP_RIGHT_PCT))

    cropped = image[top:bottom, left:right]
    offsets = {
        "top": top,
        "bottom": height - bottom,
        "left": left,
        "right": width - right,
    }
    return cropped, offsets


def _extract_curve_points(
    cropped: np.ndarray,
) -> tuple[list[int | None], list[int | None], list[tuple[int, int]], np.ndarray]:
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    roi_top = int(height * PLOT_ROI_TOP_PCT)
    roi_bottom = int(height * (1 - PLOT_ROI_BOTTOM_PCT))
    roi_bottom = max(roi_bottom, roi_top + 1)

    mask = np.zeros((height, width), dtype=np.uint8)
    points: list[int | None] = []
    intensities: list[int | None] = []
    discarded: list[tuple[int, int]] = []
    previous_y = None

    for x in range(width):
        column = gray[roi_top:roi_bottom, x]
        if column.size == 0:
            points.append(None)
            intensities.append(None)
            continue

        rel_y = int(np.argmin(column))
        candidate_y = roi_top + rel_y
        candidate_intensity = int(column[rel_y])

        if not _has_vertical_contrast(column, rel_y):
            discarded.append((x, candidate_y))
            points.append(None)
            intensities.append(None)
            continue

        if previous_y is not None:
            delta = abs(candidate_y - previous_y)
            if delta > MAX_DELTA_Y:
                if candidate_intensity < DARK_INTENSITY_THRESHOLD:
                    points.append(candidate_y)
                    intensities.append(candidate_intensity)
                    mask[candidate_y, x] = 255
                    previous_y = candidate_y
                    continue

                local_y = _local_min_nearby(column, previous_y, roi_top)
                if local_y is not None:
                    local_intensity = int(column[local_y - roi_top])
                    if local_intensity < candidate_intensity:
                        candidate_y = local_y
                        candidate_intensity = local_intensity
                    delta = abs(candidate_y - previous_y)

                if delta > MAX_DELTA_Y and candidate_intensity >= DARK_INTENSITY_THRESHOLD:
                    discarded.append((x, candidate_y))
                    points.append(None)
                    intensities.append(None)
                    continue

        points.append(candidate_y)
        intensities.append(candidate_intensity)
        mask[candidate_y, x] = 255
        previous_y = candidate_y

    _apply_edge_margin(mask)
    return points, intensities, discarded, mask


def _has_vertical_contrast(column: np.ndarray, rel_y: int) -> bool:
    if column.size < 2:
        return False
    diffs = np.abs(np.diff(column.astype(np.int16)))
    idx = min(rel_y, diffs.size - 1)
    local = diffs[idx]
    if rel_y > 0:
        local = max(local, diffs[rel_y - 1])
    return local >= VERTICAL_GRADIENT_MIN


def _local_min_nearby(
    column: np.ndarray,
    previous_y: int,
    roi_top: int,
) -> int | None:
    target_rel = previous_y - roi_top
    if target_rel < 0 or target_rel >= column.size:
        return None
    start = max(0, target_rel - LOCAL_WINDOW_PX)
    end = min(column.size, target_rel + LOCAL_WINDOW_PX + 1)
    window = column[start:end]
    if window.size == 0:
        return None
    window_rel = int(np.argmin(window)) + start
    return roi_top + window_rel


def _apply_edge_margin(mask: np.ndarray) -> None:
    height, width = mask.shape
    margin_x = max(EDGE_MARGIN_PX, int(width * EDGE_MARGIN_PCT))
    margin_y = max(EDGE_MARGIN_PX, int(height * EDGE_MARGIN_PCT))
    mask[:margin_y, :] = 0
    mask[-margin_y:, :] = 0
    mask[:, :margin_x] = 0
    mask[:, -margin_x:] = 0


def _interpolate_gaps(values: list[int | None], max_gap: int) -> list[int | None]:
    filled = values[:]
    last_index = None
    for idx, value in enumerate(values):
        if value is not None:
            if last_index is not None and idx - last_index > 1:
                gap = idx - last_index - 1
                if gap <= max_gap:
                    start = values[last_index]
                    end = value
                    if start is not None:
                        step = (end - start) / (gap + 1)
                        for i in range(1, gap + 1):
                            filled[last_index + i] = int(round(start + step * i))
            last_index = idx
    return filled


def _detect_spikes(
    values: list[int | None],
    intensities: list[int | None],
) -> tuple[list[bool], list[tuple[int, int]], int]:
    median = _median_filter(values, window=SPIKE_MEDIAN_WINDOW)
    spike_mask: list[bool] = []
    spike_points: list[tuple[int, int]] = []
    max_jump_px = 0
    prev_val = None
    for idx, (value, med, intensity) in enumerate(zip(values, median, intensities)):
        is_spike = False
        if value is not None and med is not None and intensity is not None:
            if abs(value - med) > SPIKE_DELTA and intensity < DARK_INTENSITY_THRESHOLD:
                is_spike = True
                spike_points.append((idx, value))
        spike_mask.append(is_spike)
        if value is not None and prev_val is not None:
            max_jump_px = max(max_jump_px, abs(value - prev_val))
        if value is not None:
            prev_val = value
    return spike_mask, spike_points, max_jump_px


def _median_filter(values: list[int | None], window: int) -> list[int | None]:
    if window <= 1:
        return values[:]
    half = window // 2
    filtered: list[int | None] = []
    for idx in range(len(values)):
        start = max(0, idx - half)
        end = min(len(values), idx + half + 1)
        window_vals = [v for v in values[start:end] if v is not None]
        filtered.append(int(np.median(window_vals)) if window_vals else None)
    return filtered


def _smooth_series(
    values: list[int | None],
    window: int,
    spike_mask: list[bool] | None = None,
) -> list[int | None]:
    if window <= 1:
        return values
    smoothed: list[int | None] = []
    half = window // 2
    for idx, value in enumerate(values):
        if spike_mask and idx < len(spike_mask) and spike_mask[idx] and value is not None:
            smoothed.append(value)
            continue
        if value is None:
            smoothed.append(None)
            continue
        start = max(0, idx - half)
        end = min(len(values), idx + half + 1)
        window_vals = [
            v
            for j, v in enumerate(values[start:end], start=start)
            if v is not None and not (spike_mask and j < len(spike_mask) and spike_mask[j])
        ]
        if not window_vals:
            smoothed.append(value)
        else:
            smoothed.append(int(np.median(window_vals)))
    return smoothed


def _pixel_to_mv(y_pixel: int, height: int) -> float:
    y_norm = y_pixel / height
    log_val = 1 - y_norm * 2
    return float(10 ** log_val)


def _write_debug_artifacts(
    cropped: np.ndarray,
    mask: np.ndarray,
    xs: list[int],
    ys: list[int | None],
    source_path: Path,
    discarded: list[tuple[int, int]] | None = None,
    spikes: list[tuple[int, int]] | None = None,
) -> dict:
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", source_path.parent / "debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    overlay = cropped.copy()
    mask_overlay = np.zeros_like(mask)
    previous_point = None
    for x, y in zip(xs, ys):
        if y is None:
            previous_point = None
            continue
        point = (x, y)
        if previous_point is not None:
            cv2.line(overlay, previous_point, point, (0, 0, 255), 1)
            cv2.line(mask_overlay, previous_point, point, 255, 1)
        else:
            mask_overlay[y, x] = 255
        previous_point = point

    if discarded:
        for x, y in discarded:
            cv2.circle(overlay, (x, y), 1, (0, 165, 255), -1)

    if spikes:
        for x, y in spikes:
            cv2.circle(overlay, (x, y), 2, (255, 0, 0), -1)

    mask_path = debug_dir / f"mask_{source_path.stem}.png"
    overlay_path = debug_dir / f"overlay_{source_path.stem}.png"

    cv2.imwrite(str(mask_path), mask_overlay if np.any(mask_overlay) else mask)
    cv2.imwrite(str(overlay_path), overlay)

    return {
        "mask": str(mask_path),
        "overlay": str(overlay_path),
    }
