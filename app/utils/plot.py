from functools import lru_cache
import math


@lru_cache(maxsize=1)
def _graph_objects():  # pragma: no cover - thin import wrapper
    import plotly.graph_objects as go  # type: ignore

    return go


def _log_range(values):
    positive = [float(value) for value in values if value and float(value) > 0]
    if not positive:
        return [-1, 1]
    min_val = min(positive)
    max_val = max(positive)
    min_log = math.floor(math.log10(min_val))
    max_log = math.ceil(math.log10(max_val))
    if min_log == max_log:
        max_log += 1
    return [min_log, max_log]


def make_tremor_figure(
    times,
    raw_values,
    threshold: float,
    smooth_values=None,
    ingv_mode: bool = False,
    mobile_tuning: bool = False,
):
    go = _graph_objects()
    fig = go.Figure()
    has_smooth = smooth_values is not None
    smooth_values = smooth_values if has_smooth else []
    y_range = _log_range(list(raw_values) + list(smooth_values))

    if ingv_mode:
        fig.add_trace(go.Scatter(
            x=times,
            y=raw_values,
            mode="lines",
            name="RMS",
            line=dict(color='#00AA00', width=1),
            showlegend=False
        ))

        fig.add_hline(
            y=threshold,
            line_dash="solid",
            line_color="#FF0000",
            line_width=1
        )

        fig.update_layout(
            title="ECBD - RMS (UTC Time)",
            title_font=dict(size=14, color='black'),
            xaxis_title="",
            yaxis_title="",
            template="plotly_white",
            plot_bgcolor='white',
            paper_bgcolor='white',
            font=dict(family="Arial", size=10, color="black"),
            margin=dict(l=60, r=20, t=40, b=40),
            showlegend=False,
            xaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor='lightgray',
                tickangle=-90,
                tickformat='%d/%m\n%H:%M'
            ),
            yaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor='lightgray',
                tickvals=[0.1, 1, 10],
                ticktext=['10⁻¹', '10⁰', '10¹']
            )
        )
    else:
        fig.add_trace(go.Scatter(
            x=times,
            y=raw_values,
            mode="lines",
            name="RAW (picchi reali)",
            line=dict(color='#4ade80', width=2)
        ))
        if has_smooth:
            fig.add_trace(go.Scatter(
                x=times,
                y=smooth_values,
                mode="lines",
                name="Trend (smoothed)",
                line=dict(color='#22d3ee', width=2, dash="solid"),
                opacity=0.8
            ))

        fig.add_hline(
            y=threshold,
            line_dash="dash",
            line_color="#ef4444",
            annotation_text=f"Threshold: {threshold} mV"
        )

        fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Tremor (mV)",
            template="plotly_dark",
            margin=dict(l=0, r=0, t=30, b=0),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='#e6e7ea',
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(color="#e6e7ea")
            )
        )

    fig.update_yaxes(
        type="log",
        range=y_range,
        tickvals=[0.1, 1, 10],
        ticktext=['10⁻¹', '10⁰', '10¹']
    )

    if mobile_tuning:
        fig.update_layout(
            autosize=True,
            margin=dict(l=48, r=12, t=18, b=42),
            font=dict(size=11),
        )
        fig.update_xaxes(tickfont=dict(size=10))
        fig.update_yaxes(tickfont=dict(size=10), title_standoff=6)
        fig.update_traces(
            fill=None,
            mode="lines",
            line=dict(width=1.0),
            selector=dict(mode="lines"),
        )

    return fig
