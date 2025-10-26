from functools import lru_cache


@lru_cache(maxsize=1)
def _graph_objects():  # pragma: no cover - thin import wrapper
    import plotly.graph_objects as go  # type: ignore

    return go


def make_tremor_figure(times, values, threshold: float, ingv_mode: bool = False):
    go = _graph_objects()
    fig = go.Figure()

    if ingv_mode:
        fig.add_trace(go.Scatter(
            x=times,
            y=values,
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
            y=values,
            mode="lines",
            name="Tremor",
            line=dict(color='#4ade80', width=2)
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
            font_color='#e6e7ea'
        )

    fig.update_yaxes(type="log", range=[-1, 1])
    return fig
