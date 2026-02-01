import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import requests

from backend.utils.ingv_timestamp import extract_updated_timestamp_from_image
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
Y_PICK_MODE = os.getenv("INGV_COLORED_Y_PICK_MODE", "adaptive").lower()
THICKNESS_THRESHOLD_PX = 2
V_BLACK_MAX = int(os.getenv("INGV_COLORED_BLACK_V_MAX", "95"))
S_BLACK_MAX = int(os.getenv("INGV_COLORED_BLACK_S_MAX", "80"))
V_BLACK_THIN_MAX = int(os.getenv("INGV_COLORED_THIN_V_MAX", "135"))
S_BLACK_THIN_MAX = int(os.getenv("INGV_COLORED_THIN_S_MAX", "120"))
INK_MIN_PIXEL_RATIO = float(os.getenv("INGV_COLORED_INK_MIN_PIXEL_RATIO", "0.0002"))
INK_CLOSE_ITER = int(os.getenv("INGV_COLORED_INK_CLOSE_ITER", "2"))
INK_OPEN_ITER = int(os.getenv("INGV_COLORED_INK_OPEN_ITER", "1"))
INK_OPEN_NOISE_THRESHOLD = int(os.getenv("INGV_COLORED_INK_OPEN_NOISE_THRESHOLD", "80"))
INK_MAX_AREA_RATIO = float(os.getenv("INGV_COLORED_INK_MAX_AREA_RATIO", "0.08"))
INK_RECT_FILL_RATIO = float(os.getenv("INGV_COLORED_INK_RECT_FILL_RATIO", "0.6"))
INK_RECT_DIM_RATIO = float(os.getenv("INGV_COLORED_INK_RECT_DIM_RATIO", "0.25"))
INK_MARGIN_PX = int(os.getenv("INGV_COLORED_INK_MARGIN_PX", "6"))
EDGE_GUARD_PX = int(os.getenv("INGV_COLORED_EDGE_GUARD_PX", "2"))
BASELINE_THICKNESS_PX = int(os.getenv("INGV_COLORED_BASELINE_THICKNESS_PX", "6"))
BASELINE_BOTTOM_MARGIN_PX = int(
    os.getenv("INGV_COLORED_BASELINE_BOTTOM_MARGIN_PX", "4")
)
INK_CLOSE_THICKNESS_GUARD = float(
    os.getenv("INGV_COLORED_INK_CLOSE_THICKNESS_GUARD", "1.5")
)
INK_DILATE_ITER = int(os.getenv("INGV_COLORED_INK_DILATE_ITER", "1"))
SPIKE_DELTA_ABS_PX = int(os.getenv("INGV_COLORED_SPIKE_DELTA_ABS_PX", "12"))
SPIKE_EPSILON_PX = int(os.getenv("INGV_COLORED_SPIKE_EPSILON_PX", "2"))
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

    try:
        end_time = extract_updated_timestamp_from_image(image)
    except Exception as exc:
        logger.error("[INGV COLORED] timestamp OCR failed: %s", exc)
        raise
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
        mask_ink=mask_meta.get("mask_ink"),
        mask_ink_core=mask_meta.get("mask_ink_core"),
        mask_ink_thin=mask_meta.get("mask_ink_thin"),
        mask_ink_combined=mask_meta.get("mask_ink_combined"),
        mask_pretty=mask_meta.get("mask_pretty"),
        pick_tops=mask_meta.get("pick_tops"),
        pick_mids=mask_meta.get("pick_mids"),
        spike_columns=mask_meta.get("spike_columns"),
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
            "thin_cols=%s thick_cols=%s thickness_median=%.2f max_delta_y=%s "
            "continuity_adjusted=%.1f%% mean_span=%.2f mean_offset_from_min=%.2f"
        ),
        y_offset,
        Y_PICK_MODE,
        thin_count,
        thick_count,
        thickness_median,
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
    mask_ink = mask_meta.get("mask_ink", mask_raw)
    mask_pretty = mask_meta.get("mask_pretty")
    mask_final = mask_ink.copy()
    raw_white = int(np.count_nonzero(mask_final))
    candidate_col_pct = _column_coverage_pct(mask_final)
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
    pick_tops: list[int | None] = []
    pick_mids: list[int | None] = []
    pick_bots: list[int | None] = []
    pick_runs: list[int | None] = []
    pick_spikes: list[bool] = []
    continuity_adjusted = 0
    invalid_raw = 0
    previous_pick = None
    for x in range(width):
        column = np.where(mask_final[:, x] == 255)[0]
        (
            candidate_y,
            y_min,
            y_max,
            pick_mode,
            adjusted,
            thickness,
            y_top,
            y_mid,
            y_bot,
            runs,
            is_spike,
        ) = _pick_column_y(
            column,
            previous_pick,
            height,
        )
        if candidate_y is None or candidate_y <= 0 or candidate_y >= height - 1:
            raw_points.append(None)
            column_ranges.append((None, None))
            pick_modes.append(None)
            pick_thicknesses.append(None)
            pick_tops.append(None)
            pick_mids.append(None)
            pick_bots.append(None)
            pick_runs.append(None)
            pick_spikes.append(False)
            previous_pick = None
            if candidate_y is not None:
                invalid_raw += 1
        else:
            raw_points.append(candidate_y)
            column_ranges.append((y_min, y_max))
            pick_modes.append(pick_mode)
            pick_thicknesses.append(thickness)
            pick_tops.append(y_top)
            pick_mids.append(y_mid)
            pick_bots.append(y_bot)
            pick_runs.append(runs)
            pick_spikes.append(is_spike)
            previous_pick = candidate_y
        if adjusted:
            continuity_adjusted += 1

    thickness_values = [value for value in pick_thicknesses if value is not None]
    thickness_median = float(np.median(thickness_values)) if thickness_values else 0.0
    max_delta_y = BASE_MAX_DELTA_Y

    interpolated_points, interpolation_reasons = _interpolate_gaps(
        raw_points,
        max_delta_y,
    )
    filtered_points, reasons, continuity_adjusted = _apply_slope_guard(
        interpolated_points,
        max_delta_y,
        spike_columns=pick_spikes,
        base_reasons=interpolation_reasons,
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
    y_stddev_robust = _robust_stddev(valid_y)
    y_min = float(np.min(valid_y)) if valid_y.size else 0.0
    y_max = float(np.max(valid_y)) if valid_y.size else 0.0
    consecutive_equal, longest_equal_run = _count_consecutive_equals(corrected_points)
    coverage_ratio = valid_y.size / width if width else 0.0
    logger.info(
        (
            "[INGV COLORED][extract stats] plot_bbox=%s coverage_pct=%.1f%% "
            "empty_columns=%s continuity_rejected=%s clamped_invalid=%s "
            "y_stddev=%.2f y_stddev_robust=%.2f y_min=%.1f y_max=%.1f max_delta_y=%s"
        ),
        mask_meta["bbox"],
        candidate_col_pct,
        empty_columns,
        continuity_reject_count,
        clamped_invalid,
        y_stddev,
        y_stddev_robust,
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
        "stddev_y_robust": y_stddev_robust,
        "min_y": y_min,
        "max_y": y_max,
        "shift_y": bias_meta.get("shift", 0),
        "iqr": bias_meta.get("iqr", 0.0),
        "threshold": bias_meta.get("threshold", BIAS_IQR_THRESHOLD),
        "max_delta_y": max_delta_y,
        "pick_mode": pick_modes,
        "pick_thickness": pick_thicknesses,
        "coverage_ratio": coverage_ratio,
        "shift_disabled_reason": bias_meta.get("disabled_reason"),
        "consecutive_equal": consecutive_equal,
        "longest_equal_run": longest_equal_run,
        "spike_columns_count": int(sum(1 for flag in pick_spikes if flag)),
        "spike_override_used": any(pick_spikes),
        "iqr_used_for_spikes": False,
        "pick_samples": _sample_column_picks(
            column_ranges,
            pick_modes,
            corrected_points,
            pick_tops=pick_tops,
            pick_mids=pick_mids,
        ),
    }
    flat_suspect = (
        longest_equal_run >= int(width * 0.6)
        and thickness_median <= THICKNESS_THRESHOLD_PX
        and candidate_col_pct < 50.0
    )
    if coverage_ratio < 0.6 or flat_suspect:
        logger.error(
            (
                "[INGV COLORED][extract stats] FATAL low signal stddev=%.2f "
                "robust_stddev=%.2f coverage=%.1f%% equal=%s max_equal_run=%s sample=%s"
            ),
            y_stddev,
            y_stddev_robust,
            coverage_ratio * 100,
            consecutive_equal,
            longest_equal_run,
            debug_payload.get("pick_samples"),
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
            mask_ink=mask_ink,
            mask_ink_core=mask_meta.get("mask_ink_core"),
            mask_ink_thin=mask_meta.get("mask_ink_thin"),
            mask_ink_combined=mask_meta.get("mask_ink_combined"),
            mask_pretty=mask_meta.get("mask_pretty"),
            pick_tops=pick_tops,
            pick_mids=pick_mids,
            spike_columns=pick_spikes,
            debug_payload=debug_payload,
        )
        raise ValueError(
            "Colored PNG extraction failed: curve is flat or missing (stddev/coverage guard)."
        )

    if max_delta_y >= SPIKE_DELTA_ABS_PX:
        raw_max_y = max((y for y in raw_points if y is not None), default=None)
        final_max_y = max((y for y in corrected_points if y is not None), default=None)
        if raw_max_y is not None and (
            final_max_y is None or final_max_y < (raw_max_y - SPIKE_EPSILON_PX)
        ):
            raise ValueError("SPIKE LOST")

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
            "pick_tops": pick_tops,
            "pick_mids": pick_mids,
            "pick_bots": pick_bots,
            "pick_runs": pick_runs,
            "continuity_adjusted": continuity_adjusted,
            "bias_meta": bias_meta,
            "max_delta_y": max_delta_y,
            "invalid_raw": invalid_raw,
            "y_stddev": y_stddev,
            "y_min": y_min,
            "y_max": y_max,
            "coverage_pct": candidate_col_pct,
            "spike_columns": pick_spikes,
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


def _plot_area_mask(height: int, width: int) -> np.ndarray:
    margin = max(INK_MARGIN_PX, EDGE_GUARD_PX + 1, FRAME_LINE_THICKNESS)
    mask = np.zeros((height, width), dtype=np.uint8)
    if height <= margin * 2 or width <= margin * 2:
        mask[:, :] = 255
        return mask
    mask[margin : height - margin, margin : width - margin] = 255
    return mask


def _select_hsv_ink_mask(
    *,
    v: np.ndarray,
    s: np.ndarray,
    v_max: int,
    s_max: int,
    min_pixels: int,
) -> tuple[np.ndarray, dict]:
    mask_vs = (v <= v_max) & (s <= s_max)
    mask_v = v <= v_max
    use_v_only = np.count_nonzero(mask_vs) < min_pixels and np.count_nonzero(mask_v) > 0
    selected = mask_v if use_v_only else mask_vs
    mask = np.where(selected, 255, 0).astype(np.uint8)
    return mask, {
        "mode": "v_only" if use_v_only else "v_and_s",
        "count_vs": int(np.count_nonzero(mask_vs)),
        "count_v": int(np.count_nonzero(mask_v)),
        "min_pixels": min_pixels,
        "v_max": v_max,
        "s_max": s_max,
    }


def _build_ink_mask(
    cropped: np.ndarray,
    within_plot_area: np.ndarray,
) -> tuple[np.ndarray, dict]:
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    total_pixels = max(int(cropped.shape[0] * cropped.shape[1]), 1)
    min_pixels = max(10, int(total_pixels * INK_MIN_PIXEL_RATIO))

    core_mask, core_meta = _select_hsv_ink_mask(
        v=v,
        s=s,
        v_max=V_BLACK_MAX,
        s_max=S_BLACK_MAX,
        min_pixels=min_pixels,
    )
    thin_mask, thin_meta = _select_hsv_ink_mask(
        v=v,
        s=s,
        v_max=V_BLACK_THIN_MAX,
        s_max=S_BLACK_THIN_MAX,
        min_pixels=min_pixels,
    )
    combined = core_mask.copy()
    combined[(thin_mask == 255) & (within_plot_area == 255)] = 255
    combined = cv2.bitwise_and(combined, within_plot_area)

    return combined, {
        "core_mask": core_mask,
        "thin_mask": thin_mask,
        "combined_mask": combined,
        "core_meta": core_meta,
        "thin_meta": thin_meta,
    }


def _clean_ink_mask(mask: np.ndarray) -> tuple[np.ndarray, dict]:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = mask.copy()
    close_applied = False
    close_rejected = False
    if INK_CLOSE_ITER > 0:
        before_thickness = _estimate_mask_mean_thickness(cleaned)
        candidate = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)
        after_thickness = _estimate_mask_mean_thickness(candidate)
        if (after_thickness - before_thickness) <= INK_CLOSE_THICKNESS_GUARD:
            cleaned = candidate
            close_applied = True
        else:
            close_rejected = True
    open_applied = False
    if _should_open_mask(cleaned):
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=INK_OPEN_ITER)
        open_applied = True

    dilated = False
    if INK_DILATE_ITER > 0:
        mean_thickness = _estimate_mask_mean_thickness(cleaned)
        if mean_thickness <= THICKNESS_THRESHOLD_PX + 0.5:
            cleaned = cv2.dilate(cleaned, kernel, iterations=1)
            dilated = True

    removed_border = _remove_border_components(cleaned)
    removed_large = _remove_large_components(cleaned)
    return cleaned, {
        "close_applied": close_applied,
        "close_rejected": close_rejected,
        "open_applied": open_applied,
        "dilated": dilated,
        "removed_border": removed_border,
        "removed_large": removed_large,
    }


