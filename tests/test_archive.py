"""Tests for the archive module."""

import gzip
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.utils.archive import ArchiveManager


@pytest.fixture
def temp_archive_dir():
    """Create a temporary directory for archive tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def archive_manager(temp_archive_dir):
    """Create an ArchiveManager instance with a temporary directory."""
    return ArchiveManager(base_path=temp_archive_dir, retention_days=90)


def test_archive_manager_initialization(temp_archive_dir):
    """Test ArchiveManager initialization."""
    manager = ArchiveManager(base_path=temp_archive_dir, retention_days=30)
    assert manager.base_path == Path(temp_archive_dir)
    assert manager.retention_days == 30
    assert manager.base_path.exists()


def test_get_archive_path(archive_manager):
    """Test archive path generation."""
    date = datetime(2025, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    path = archive_manager._get_archive_path(date, compressed=False)
    assert path.name == "etna_20251104.png"
    assert "2025" in str(path)
    assert "11" in str(path)
    assert "04" in str(path)

    path_compressed = archive_manager._get_archive_path(date, compressed=True)
    assert path_compressed.name == "etna_20251104.png.gz"


def test_save_daily_graph_uncompressed(archive_manager):
    """Test saving uncompressed graph."""
    png_data = b"fake_png_data_12345"
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    archive_path = archive_manager.save_daily_graph(
        png_data, date=date, compress=False
    )

    assert archive_path.exists()
    assert archive_path.name == "etna_20251104.png"

    # Verify content
    with open(archive_path, "rb") as f:
        saved_data = f.read()
    assert saved_data == png_data


def test_save_daily_graph_compressed(archive_manager):
    """Test saving compressed graph."""
    png_data = b"fake_png_data_12345_this_is_longer_data_for_compression"
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    archive_path = archive_manager.save_daily_graph(
        png_data, date=date, compress=True
    )

    assert archive_path.exists()
    assert archive_path.name == "etna_20251104.png.gz"

    # Verify content is compressed
    with open(archive_path, "rb") as f:
        saved_data = f.read()
    assert saved_data != png_data  # Should be different (compressed)

    # Verify we can decompress it
    decompressed = gzip.decompress(saved_data)
    assert decompressed == png_data


def test_save_daily_graph_default_date(archive_manager):
    """Test saving graph with default (current) date."""
    png_data = b"fake_png_data"

    archive_path = archive_manager.save_daily_graph(png_data)

    assert archive_path.exists()
    # Should use today's date
    today = datetime.now(timezone.utc)
    expected_filename = f"etna_{today.strftime('%Y%m%d')}.png"
    assert archive_path.name == expected_filename


def test_save_daily_graph_overwrites_existing(archive_manager):
    """Test that saving overwrites existing archives."""
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)
    first_data = b"first_version"
    second_data = b"second_version"

    # Save first version
    archive_manager.save_daily_graph(first_data, date=date)

    # Save second version
    archive_path = archive_manager.save_daily_graph(second_data, date=date)

    # Verify only second version exists
    with open(archive_path, "rb") as f:
        saved_data = f.read()
    assert saved_data == second_data


def test_cleanup_old_archives(archive_manager):
    """Test cleanup of old archives."""
    # Create archives with different ages
    today = datetime.now(timezone.utc)
    old_date = today - timedelta(days=100)  # Beyond retention
    recent_date = today - timedelta(days=30)  # Within retention

    archive_manager.save_daily_graph(b"old_data", date=old_date)
    archive_manager.save_daily_graph(b"recent_data", date=recent_date)

    # Verify both exist
    assert archive_manager.archive_exists(old_date)
    assert archive_manager.archive_exists(recent_date)

    # Run cleanup
    deleted_count = archive_manager.cleanup_old_archives()

    # Verify old archive is deleted, recent is kept
    assert deleted_count == 1
    assert not archive_manager.archive_exists(old_date)
    assert archive_manager.archive_exists(recent_date)


def test_cleanup_with_negative_retention(temp_archive_dir):
    """Test that cleanup is disabled when retention_days is negative."""
    manager = ArchiveManager(base_path=temp_archive_dir, retention_days=-1)

    old_date = datetime.now(timezone.utc) - timedelta(days=100)
    manager.save_daily_graph(b"data", date=old_date)

    deleted_count = manager.cleanup_old_archives()
    assert deleted_count == 0
    assert manager.archive_exists(old_date)


def test_list_archives_empty(archive_manager):
    """Test listing archives when none exist."""
    archives = archive_manager.list_archives()
    assert archives == []


def test_list_archives(archive_manager):
    """Test listing archived graphs."""
    dates = [
        datetime(2025, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 11, 2, tzinfo=timezone.utc),
        datetime(2025, 11, 3, tzinfo=timezone.utc),
    ]

    for date in dates:
        archive_manager.save_daily_graph(b"test_data", date=date)

    archives = archive_manager.list_archives()

    assert len(archives) == 3
    # Should be sorted by date descending
    assert archives[0]["date"] == "2025-11-03"
    assert archives[1]["date"] == "2025-11-02"
    assert archives[2]["date"] == "2025-11-01"

    # Check metadata
    for archive in archives:
        assert "path" in archive
        assert "size" in archive
        assert "compressed" in archive
        assert "modified" in archive
        assert archive["size"] > 0


def test_list_archives_with_date_filter(archive_manager):
    """Test listing archives with date filters."""
    dates = [
        datetime(2025, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 11, 5, tzinfo=timezone.utc),
        datetime(2025, 11, 10, tzinfo=timezone.utc),
    ]

    for date in dates:
        archive_manager.save_daily_graph(b"test_data", date=date)

    # Filter by start date
    archives = archive_manager.list_archives(
        start_date=datetime(2025, 11, 5, tzinfo=timezone.utc)
    )
    assert len(archives) == 2
    assert archives[0]["date"] == "2025-11-10"
    assert archives[1]["date"] == "2025-11-05"

    # Filter by end date
    archives = archive_manager.list_archives(
        end_date=datetime(2025, 11, 5, tzinfo=timezone.utc)
    )
    assert len(archives) == 2
    assert archives[0]["date"] == "2025-11-05"
    assert archives[1]["date"] == "2025-11-01"

    # Filter by range
    archives = archive_manager.list_archives(
        start_date=datetime(2025, 11, 2, tzinfo=timezone.utc),
        end_date=datetime(2025, 11, 8, tzinfo=timezone.utc),
    )
    assert len(archives) == 1
    assert archives[0]["date"] == "2025-11-05"


def test_get_archive(archive_manager):
    """Test retrieving archived graph."""
    png_data = b"test_png_data_content"
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    archive_manager.save_daily_graph(png_data, date=date)

    retrieved_data = archive_manager.get_archive(date)
    assert retrieved_data == png_data


def test_get_archive_compressed(archive_manager):
    """Test retrieving compressed archived graph."""
    png_data = b"test_png_data_content_for_compression"
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    archive_manager.save_daily_graph(png_data, date=date, compress=True)

    # Should decompress automatically
    retrieved_data = archive_manager.get_archive(date)
    assert retrieved_data == png_data


def test_get_archive_not_found(archive_manager):
    """Test retrieving non-existent archive."""
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)
    retrieved_data = archive_manager.get_archive(date)
    assert retrieved_data is None


def test_archive_exists(archive_manager):
    """Test checking if archive exists."""
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    assert not archive_manager.archive_exists(date)

    archive_manager.save_daily_graph(b"data", date=date)

    assert archive_manager.archive_exists(date)


def test_multiple_saves_same_day(archive_manager):
    """Test that multiple saves on the same day only keep the latest."""
    date = datetime(2025, 11, 4, tzinfo=timezone.utc)

    # Save multiple times
    for i in range(3):
        data = f"version_{i}".encode()
        archive_manager.save_daily_graph(data, date=date)

    # Should only have the latest version
    retrieved = archive_manager.get_archive(date)
    assert retrieved == b"version_2"

    # Should only list one archive for that date
    archives = archive_manager.list_archives()
    assert len(archives) == 1


def test_environment_variable_defaults():
    """Test that environment variables are used for defaults."""
    os.environ["ARCHIVE_BASE_PATH"] = "/tmp/test_archives"
    os.environ["ARCHIVE_RETENTION_DAYS"] = "60"

    try:
        manager = ArchiveManager()
        assert str(manager.base_path) == "/tmp/test_archives"
        assert manager.retention_days == 60
    finally:
        del os.environ["ARCHIVE_BASE_PATH"]
        del os.environ["ARCHIVE_RETENTION_DAYS"]
