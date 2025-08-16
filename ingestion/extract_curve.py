from io import BytesIO
from PIL import Image
import pandas as pd
import numpy as np

# NOTE: placeholder – in produzione usa la tua pipeline HSV approvata
def extract_series_from_png(png_bytes: bytes) -> pd.DataFrame:
    # Dummy curve (sostituire con estrazione reale)
    img = Image.open(BytesIO(png_bytes))
    w, h = img.size
    x = pd.date_range(periods=200, freq="min", end=pd.Timestamp.utcnow())
    y = np.clip(np.linspace(0.1, 5.0, 200), 0.1, None)
    return pd.DataFrame({"time": x, "value_mv": y})