def _should_open_mask(mask: np.ndarray) -> bool:
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    noise_components = 0
    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area <= 2:
            noise_components += 1
            if noise_components >= INK_OPEN_NOISE_THRESHOLD:
                return True
    return False


def _select_candidate_mask(
    gray: np.ndarray,
    cropped: np.ndarray,
) -> tuple[np.ndarray, int, dict]:
    attempts = []
    border_components = 0

    plot_area_mask = _plot_area_mask(cropped.shape[0], cropped.shape[1])
    ink_combined, ink_meta = _build_ink_mask(cropped, plot_area_mask)
    mask_ink = ink_combined.copy()
    border_components = _remove_frame_components(mask_ink)
    ink_pretty, ink_pretty_meta = _clean_ink_mask(ink_combined)

    coverage = _column_coverage_pct(mask_ink)
    area_ratio = float(np.count_nonzero(mask_ink)) / max(float(mask_ink.size), 1.0)
    attempts.append(
        {
            "name": "hsv_ink_raw",
            "coverage": coverage,
            "area_ratio": area_ratio,
            "removed": border_components,
            "meta": {**ink_meta, "area_ratio": area_ratio},
        }
    )
    pretty_coverage = _column_coverage_pct(ink_pretty)
    pretty_area_ratio = float(np.count_nonzero(ink_pretty)) / max(
        float(ink_pretty.size), 1.0
    )
    attempts.append(
        {
            "name": "hsv_ink_pretty",
            "coverage": pretty_coverage,
            "area_ratio": pretty_area_ratio,
            "removed": 0,
            "meta": {**ink_meta, **ink_pretty_meta, "area_ratio": pretty_area_ratio},
        }
    )

    return mask_ink, border_components, {
        "attempts": attempts,
        "mask_raw": ink_combined.copy(),
        "mask_ink": mask_ink,
        "mask_ink_core": ink_meta.get("core_mask"),
        "mask_ink_thin": ink_meta.get("thin_mask"),
        "mask_ink_combined": ink_meta.get("combined_mask"),
        "mask_pretty": ink_pretty,
        "bbox": None,
    }


