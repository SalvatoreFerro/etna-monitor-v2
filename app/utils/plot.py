import plotly.graph_objects as go

def make_tremor_figure(times, values, threshold: float):
    fig = go.Figure()
    
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
        margin=dict(l=0, r=0, t=30, b=0)
    )
    
    fig.update_yaxes(type="log")
    return fig
