"""Tests for archive API endpoints."""

import io
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask

from backend.app import app as backend_app


@pytest.fixture
def client():
    """Create a test client for the backend app."""
    backend_app.config['TESTING'] = True
    with backend_app.test_client() as client:
        yield client


@pytest.fixture
def temp_archive_dir():
    """Create a temporary directory for archive tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_archive_manager(temp_archive_dir):
    """Mock the archive manager with a temporary directory."""
    with patch('backend.app.archive_manager') as mock_manager:
        from backend.utils.archive import ArchiveManager
        real_manager = ArchiveManager(base_path=temp_archive_dir)
        
        # Configure mock to use real manager methods
        mock_manager.list_archives = real_manager.list_archives
        mock_manager.get_archive = real_manager.get_archive
        mock_manager.save_daily_graph = real_manager.save_daily_graph
        mock_manager.archive_exists = real_manager.archive_exists
        
        yield real_manager


def test_list_archives_empty(client, mock_archive_manager):
    """Test listing archives when none exist."""
    response = client.get('/api/archives/list')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['ok'] is True
    assert data['count'] == 0
    assert data['archives'] == []


def test_list_archives_with_data(client, mock_archive_manager):
    """Test listing archives with data."""
    # Create test archives
    dates = [
        datetime(2025, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 11, 2, tzinfo=timezone.utc),
        datetime(2025, 11, 3, tzinfo=timezone.utc),
    ]
    
    for date in dates:
        mock_archive_manager.save_daily_graph(b"test_data", date=date)
    
    response = client.get('/api/archives/list')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['ok'] is True
    assert data['count'] == 3
    assert len(data['archives']) == 3
    
    # Verify dates are sorted descending
    assert data['archives'][0]['date'] == '2025-11-03'
    assert data['archives'][1]['date'] == '2025-11-02'
    assert data['archives'][2]['date'] == '2025-11-01'


def test_list_archives_with_date_filter(client, mock_archive_manager):
    """Test listing archives with date filters."""
    dates = [
        datetime(2025, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 11, 5, tzinfo=timezone.utc),
        datetime(2025, 11, 10, tzinfo=timezone.utc),
    ]
    
    for date in dates:
        mock_archive_manager.save_daily_graph(b"test_data", date=date)
    
    # Filter by start date
    response = client.get('/api/archives/list?start_date=2025-11-05')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['ok'] is True
    assert data['count'] == 2
    assert data['archives'][0]['date'] == '2025-11-10'
    assert data['archives'][1]['date'] == '2025-11-05'


def test_list_archives_invalid_date_format(client, mock_archive_manager):
    """Test listing archives with invalid date format."""
    response = client.get('/api/archives/list?start_date=invalid-date')
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['ok'] is False
    assert 'Invalid start_date format' in data['error']


def test_get_archive_graph_success(client, mock_archive_manager):
    """Test retrieving an archived graph."""
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)
    png_data = b"fake_png_data_content"
    
    mock_archive_manager.save_daily_graph(png_data, date=date)
    
    response = client.get('/api/archives/graph/2025-11-04')
    assert response.status_code == 200
    assert response.mimetype == 'image/png'
    assert response.data == png_data


def test_get_archive_graph_not_found(client, mock_archive_manager):
    """Test retrieving non-existent archive."""
    response = client.get('/api/archives/graph/2025-11-04')
    assert response.status_code == 404
    
    data = response.get_json()
    assert data['ok'] is False
    assert 'Archive not found' in data['error']


def test_get_archive_graph_invalid_date_format(client, mock_archive_manager):
    """Test retrieving archive with invalid date format."""
    response = client.get('/api/archives/graph/invalid-date')
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['ok'] is False
    assert 'Invalid date format' in data['error']


def test_get_archive_data_success(client, mock_archive_manager):
    """Test retrieving processed data from archive."""
    import cv2
    import numpy as np
    
    # Create a simple test PNG with green pixels
    height, width = 400, 1024
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[200:205, 120:width - 50] = (0, 255, 0)  # Green pixels
    
    success, buffer = cv2.imencode(".png", img)
    assert success
    png_data = buffer.tobytes()
    
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)
    mock_archive_manager.save_daily_graph(png_data, date=date)
    
    response = client.get('/api/archives/data/2025-11-04')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['ok'] is True
    assert data['date'] == '2025-11-04'
    assert data['count'] > 0
    assert isinstance(data['data'], list)
    
    # Verify data structure
    if len(data['data']) > 0:
        first_point = data['data'][0]
        assert 'timestamp' in first_point
        assert 'value' in first_point


def test_get_archive_data_not_found(client, mock_archive_manager):
    """Test retrieving data from non-existent archive."""
    response = client.get('/api/archives/data/2025-11-04')
    assert response.status_code == 404
    
    data = response.get_json()
    assert data['ok'] is False
    assert 'Archive not found' in data['error']


def test_get_archive_data_invalid_date_format(client, mock_archive_manager):
    """Test retrieving data with invalid date format."""
    response = client.get('/api/archives/data/invalid-date')
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['ok'] is False
    assert 'Invalid date format' in data['error']


def test_force_update_endpoint_still_works(client):
    """Ensure force_update endpoint is not broken."""
    with patch('backend.app.process_png_to_csv') as mock_process:
        mock_process.return_value = {
            'rows': 100,
            'first_ts': '2025-11-04T00:00:00Z',
            'last_ts': '2025-11-04T12:00:00Z',
            'output_path': '/tmp/curva.csv'
        }
        
        response = client.get('/api/force_update')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['ok'] is True
        assert 'message' in data
