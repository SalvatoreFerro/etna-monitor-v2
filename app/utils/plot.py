import plotly.graph_objects as go

def make_tremor_figure(times, values, threshold: float):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=values, mode="lines", name="Tremore"))
    fig.add_hline(y=threshold, line_dash="dash")
    fig.update_layout(
        xaxis_title="Tempo",
        yaxis_title="mV (log)",
    )
    fig.update_yaxes(type="log")  # 🔴 requisito EtnaMonitor
    return fig