def _interpolate_gaps(
    points: list[int | None],
    max_delta_y: int,
) -> tuple[list[int | None], list[str]]:
    filled = points.copy()
    reasons = ["direct" if value is not None else "empty" for value in points]
    last_valid_idx = None
    for idx, value in enumerate(points):
        if value is not None:
            if last_valid_idx is not None and idx - last_valid_idx > 1:
                prev_val = points[last_valid_idx]
                next_val = value
                if prev_val is not None:
                    span = idx - last_valid_idx
                    slope = abs(next_val - prev_val) / span
                    if slope <= max_delta_y:
                        for j in range(last_valid_idx + 1, idx):
                            ratio = (j - last_valid_idx) / span
                            interpolated = int(round(prev_val + (next_val - prev_val) * ratio))
                            filled[j] = interpolated
                            reasons[j] = "interpolate"
            last_valid_idx = idx
    return filled, reasons


def _apply_slope_guard(
    points: list[int | None],
    max_delta_y: int,
    *,
    spike_columns: list[bool] | None = None,
    base_reasons: list[str] | None = None,
) -> tuple[list[int | None], list[str], int]:
    guarded: list[int | None] = []
    reasons: list[str] = []
    adjusted = 0
    previous_y = None
    for idx, value in enumerate(points):
        reason = base_reasons[idx] if base_reasons and idx < len(base_reasons) else "direct"
        if value is None:
            guarded.append(None)
            reasons.append(reason)
            continue
        if previous_y is None:
            guarded.append(value)
            reasons.append(reason)
            previous_y = value
            continue
        if spike_columns and idx < len(spike_columns) and spike_columns[idx]:
            guarded.append(value)
            reasons.append("spike_accept")
            previous_y = value
            continue
        delta = value - previous_y
        if abs(delta) > max_delta_y:
            clamped = int(previous_y + max_delta_y * (1 if delta > 0 else -1))
            guarded.append(clamped)
            reasons.append("slope_guard")
            previous_y = clamped
            adjusted += 1
        else:
            guarded.append(value)
            reasons.append(reason)
            previous_y = value
    return guarded, reasons, adjusted


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


