import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import cv2
import numpy as np
import pandas as pd

from backend.utils.extract_png import extract_green_curve_from_png, clean_and_save_data, process_png_to_csv

def test_extract_green_curve_creates_dataframe():
    """Test that PNG processing creates a valid DataFrame"""
    height, width = 400, 1024
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[200:205, 120:width - 50] = (0, 255, 0)

    success, buffer = cv2.imencode(".png", img)
    assert success
    png_bytes = buffer.tobytes()

    end_time = datetime(2025, 1, 8, 0, 0, tzinfo=timezone.utc)
    df = extract_green_curve_from_png(
        png_bytes,
        end_time=end_time,
        duration=timedelta(days=7),
    )

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["timestamp", "value"]
    assert not df.empty
    assert df["timestamp"].min() >= end_time - timedelta(days=7)
    assert df["timestamp"].max() == end_time

def test_clean_and_save_data_creates_csv():
    """Test that data cleaning creates curva.csv correctly"""
    test_data = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=5, freq="H"),
        "value": [0.1, 1.0, 10.0, 0.5, 2.0]
    })

    output_path = "test_data/test_curva.csv"

    try:
        result_path, cleaned_df = clean_and_save_data(test_data, output_path)

        assert os.path.exists(result_path)
        assert len(cleaned_df) == 5
        assert cleaned_df["timestamp"].dt.tz is not None

        df_loaded = pd.read_csv(result_path)
        assert len(df_loaded) == 5
        assert list(df_loaded.columns) == ["timestamp", "value"]
        assert df_loaded["timestamp"].str.endswith("Z").all()

    finally:
        if os.path.exists(output_path):
            os.remove(output_path)
        if os.path.exists("test_data"):
            os.rmdir("test_data")

def test_process_png_to_csv_integration():
    """Test complete pipeline with mocked PNG download"""
    with patch('backend.utils.extract_png.download_png') as mock_download, \
         patch('backend.utils.extract_png.extract_green_curve_from_png') as mock_extract:

        reference_time = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
        mock_download.return_value = (b'fake_png_data', reference_time)
        mock_data = pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2025-01-01T12:00:00+00:00",
                "2025-01-01T13:00:00+00:00"
            ]),
            "value": [1.5, 2.3]
        })
        mock_data.attrs["metadata"] = {
            "pixel_columns": 894,
            "start_time": reference_time - timedelta(days=7),
            "end_time": reference_time,
            "duration_seconds": timedelta(days=7).total_seconds(),
            "interval_seconds": 300,
        }
        mock_extract.return_value = mock_data

        output_path = "test_data/integration_test.csv"

        try:
            result = process_png_to_csv("http://test.url", output_path)
            assert result["output_path"] == output_path
            assert result["rows"] == 2
            assert result["last_ts"].endswith("Z")
            assert os.path.exists(output_path)

        finally:
            if os.path.exists(output_path):
                os.remove(output_path)
            if os.path.exists("test_data"):
                os.rmdir("test_data")
