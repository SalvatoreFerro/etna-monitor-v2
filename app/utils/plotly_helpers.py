from __future__ import annotations

from collections.abc import Sequence
from math import log10

import plotly.graph_objects as go
from plotly import offline as plotly_offline

from .plot_thresholds import get_plot_band_thresholds

Y_AXIS_MIN_MV = 0.1
MOBILE_PLOT_MARGIN = {"l": 50, "r": 18, "t": 18, "b": 44}
MOBILE_TICK_FONT_SIZE = 10
MOBILE_Y_NTICKS = 6
MOBILE_X_NTICKS = 5
MOBILE_LINE_WIDTH = 3.5
DEFAULT_Y_TICKVALS = [0.1, 0.2, 0.5, 1, 2, 5, 10]
DEFAULT_Y_TICKTEXT = ["10⁻¹", "0.2", "0.5", "1", "2", "5", "10¹"]


def _compute_log_range(plot_values: Sequence[float]) -> tuple[list[float], float]:
    max_y = max(plot_values) if plot_values else Y_AXIS_MIN_MV
    y_max = max(10.0, max_y * 2)
    return [log10(Y_AXIS_MIN_MV), log10(y_max)], y_max


def _build_background_band_shapes(
    *,
    y_min: float,
    y_max: float,
    yellow_mv: float,
    red_mv: float,
) -> list[dict]:
    def _band(y0: float, y1: float, color: str, glow: str) -> list[dict]:
        base_shape = {
            "type": "rect",
            "xref": "paper",
            "yref": "y",
            "x0": 0,
            "x1": 1,
            "y0": y0,
            "y1": y1,
            "layer": "below",
            "line": {"width": 0},
            "fillcolor": color,
        }
        glow_shape = {
            **base_shape,
            "fillcolor": glow,
        }
        return [glow_shape, base_shape]

    yellow_mv = max(y_min, yellow_mv)
    red_mv = max(yellow_mv, red_mv)
    shapes: list[dict] = []
    shapes.extend(_band(y_min, yellow_mv, "rgba(0,255,120,0.10)", "rgba(0,255,140,0.06)"))
    shapes.extend(_band(yellow_mv, red_mv, "rgba(255,215,0,0.10)", "rgba(255,225,80,0.06)"))
    shapes.extend(_band(red_mv, y_max, "rgba(255,80,80,0.12)", "rgba(255,120,120,0.07)"))
    return shapes


def _build_tremor_layout(
    *,
    mode: str,
    shapes: Sequence[dict] | None = None,
) -> dict:
    base_layout = {
        "margin": {"l": 60, "r": 20, "t": 20, "b": 50},
        "hovermode": "x unified",
        "xaxis": {
            "type": "date",
            "title": "",
            "showgrid": True,
            "gridcolor": "#1f2937",
            "linewidth": 1,
            "linecolor": "#334155",
            "hoverformat": "%d/%m %H:%M",
            "tickfont": {"size": 12},
            "ticks": "outside",
            "tickcolor": "#334155",
        },
        "yaxis": {
            "title": "Ampiezza (mV)",
            "type": "log",
            "showgrid": True,
            "gridcolor": "#1f2937",
            "linewidth": 1,
            "linecolor": "#334155",
            "tickfont": {"size": 12},
            "tickvals": DEFAULT_Y_TICKVALS,
            "ticktext": DEFAULT_Y_TICKTEXT,
            "ticksuffix": " mV",
            "exponentformat": "power",
            "minor": {"ticklen": 4, "showgrid": False},
            "zeroline": False,
        },
        "plot_bgcolor": "rgba(0,0,0,0)",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": "#e2e8f0"},
        "hoverlabel": {
            "bgcolor": "rgba(15, 23, 42, 0.92)",
            "bordercolor": "#ef4444",
            "font": {"color": "#f8fafc"},
        },
    }
    if shapes:
        base_layout["shapes"] = list(shapes)

    if mode == "admin":
        base_layout.update(
            {
                "font": {"color": "#0f172a"},
                "plot_bgcolor": "rgba(255,255,255,1)",
                "paper_bgcolor": "rgba(255,255,255,1)",
            }
        )
        base_layout["xaxis"] = {
            **base_layout["xaxis"],
            "gridcolor": "#e2e8f0",
            "linecolor": "#94a3b8",
            "tickcolor": "#94a3b8",
        }
        base_layout["yaxis"] = {
            **base_layout["yaxis"],
            "gridcolor": "#e2e8f0",
            "linecolor": "#94a3b8",
        }

    return base_layout


