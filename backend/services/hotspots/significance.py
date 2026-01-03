from __future__ import annotations

from typing import Any, Mapping

from .config import HotspotsConfig


def _normalize_confidence(value: str | None) -> str:
    if not value:
        return "unknown"
    raw = value.strip().lower()
    if raw in {"low", "l"}:
        return "low"
    if raw in {"nominal", "n", "medium", "med"}:
        return "nominal"
    if raw in {"high", "h"}:
        return "high"
    try:
        numeric = float(raw)
    except ValueError:
        return raw
    if numeric < 30:
        return "low"
    if numeric < 80:
        return "nominal"
    return "high"


def _confidence_rank(value: str | None) -> int:
    normalized = _normalize_confidence(value)
    return {"low": 0, "nominal": 1, "high": 2}.get(normalized, -1)


def is_significant(
    confidence: str | None,
    brightness: float | None,
    frp: float | None,
    config: HotspotsConfig,
) -> bool:
    if _confidence_rank(confidence) < _confidence_rank(config.significant_confidence_min):
        return False
    brightness_ok = brightness is not None and brightness >= config.significant_brightness_min
    frp_ok = frp is not None and frp >= config.significant_frp_min
    return brightness_ok or frp_ok


def is_significant_item(item: Mapping[str, Any], config: HotspotsConfig) -> bool:
    intensity = item.get("intensity") or {}
    brightness = intensity.get("brightness")
    frp = intensity.get("frp")
    return is_significant(item.get("confidence"), brightness, frp, config)


def is_significant_record(record: Any, config: HotspotsConfig) -> bool:
    brightness = getattr(record, "bright_ti4", None)
    if brightness is None:
        brightness = getattr(record, "brightness", None)
    if brightness is None:
        brightness = getattr(record, "bright_ti5", None)
    frp = getattr(record, "frp", None)
    return is_significant(getattr(record, "confidence", None), brightness, frp, config)


__all__ = ["is_significant", "is_significant_item", "is_significant_record"]
