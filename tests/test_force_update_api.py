import pytest
import json
import os
from unittest.mock import patch
from backend.app import app

@pytest.fixture
def client():
    """Create test client"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_force_update_endpoint_success(client):
    """Test /api/force_update returns success"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.return_value = "data/curva.csv"
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ok"] is True
        assert "message" in data

def test_force_update_endpoint_handles_errors(client):
    """Test /api/force_update handles errors gracefully"""
    with patch('backend.app.process_png_to_csv') as mock_process:
        mock_process.side_effect = Exception("Network error")
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["ok"] is False
        assert "error" in data

def test_force_update_get_method(client):
    """Test /api/force_update works with GET method"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.return_value = "data/curva.csv"
        
        response = client.get('/api/force_update')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ok"] is True

def test_curva_csv_created_correctly(client):
    """Test that curva.csv is created with correct format"""
    with patch('backend.utils.extract_png.download_png'), \
         patch('backend.utils.extract_png.extract_green_curve_from_png') as mock_extract:
        
        import pandas as pd
        mock_data = pd.DataFrame({
            "timestamp": ["2025-01-01 12:00:00", "2025-01-01 13:00:00"],
            "value": [1.5, 2.3]
        })
        mock_extract.return_value = mock_data
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 200
        assert os.path.exists("data/curva.csv")
        
        df = pd.read_csv("data/curva.csv")
        assert list(df.columns) == ["timestamp", "value"]
        
        if os.path.exists("data/curva.csv"):
            os.remove("data/curva.csv")
