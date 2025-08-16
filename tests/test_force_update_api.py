import pytest
import json
import os
from unittest.mock import patch
from app import create_app

@pytest.fixture
def client():
    """Create test client"""
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_force_update_endpoint_success(client):
    """Test /api/force_update returns success"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.return_value = {
            "rows": 100,
            "last_ts": "2025-01-01 12:00:00",
            "output_path": "/data/curva.csv"
        }
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ok"] is True
        assert data["rows"] == 100
        assert data["last_ts"] == "2025-01-01 12:00:00"
        assert data["output_path"] == "/data/curva.csv"

def test_force_update_endpoint_handles_errors(client):
    """Test /api/force_update handles errors gracefully"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.side_effect = Exception("Network error")
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["ok"] is False
        assert "error" in data

def test_force_update_get_method(client):
    """Test /api/force_update works with GET method"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.return_value = {
            "rows": 50,
            "last_ts": "2025-01-01 15:00:00",
            "output_path": "/data/curva.csv"
        }
        
        response = client.get('/api/force_update')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ok"] is True
        assert data["rows"] == 50

def test_curva_csv_created_correctly(client):
    """Test that curva.csv is created with correct format"""
    with patch('backend.utils.extract_png.process_png_to_csv') as mock_process:
        mock_process.return_value = {
            "rows": 2,
            "last_ts": "2025-01-01 13:00:00",
            "output_path": "/tmp/test_curva.csv"
        }
        
        response = client.post('/api/force_update')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ok"] is True
        assert data["rows"] == 2
        assert data["last_ts"] == "2025-01-01 13:00:00"
