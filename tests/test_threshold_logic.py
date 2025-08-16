import pandas as pd
from alerts.rules import is_alert

def test_alert_window_logic():
    s = pd.Series([1, 2, 3, 4, 5])
    assert is_alert(s, window=3, threshold=3.5) is True
    assert is_alert(s, window=3, threshold=4.6) is False
