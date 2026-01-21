import builtins
import importlib
import importlib.util
import sys
from datetime import datetime, timezone


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
