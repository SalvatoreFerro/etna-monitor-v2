import builtins
import importlib
import importlib.util
import sys
from datetime import datetime, timezone


def test_ensure_utc_aware():
    """Test the ensure_utc_aware helper function for datetime normalization."""
    from scripts.csv_updater import ensure_utc_aware
    
    # Test None input
    assert ensure_utc_aware(None) is None
    
    # Test naive datetime (should add UTC timezone)
    naive_dt = datetime(2025, 1, 1, 12, 0, 0)
    result = ensure_utc_aware(naive_dt)
    assert result is not None
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc
    assert result.year == 2025
    assert result.month == 1
    assert result.day == 1
    assert result.hour == 12
    
    # Test already UTC-aware datetime (should return same time)
    aware_utc = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = ensure_utc_aware(aware_utc)
    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result == aware_utc
    
    # Test non-UTC aware datetime (should convert to UTC)
    from datetime import timedelta
    est = timezone(timedelta(hours=-5))  # EST is UTC-5
    aware_est = datetime(2025, 1, 1, 12, 0, 0, tzinfo=est)
    result = ensure_utc_aware(aware_est)
    assert result is not None
    assert result.tzinfo == timezone.utc
    # 12:00 EST should be 17:00 UTC
    assert result.hour == 17


def test_datetime_comparison_after_normalization():
    """Test that normalized datetimes can be compared without crash."""
    from scripts.csv_updater import ensure_utc_aware
    
    # Simulate the scenario that caused the crash:
    # previous_last_ts from CSV (naive) vs last_ts from extraction (aware)
    naive_previous = datetime(2025, 1, 1, 10, 0, 0)
    aware_current = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Without normalization, this would crash:
    # if aware_current > naive_previous:  # TypeError!
    
    # With normalization, comparison works:
    normalized_previous = ensure_utc_aware(naive_previous)
    normalized_current = ensure_utc_aware(aware_current)
    
    # This should not crash
    assert normalized_current > normalized_previous
    
    # Test the actual comparison logic from csv_updater.py line 271
    last_ts_normalized = ensure_utc_aware(aware_current)
    previous_last_ts_normalized = ensure_utc_aware(naive_previous)
    
    # This is the pattern used in the code
    if last_ts_normalized and (previous_last_ts_normalized is None or last_ts_normalized > previous_last_ts_normalized):
        updated = True
    else:
        updated = False
    
    assert updated is True


def test_csv_updater_runs_without_pandas(monkeypatch, tmp_path):
    original_import = builtins.__import__
    original_find_spec = importlib.util.find_spec

    def blocked_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("pandas disabled for cron test")
        return original_import(name, *args, **kwargs)

    def blocked_find_spec(name, *args, **kwargs):
        if name == "pandas":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    monkeypatch.setattr(importlib.util, "find_spec", blocked_find_spec)

    if "backend.utils.time" in sys.modules:
        importlib.reload(sys.modules["backend.utils.time"])
    if "scripts.csv_updater" in sys.modules:
        importlib.reload(sys.modules["scripts.csv_updater"])

    csv_updater = importlib.import_module("scripts.csv_updater")

    def fake_download_colored_png(_url):
        return tmp_path / "fake.png"

    def fake_extract_series_from_colored(_path):
        return (
            [datetime(2025, 1, 1, tzinfo=timezone.utc)],
            [1.5],
            {},
        )

    monkeypatch.setattr(csv_updater, "download_colored_png", fake_download_colored_png)
    monkeypatch.setattr(csv_updater, "extract_series_from_colored", fake_extract_series_from_colored)

    csv_path = tmp_path / "curva.csv"
    result = csv_updater.update_with_retries(
        "http://example.com",
        "http://example.com/colored.png",
        csv_path,
    )
    assert result["ok"] is True

    assert csv_path.exists()
    last_ts = csv_updater._read_csv_last_timestamp(csv_path)
    assert isinstance(last_ts, datetime)
    assert last_ts.tzinfo is not None
    assert last_ts == datetime(2025, 1, 1, tzinfo=timezone.utc)
