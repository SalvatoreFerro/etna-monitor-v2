"""Tests for the background CSV updater in startup.py"""

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_background_updater_disabled_by_default():
    """Test that the background updater is disabled when ENABLE_BACKGROUND_UPDATER is not set."""
    import startup
    
    # Clear the environment variable if set
    os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)
    
    # Get initial thread count
    initial_threads = threading.active_count()
    
    # Call the function
    startup._start_background_updater()
    
    # Wait a moment for any thread to start
    time.sleep(0.1)
    
    # Verify no new thread was created
    assert threading.active_count() == initial_threads


def test_background_updater_enabled_with_true():
    """Test that the background updater starts when ENABLE_BACKGROUND_UPDATER is set to true."""
    import startup
    
    os.environ["ENABLE_BACKGROUND_UPDATER"] = "true"
    os.environ["CSV_UPDATE_INTERVAL"] = "10"
    
    try:
        # Get initial thread count
        initial_threads = threading.active_count()
        
        # Mock the csv_updater to prevent actual execution
        with patch("scripts.csv_updater.update_with_retries") as mock_update:
            # Call the function
            startup._start_background_updater()
            
            # Wait for thread to start
            time.sleep(0.2)
            
            # Verify a new thread was created
            assert threading.active_count() > initial_threads
            
            # Find the csv-updater thread
            csv_thread = None
            for thread in threading.enumerate():
                if thread.name == "csv-updater":
                    csv_thread = thread
                    break
            
            assert csv_thread is not None
            assert csv_thread.daemon is True
    finally:
        os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)
        os.environ.pop("CSV_UPDATE_INTERVAL", None)


def test_background_updater_enabled_with_variations():
    """Test that the background updater recognizes various true values."""
    import startup
    
    for value in ["1", "true", "True", "TRUE", "yes", "YES"]:
        os.environ["ENABLE_BACKGROUND_UPDATER"] = value
        
        try:
            initial_threads = threading.active_count()
            
            with patch("scripts.csv_updater.update_with_retries"):
                startup._start_background_updater()
                time.sleep(0.1)
                
                # Should have started a thread
                assert threading.active_count() > initial_threads
                
                # Clean up by waiting for thread to be marked as daemon
                time.sleep(0.1)
        finally:
            os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)


def test_background_updater_disabled_with_false_values():
    """Test that the background updater doesn't start with false-equivalent values."""
    import startup
    
    for value in ["0", "false", "False", "FALSE", "no", "NO", "off", "disabled"]:
        os.environ["ENABLE_BACKGROUND_UPDATER"] = value
        
        try:
            initial_threads = threading.active_count()
            
            startup._start_background_updater()
            time.sleep(0.1)
            
            # Should NOT have started a thread
            assert threading.active_count() == initial_threads
        finally:
            os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)


def test_background_updater_invalid_interval():
    """Test that the background updater uses default interval when CSV_UPDATE_INTERVAL is invalid."""
    import startup
    
    os.environ["ENABLE_BACKGROUND_UPDATER"] = "true"
    os.environ["CSV_UPDATE_INTERVAL"] = "invalid"
    
    try:
        with patch("scripts.csv_updater.update_with_retries"):
            # Should not raise an exception, should use default
            startup._start_background_updater()
            time.sleep(0.1)
    finally:
        os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)
        os.environ.pop("CSV_UPDATE_INTERVAL", None)


def test_background_updater_reads_environment_variables():
    """Test that the background updater reads the correct environment variables."""
    import startup
    from pathlib import Path
    
    os.environ["ENABLE_BACKGROUND_UPDATER"] = "true"
    os.environ["CSV_UPDATE_INTERVAL"] = "5"
    os.environ["INGV_URL"] = "https://example.com/test.png"
    os.environ["INGV_COLORED_URL"] = "https://example.com/colored.png"
    os.environ["CURVA_CSV_PATH"] = "/tmp/test.csv"
    
    try:
        with patch("scripts.csv_updater.update_with_retries") as mock_update:
            mock_update.return_value = {"ok": True, "updated": True}
            
            startup._start_background_updater()
            
            # Wait for the thread to make at least one call to the updater
            time.sleep(0.5)
            
            # Verify the updater was called with the correct parameters
            assert mock_update.call_count >= 1
            
            # Check the arguments of the first call
            call_args = mock_update.call_args
            assert call_args is not None
            
            # Verify keyword arguments
            kwargs = call_args.kwargs
            assert kwargs["ingv_url"] == "https://example.com/test.png"
            assert kwargs["colored_url"] == "https://example.com/colored.png"
            assert kwargs["csv_path"] == Path("/tmp/test.csv")
            
    finally:
        os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)
        os.environ.pop("CSV_UPDATE_INTERVAL", None)
        os.environ.pop("INGV_URL", None)
        os.environ.pop("INGV_COLORED_URL", None)
        os.environ.pop("CURVA_CSV_PATH", None)


def test_background_updater_exception_handling():
    """Test that the background updater continues running after exceptions."""
    import startup
    
    os.environ["ENABLE_BACKGROUND_UPDATER"] = "true"
    os.environ["CSV_UPDATE_INTERVAL"] = "1"
    
    try:
        with patch("scripts.csv_updater.update_with_retries") as mock_update:
            # Make the updater raise an exception
            mock_update.side_effect = Exception("Test exception")
            
            # Start the updater
            startup._start_background_updater()
            
            # Wait for the thread to potentially call the updater
            time.sleep(0.3)
            
            # The thread should still be alive despite the exception
            csv_thread = None
            for thread in threading.enumerate():
                if thread.name == "csv-updater":
                    csv_thread = thread
                    break
            
            assert csv_thread is not None
            assert csv_thread.is_alive()
    finally:
        os.environ.pop("ENABLE_BACKGROUND_UPDATER", None)
        os.environ.pop("CSV_UPDATE_INTERVAL", None)
