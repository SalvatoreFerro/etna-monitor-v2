from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_generated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_data_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def read_cache(path: str) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_cache_valid(cache: dict[str, Any], ttl_minutes: int) -> bool:
    generated_at = _parse_generated_at(cache.get("generated_at"))
    if generated_at is None:
        return False
    age = datetime.now(timezone.utc) - generated_at
    return age.total_seconds() <= ttl_minutes * 60


def write_cache(path: str, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    ensure_data_dir(str(file_path.parent))
    temp_path = file_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(file_path)


def unavailable_payload(message: str) -> dict[str, Any]:
    return {
        "available": False,
        "message": message,
    }


__all__ = ["read_cache", "write_cache", "is_cache_valid", "unavailable_payload", "ensure_data_dir"]