def _remove_border_components(mask: np.ndarray) -> int:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape
    removed = 0
    for label in range(1, num_labels):
        x, y, w, h, _ = stats[label]
        touches_border = x <= 0 or y <= 0 or (x + w) >= width or (y + h) >= height
        if touches_border:
            mask[labels == label] = 0
            removed += 1
    return removed


def _remove_large_components(mask: np.ndarray) -> int:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape
    removed = 0
    total_pixels = max(height * width, 1)
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if w == 0 or h == 0:
            continue
        area_ratio = area / total_pixels
        fill_ratio = area / max(w * h, 1)
        near_margin = (
            x <= INK_MARGIN_PX
            or y <= INK_MARGIN_PX
            or (x + w) >= (width - INK_MARGIN_PX)
            or (y + h) >= (height - INK_MARGIN_PX)
        )
        oversize = area_ratio >= INK_MAX_AREA_RATIO
        rectangular = (
            fill_ratio >= INK_RECT_FILL_RATIO
            and (w >= width * INK_RECT_DIM_RATIO or h >= height * INK_RECT_DIM_RATIO)
        )
        if oversize or (rectangular and near_margin):
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


def _estimate_mask_mean_thickness(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    heights = []
    for x in range(mask.shape[1]):
        ys = np.where(mask[:, x] == 255)[0]
        if ys.size == 0:
            continue
        heights.append(int(ys[-1] - ys[0] + 1))
    return float(np.mean(heights)) if heights else 0.0


def _fallback_black_curve_mask(cropped: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    _, s, v = cv2.split(hsv)
    dark_pixels = (v < 90) & (gray < 85) & (s < 90)
    mask = np.where(dark_pixels, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
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


def _pick_column_y(
    ys: np.ndarray,
    previous_y: int | None,
    height: int,
) -> tuple[
    int | None,
    int | None,
    int | None,
    str | None,
    bool,
    int | None,
    int | None,
    int | None,
    int | None,
    int,
    bool,
]:
    if ys.size == 0:
        return None, None, None, None, False, None, None, None, None, 0, False
    ys_sorted = np.sort(ys)
    y_min = int(ys_sorted[0])
    y_max = int(ys_sorted[-1])
    thickness = int(y_max - y_min + 1)

    y_top = y_min
    y_mid = int(np.median(ys_sorted))
    y_bot = y_max

    runs = 1
    if ys_sorted.size > 1:
        diffs = np.diff(ys_sorted)
        runs = int(np.sum(diffs > 1)) + 1

    candidates = [
        ("top", y_top),
        ("mid", y_mid),
        ("bot", y_bot),
    ]

    valid_candidates: list[tuple[str, int]] = []
    for name, value in candidates:
        if value <= EDGE_GUARD_PX or value >= height - EDGE_GUARD_PX - 1:
            continue
        if (
            name == "bot"
            and thickness >= BASELINE_THICKNESS_PX
            and value >= height - BASELINE_BOTTOM_MARGIN_PX
        ):
            continue
        valid_candidates.append((name, value))

    if not valid_candidates:
        return None, y_min, y_max, None, False, thickness, y_top, y_mid, y_bot, runs, False

    if previous_y is not None and abs(y_top - previous_y) >= SPIKE_DELTA_ABS_PX:
        return (
            y_top,
            y_min,
            y_max,
            "spike_top",
            True,
            thickness,
            y_top,
            y_mid,
            y_bot,
            runs,
            True,
        )

    if previous_y is None:
        pick_name, pick_value = (
            ("top", y_top) if thickness <= THICKNESS_THRESHOLD_PX else ("mid", y_mid)
        )
        if pick_name not in {name for name, _ in valid_candidates}:
            pick_name, pick_value = valid_candidates[0]
        return (
            pick_value,
            y_min,
            y_max,
            pick_name,
            False,
            thickness,
            y_top,
            y_mid,
            y_bot,
            runs,
            False,
        )

    pick_name, pick_value = min(
        valid_candidates,
        key=lambda item: abs(item[1] - previous_y),
    )
    return (
        pick_value,
        y_min,
        y_max,
        pick_name,
        True,
        thickness,
        y_top,
        y_mid,
        y_bot,
        runs,
        False,
    )


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
    mask_ink: np.ndarray | None = None,
    mask_ink_core: np.ndarray | None = None,
    mask_ink_thin: np.ndarray | None = None,
    mask_ink_combined: np.ndarray | None = None,
    mask_pretty: np.ndarray | None = None,
    pick_tops: list[int | None] | None = None,
    pick_mids: list[int | None] | None = None,
    spike_columns: list[bool] | None = None,
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
    mask_ink_path = debug_dir / "mask_ink.png"
    mask_ink_core_path = debug_dir / "mask_ink_core.png"
    mask_ink_thin_path = debug_dir / "mask_ink_thin.png"
    mask_ink_combined_path = debug_dir / "mask_ink_combined.png"
    mask_pretty_path = debug_dir / "mask_pretty.png"
    mask_polyline_path = debug_dir / "mask_polyline.png"
    overlay_path = debug_dir / "overlay.png"
    overlay_marker_path = debug_dir / "overlay_markers.png"
    raw_csv_path = debug_dir / "curve_points.csv"
    filtered_csv_path = debug_dir / "curve_points_filtered.csv"
    filtered_global_csv_path = debug_dir / "curve_points_filtered_global.csv"

    cv2.imwrite(str(crop_path), cropped)
    cv2.imwrite(str(mask_candidate_path), mask_candidate)
    cv2.imwrite(str(mask_raw_path), mask_raw)
    if mask_ink is not None:
        cv2.imwrite(str(mask_ink_path), mask_ink)
    if mask_ink_core is not None:
        cv2.imwrite(str(mask_ink_core_path), mask_ink_core)
    if mask_ink_thin is not None:
        cv2.imwrite(str(mask_ink_thin_path), mask_ink_thin)
    if mask_ink_combined is not None:
        cv2.imwrite(str(mask_ink_combined_path), mask_ink_combined)
    if mask_pretty is not None:
        cv2.imwrite(str(mask_pretty_path), mask_pretty)
    cv2.imwrite(str(mask_polyline_path), mask_polyline)
    marker_overlay = overlay.copy()
    if spike_columns:
        height, width = marker_overlay.shape[:2]
        for idx, is_spike in enumerate(spike_columns):
            if not is_spike or idx >= width:
                continue
            cv2.line(
                marker_overlay,
                (idx, 0),
                (idx, height - 1),
                (255, 0, 255),
                1,
                cv2.LINE_AA,
            )
    _draw_column_markers(
        marker_overlay,
        xs,
        filtered_points,
        column_ranges,
        pick_tops=pick_tops,
        pick_mids=pick_mids,
    )
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
        "mask_ink": str(mask_ink_path) if mask_ink is not None else None,
        "mask_ink_core": str(mask_ink_core_path) if mask_ink_core is not None else None,
        "mask_ink_thin": str(mask_ink_thin_path) if mask_ink_thin is not None else None,
        "mask_ink_combined": (
            str(mask_ink_combined_path) if mask_ink_combined is not None else None
        ),
        "mask_pretty": str(mask_pretty_path) if mask_pretty is not None else None,
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
    *,
    pick_tops: list[int | None] | None = None,
    pick_mids: list[int | None] | None = None,
) -> None:
    height, width = overlay.shape[:2]
    sample_count = min(40, width)
    if sample_count == 0:
        return
    rng = np.random.default_rng(42)
    tail_start = int(width * 0.9)
    tail_indices = np.arange(tail_start, width) if tail_start < width else np.array([])
    base_count = max(sample_count - tail_indices.size, 0)
    base_indices = (
        rng.choice(width, size=base_count, replace=False) if base_count else np.array([])
    )
    sample_indices = np.unique(np.concatenate([base_indices, tail_indices])).astype(int)
    if sample_indices.size > sample_count:
        sample_indices = rng.choice(sample_indices, size=sample_count, replace=False)
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
        if pick_tops and idx < len(pick_tops):
            y_top = pick_tops[idx]
            if y_top is not None:
                y_top = int(max(0, min(height - 1, y_top)))
                cv2.circle(overlay, (x, y_top), 2, (255, 0, 0), -1, cv2.LINE_AA)
        if pick_mids and idx < len(pick_mids):
            y_mid = pick_mids[idx]
            if y_mid is not None:
                y_mid = int(max(0, min(height - 1, y_mid)))
                cv2.circle(overlay, (x, y_mid), 2, (0, 255, 255), -1, cv2.LINE_AA)
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


def _robust_stddev(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(mad * 1.4826)


def _count_consecutive_equals(points: list[int | None]) -> tuple[int, int]:
    longest_run = 0
    current_run = 0
    total_equal = 0
    last_value = None
    for value in points:
        if value is None:
            current_run = 0
            last_value = None
            continue
        if last_value is not None and value == last_value:
            current_run += 1
            total_equal += 1
        else:
            current_run = 1
        if current_run > longest_run:
            longest_run = current_run
        last_value = value
    return total_equal, longest_run


def _sample_column_picks(
    column_ranges: list[tuple[int | None, int | None]],
    pick_modes: list[str | None],
    points: list[int | None],
    sample_size: int = 8,
    *,
    pick_tops: list[int | None] | None = None,
    pick_mids: list[int | None] | None = None,
) -> list[dict]:
    if not column_ranges or not points:
        return []
    width = len(column_ranges)
    sample_size = min(sample_size, width)
    indices = np.linspace(0, width - 1, num=sample_size, dtype=int)
    samples = []
    for idx in indices:
        y_min, y_max = column_ranges[idx]
        samples.append(
            {
                "x": int(idx),
                "y_min": y_min,
                "y_max": y_max,
                "pick": points[idx],
                "mode": pick_modes[idx] if idx < len(pick_modes) else None,
                "y_top": pick_tops[idx] if pick_tops and idx < len(pick_tops) else None,
                "y_mid": pick_mids[idx] if pick_mids and idx < len(pick_mids) else None,
            }
        )
    return samples
