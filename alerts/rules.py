import pandas as pd

def is_alert(series: pd.Series, window: int, threshold: float) -> bool:
    """Restituisce True se la media degli ultimi `window` punti supera `threshold`."""
    if len(series) < window:
        return False
    return series.tail(window).mean() > threshold
