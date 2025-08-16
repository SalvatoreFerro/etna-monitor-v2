import pytest
import pandas as pd
import os
import numpy as np
from unittest.mock import patch, MagicMock
from backend.utils.extract_png import extract_green_curve_from_png, clean_and_save_data, process_png_to_csv

def test_extract_green_curve_creates_dataframe():
    """Test that PNG processing creates a valid DataFrame"""
    mock_png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    
    with patch('cv2.imdecode') as mock_decode, \
         patch('cv2.cvtColor') as mock_cvt, \
         patch('cv2.inRange') as mock_range:
        
        mock_decode.return_value = MagicMock()
        mock_cvt.return_value = MagicMock()
        mock_range.return_value = MagicMock()
        mock_range.return_value.shape = (100, 200)
        
        mock_mask = np.zeros((100, 200))
        mock_mask[50, 100] = 255
        
        with patch('numpy.where') as mock_where:
            mock_where.return_value = ([50],)
            
            df = extract_green_curve_from_png(mock_png)
            
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == ["timestamp", "value"]

def test_clean_and_save_data_creates_csv():
    """Test that data cleaning creates curva.csv correctly"""
    test_data = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=5, freq="H"),
        "value": [0.1, 1.0, 10.0, 0.5, 2.0]
    })
    
    output_path = "test_data/test_curva.csv"
    
    try:
        result_path = clean_and_save_data(test_data, output_path)
        
        assert os.path.exists(result_path)
        
        df_loaded = pd.read_csv(result_path)
        assert len(df_loaded) == 5
        assert list(df_loaded.columns) == ["timestamp", "value"]
        
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)
        if os.path.exists("test_data"):
            os.rmdir("test_data")

def test_process_png_to_csv_integration():
    """Test complete pipeline with mocked PNG download"""
    with patch('backend.utils.extract_png.download_png') as mock_download, \
         patch('backend.utils.extract_png.extract_green_curve_from_png') as mock_extract:
        
        mock_download.return_value = b'fake_png_data'
        mock_data = pd.DataFrame({
            "timestamp": ["2025-01-01 12:00:00", "2025-01-01 13:00:00"],
            "value": [1.5, 2.3]
        })
        mock_extract.return_value = mock_data
        
        output_path = "test_data/integration_test.csv"
        
        try:
            result = process_png_to_csv("http://test.url", output_path)
            assert result == output_path
            assert os.path.exists(output_path)
            
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)
            if os.path.exists("test_data"):
                os.rmdir("test_data")
