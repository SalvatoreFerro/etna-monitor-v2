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

BLACK_L_PERCENTILE = 8
BLACK_L_MAX = 80

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
    mask = _build_curve_mask(cropped)

    xs_px = list(range(mask.shape[1]))
    ys_px = _extract_curve_points(mask)
    ys_px = _interpolate_gaps(ys_px, max_gap=MAX_GAP_COLUMNS)
    ys_px = _smooth_series(ys_px, window=SMOOTHING_WINDOW)

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

    debug_paths = _write_debug_artifacts(cropped, mask, xs_px, ys_px, image_path)
    logger.info(
        "[INGV COLORED] points=%s start_ref=%s end_ref=%s crop=%s",
        len(values),
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


def _build_curve_mask(cropped: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(cropped, cv2.COLOR_BGR2LAB)
    luminance = lab[:, :, 0]

    threshold = np.percentile(luminance, BLACK_L_PERCENTILE)
    threshold = min(threshold, BLACK_L_MAX)
    mask = (luminance <= threshold).astype(np.uint8) * 255

    mask = cv2.medianBlur(mask, 3)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    mask = _remove_grid_lines(mask)
    _apply_edge_margin(mask)
    return mask


def _remove_grid_lines(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(30, width // 20), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(30, height // 15))
    )

    horizontal_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, horizontal_kernel)
    vertical_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, vertical_kernel)

    cleaned = cv2.subtract(mask, horizontal_lines)
    cleaned = cv2.subtract(cleaned, vertical_lines)
    return cleaned


def _apply_edge_margin(mask: np.ndarray) -> None:
    height, width = mask.shape
    margin_x = max(EDGE_MARGIN_PX, int(width * EDGE_MARGIN_PCT))
    margin_y = max(EDGE_MARGIN_PX, int(height * EDGE_MARGIN_PCT))
    mask[:margin_y, :] = 0
    mask[-margin_y:, :] = 0
    mask[:, :margin_x] = 0
    mask[:, -margin_x:] = 0


def _extract_curve_points(mask: np.ndarray) -> list[int | None]:
    height, width = mask.shape
    points: list[int | None] = []
    previous_y = None

    for x in range(width):
        y_values = np.where(mask[:, x] > 0)[0]
        if len(y_values) == 0:
            points.append(None)
            continue

        clusters = _cluster_candidates(y_values)
        if previous_y is None:
            best_cluster = max(clusters, key=lambda cluster: len(cluster))
        else:
            best_cluster = min(
                clusters,
                key=lambda cluster: (abs(int(np.median(cluster)) - previous_y), -len(cluster)),
            )

        selected_y = int(np.median(best_cluster))
        points.append(selected_y)
        previous_y = selected_y

    return points


def _cluster_candidates(y_values: np.ndarray, gap: int = 2) -> list[np.ndarray]:
    if len(y_values) == 0:
        return []
    clusters = []
    current = [y_values[0]]
    for value in y_values[1:]:
        if value - current[-1] <= gap:
            current.append(value)
        else:
            clusters.append(np.array(current))
            current = [value]
    clusters.append(np.array(current))
    return clusters


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


def _smooth_series(values: list[int | None], window: int) -> list[int | None]:
    if window <= 1:
        return values
    smoothed: list[int | None] = []
    half = window // 2
    for idx, value in enumerate(values):
        if value is None:
            smoothed.append(None)
            continue
        start = max(0, idx - half)
        end = min(len(values), idx + half + 1)
        window_vals = [v for v in values[start:end] if v is not None]
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
) -> dict:
    debug_dir = Path(os.getenv("INGV_COLORED_DEBUG_DIR", source_path.parent / "debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    overlay = cropped.copy()
    for x, y in zip(xs, ys):
        if y is None:
            continue
        cv2.circle(overlay, (x, y), 1, (0, 0, 255), -1)

    mask_path = debug_dir / f"mask_{source_path.stem}.png"
    overlay_path = debug_dir / f"overlay_{source_path.stem}.png"

    cv2.imwrite(str(mask_path), mask)
    cv2.imwrite(str(overlay_path), overlay)

    return {
        "mask": str(mask_path),
        "overlay": str(overlay_path),
    }
