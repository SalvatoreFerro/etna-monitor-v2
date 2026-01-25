from __future__ import annotations

from dataclasses import dataclass

from .ingv_bands import get_ingv_band_thresholds


@dataclass(frozen=True)
class PlotBandThresholds:
    yellow_mv: float
    red_mv: float


def get_plot_band_thresholds() -> PlotBandThresholds:
    bands_payload = get_ingv_band_thresholds()
    thresholds = bands_payload.get("thresholds_mv") or {}
    yellow_mv = float(thresholds.get("t1") or 1.0)
    red_mv = float(thresholds.get("t2") or max(yellow_mv * 2, yellow_mv + 0.1))
    if red_mv <= yellow_mv:
        red_mv = yellow_mv + 0.1
    return PlotBandThresholds(yellow_mv=yellow_mv, red_mv=red_mv)