def _apply_plot_tuning(
    layout: dict,
    plot_values: Sequence[float],
    *,
    add_background_bands: bool,
    mobile_tuning: bool,
) -> dict:
    layout = {**layout}
    log_range, y_max = _compute_log_range(plot_values)
    yaxis = {**(layout.get("yaxis") or {})}
    yaxis["range"] = log_range
    layout["yaxis"] = yaxis

    if add_background_bands:
        thresholds = get_plot_band_thresholds()
        existing_shapes = list(layout.get("shapes") or [])
        band_shapes = _build_background_band_shapes(
            y_min=Y_AXIS_MIN_MV,
            y_max=y_max,
            yellow_mv=thresholds.yellow_mv,
            red_mv=thresholds.red_mv,
        )
        layout["shapes"] = [*band_shapes, *existing_shapes]

    if mobile_tuning:
        meta = {**(layout.get("meta") or {})}
        mobile_overrides = {**(meta.get("mobileOverrides") or {})}
        mobile_overrides["margin"] = MOBILE_PLOT_MARGIN
        mobile_overrides["yaxis"] = {
            **(mobile_overrides.get("yaxis") or {}),
            "range": log_range,
            "tickfont": {"size": MOBILE_TICK_FONT_SIZE},
            "nticks": MOBILE_Y_NTICKS,
            "automargin": True,
        }
        mobile_overrides["xaxis"] = {
            **(mobile_overrides.get("xaxis") or {}),
            "tickfont": {"size": MOBILE_TICK_FONT_SIZE},
            "nticks": MOBILE_X_NTICKS,
        }
        mobile_overrides["lineWidth"] = MOBILE_LINE_WIDTH
        meta["mobileOverrides"] = mobile_overrides
        layout["meta"] = meta

    return layout


def build_tremor_figure(
    clean_pairs: Sequence[tuple[str, float]],
    *,
    mode: str,
    shapes: Sequence[dict] | None = None,
    min_points: int = 10,
    eps: float = 1e-2,
    add_background_bands: bool = False,
) -> go.Figure | None:
    layout = _build_tremor_layout(mode=mode, shapes=shapes)
    line = {
        "color": "#4ade80" if mode == "home" else "#111",
        "width": 2.4 if mode == "home" else 2,
        "shape": "spline" if mode == "home" else "linear",
        "smoothing": 1.15 if mode == "home" else 0,
    }
    trace_kwargs = None
    name = "Tremore" if mode == "home" else "RMS"
    if mode == "home":
        trace_kwargs = {
            "fill": "tozeroy",
            "fillcolor": "rgba(74, 222, 128, 0.08)",
            "hovertemplate": "<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>",
            "showlegend": False,
        }
    return build_plotly_figure_from_pairs(
        clean_pairs,
        line=line,
        layout=layout,
        name=name,
        min_points=min_points,
        eps=eps,
        trace_kwargs=trace_kwargs,
        add_background_bands=add_background_bands,
        mobile_tuning=mode == "home",
    )


def build_plotly_html_from_pairs(
    clean_pairs: Sequence[tuple[str, float]],
    *,
    include_plotlyjs: str | bool,
    line: dict,
    layout: dict,
    name: str = "RMS",
    mode: str = "lines",
    min_points: int = 10,
    eps: float = 1e-2,
    trace_kwargs: dict | None = None,
    add_background_bands: bool = False,
    mobile_tuning: bool = False,
) -> str | None:
    if len(clean_pairs) < min_points:
        return None
    plot_timestamps = [pair[0] for pair in clean_pairs]
    plot_values = [max(pair[1], eps) for pair in clean_pairs]
    trace_options = {
        "x": plot_timestamps,
        "y": plot_values,
        "mode": mode,
        "line": line,
        "name": name,
    }
    if trace_kwargs:
        trace_options.update(trace_kwargs)
    tuned_layout = _apply_plot_tuning(
        layout,
        plot_values,
        add_background_bands=add_background_bands,
        mobile_tuning=mobile_tuning,
    )
    fig = go.Figure(data=[go.Scatter(**trace_options)], layout=tuned_layout)
    return plotly_offline.plot(fig, include_plotlyjs=include_plotlyjs, output_type="div")


def build_plotly_figure_from_pairs(
    clean_pairs: Sequence[tuple[str, float]],
    *,
    line: dict,
    layout: dict,
    name: str = "RMS",
    mode: str = "lines",
    min_points: int = 10,
    eps: float = 1e-2,
    trace_kwargs: dict | None = None,
    add_background_bands: bool = False,
    mobile_tuning: bool = False,
) -> go.Figure | None:
    if len(clean_pairs) < min_points:
        return None
    plot_timestamps = [pair[0] for pair in clean_pairs]
    plot_values = [max(pair[1], eps) for pair in clean_pairs]
    trace_options = {
        "x": plot_timestamps,
        "y": plot_values,
        "mode": mode,
        "line": line,
        "name": name,
    }
    if trace_kwargs:
        trace_options.update(trace_kwargs)
    tuned_layout = _apply_plot_tuning(
        layout,
        plot_values,
        add_background_bands=add_background_bands,
        mobile_tuning=mobile_tuning,
    )
    return go.Figure(data=[go.Scatter(**trace_options)], layout=tuned_layout)
