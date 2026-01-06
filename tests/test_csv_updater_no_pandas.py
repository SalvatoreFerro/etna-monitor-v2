import builtins
import csv
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

    def fake_process_png_to_csv(_url, output_path):
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "value"])
            writer.writerow(["2025-01-01T00:00:00Z", "1.5"])
        return {
            "rows": 1,
            "last_ts": "2025-01-01T00:00:00Z",
            "output_path": output_path,
        }

    monkeypatch.setattr(csv_updater, "process_png_to_csv", fake_process_png_to_csv)

    csv_path = tmp_path / "curva.csv"
    result = csv_updater.update_with_retries("http://example.com", csv_path)
    assert result["ok"] is True

    assert csv_path.exists()
    last_ts = csv_updater._read_csv_last_timestamp(csv_path)
    assert isinstance(last_ts, datetime)
    assert last_ts.tzinfo is not None
    assert last_ts == datetime(2025, 1, 1, tzinfo=timezone.utc)
