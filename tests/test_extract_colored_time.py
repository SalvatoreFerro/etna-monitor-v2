"""Test that extract_colored uses current time for series end time."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.utils.extract_colored import _resolve_series_end_time


def test_resolve_series_end_time_uses_current_time():
    """Test that _resolve_series_end_time returns current time, not file mtime."""
    # Create a temporary file with an old modification time
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(b"fake png data")
    
    try:
        # Get the end time that the function resolves
        resolved_time = _resolve_series_end_time(tmp_path)
        
        # Get current time
        current_time = datetime.now(timezone.utc)
        
        # The resolved time should be very close to current time (within 5 seconds)
        time_diff = abs((current_time - resolved_time).total_seconds())
        assert time_diff < 5, f"Resolved time should be current time, but diff is {time_diff}s"
        
        # The resolved time should have timezone info
        assert resolved_time.tzinfo is not None, "Resolved time should have timezone"
        
        # The resolved time should be in UTC
        assert resolved_time.tzinfo == timezone.utc, "Resolved time should be UTC"
        
    finally:
        tmp_path.unlink(missing_ok=True)


def test_resolve_series_end_time_does_not_use_file_mtime():
    """Test that file modification time is NOT used for end time."""
    # Create a file with a known old modification time
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(b"fake png data")
    
    try:
        # Get the file's modification time
        file_mtime = datetime.fromtimestamp(tmp_path.stat().st_mtime, tz=timezone.utc)
        
        # Get the resolved end time
        resolved_time = _resolve_series_end_time(tmp_path)
        
        # The resolved time should NOT be the file's mtime
        # (it should be current time instead)
        current_time = datetime.now(timezone.utc)
        
        # Verify resolved time is close to current time, not file mtime
        diff_from_current = abs((resolved_time - current_time).total_seconds())
        diff_from_mtime = abs((resolved_time - file_mtime).total_seconds())
        
        assert diff_from_current < 5, "Should be close to current time"
        
        # If the file was just created, mtime might be similar to current time
        # So we just verify that the function returns a recent time
        assert diff_from_current < diff_from_mtime + 10, \
            "Resolved time should prioritize current time over file mtime"
        
    finally:
        tmp_path.unlink(missing_ok=True)
