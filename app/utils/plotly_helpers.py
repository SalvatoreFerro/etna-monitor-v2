from __future__ import annotations

from collections.abc import Sequence

import plotly.graph_objects as go
from plotly import offline as plotly_offline


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
    fig = go.Figure(data=[go.Scatter(**trace_options)], layout=layout)
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
    return go.Figure(data=[go.Scatter(**trace_options)], layout=layout)
