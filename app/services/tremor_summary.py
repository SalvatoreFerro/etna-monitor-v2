from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import logging
from typing import Any

import pandas as pd
from flask import current_app
from openai import OpenAI

from ..utils.config import get_curva_csv_path
from ..utils.ingv_bands import get_ingv_band_thresholds
from backend.utils.time import to_iso_utc
from config import Config

_AI_CACHE: dict[str, Any] = {
    "ts_utc": None,
    "expires_at": None,
    "payload": None,
    "last_error": None,
    "last_error_at": None,
}

_DEFAULT_DISCLAIMER = "Solo informativo, non previsione; fai riferimento alle fonti ufficiali."


def _get_logger() -> logging.Logger:
    try:
        return current_app.logger
    except RuntimeError:
        return logging.getLogger(__name__)


def load_tremor_dataframe() -> tuple[pd.DataFrame | None, str | None]:
    csv_path = get_curva_csv_path()

    if not csv_path.exists() or csv_path.stat().st_size <= 20:
        return None, "missing_data"

    try:
        raw_df = pd.read_csv(csv_path)
    except Exception:
        return None, "read_error"

    if "timestamp" not in raw_df.columns:
        return None, "missing_timestamp"

    df = raw_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if "value" not in df.columns:
        if "value_max" in df.columns:
            df["value"] = df["value_max"]
        elif "value_avg" in df.columns:
            df["value"] = df["value_avg"]

    if "value" not in df.columns:
        return None, "missing_value"

    df = df.dropna(subset=["value"]).sort_values("timestamp")
    if df.empty:
        return None, "empty_data"

    return df, None


def calculate_trend(df: pd.DataFrame, window_minutes: int = 60) -> dict | None:
    if df.empty:
        return None

    latest_ts = df["timestamp"].max()
    window_start = latest_ts - timedelta(minutes=window_minutes)
    prev_start = latest_ts - timedelta(minutes=window_minutes * 2)

    last_df = df[df["timestamp"] >= window_start].copy()
    prev_df = df[(df["timestamp"] < window_start) & (df["timestamp"] >= prev_start)].copy()

    if last_df.empty or prev_df.empty:
        return None

    median_last_hour = float(last_df["value"].median())
    median_prev_hour = float(prev_df["value"].median())

    eps = 1e-6
    delta_pct = (median_last_hour - median_prev_hour) / max(median_prev_hour, eps)

    if abs(delta_pct) < 0.07:
        status = "STABILE"
        direction = "flat"
        message = "Tremore stabile nell’ultima ora"
    elif delta_pct >= 0.07:
        status = "IN_AUMENTO"
        direction = "up"
        message = "Tremore in aumento nell’ultima ora"
    else:
        status = "IN_CALO"
        direction = "down"
        message = "Tremore in calo nell’ultima ora"

    return {
        "ts_utc": to_iso_utc(latest_ts.to_pydatetime()),
        "status": status,
        "direction": direction,
        "value_mv": median_last_hour,
        "window_min": window_minutes,
        "message": message,
        "median_last_hour": median_last_hour,
        "median_prev_hour": median_prev_hour,
        "delta_pct": delta_pct,
        "source": "INGV",
    }


def _build_level_message(trend: str, level_label: str, level_band: str) -> str:
    band_lower = level_band.lower()
    if level_band == "UNKNOWN":
        if trend == "IN_AUMENTO":
            return "Tremore in aumento nell’ultima ora (livello non disponibile)."
        if trend == "IN_CALO":
            return "Tremore in calo nell’ultima ora (livello non disponibile)."
        if trend == "STABILE":
            return "Tremore stabile nell’ultima ora (livello non disponibile)."
        return "Dati INGV non disponibili al momento."
    if trend == "IN_AUMENTO" and level_band == "GREEN":
        return (
            "Tremore in lieve aumento nell’ultima ora, "
            f"ma resta su livelli bassi (fascia {band_lower})."
        )
    if trend == "IN_AUMENTO" and level_band in {"YELLOW", "ORANGE", "RED"}:
        return (
            "Tremore in aumento e su livelli elevati "
            f"(fascia {band_lower}): monitora con attenzione."
        )
    if trend == "IN_CALO":
        return f"Tremore in calo e su livelli {level_label} (fascia {band_lower})."
    if trend == "STABILE":
        return f"Tremore stabile e su livelli {level_label} (fascia {band_lower})."
    return "Dati INGV non disponibili al momento."


def _classify_level_band(value: float, thresholds: dict[str, float]) -> str:
    t1 = thresholds.get("t1")
    t2 = thresholds.get("t2")
    t3 = thresholds.get("t3")
    if t1 is None or t2 is None or t3 is None:
        return "UNKNOWN"
    if value < t1:
        return "GREEN"
    if value < t2:
        return "YELLOW"
    if t3 > t2 and value < t3:
        return "ORANGE"
    return "RED"


def _level_label(level_band: str) -> tuple[str, str]:
    mapping = {
        "GREEN": ("bassi", "green"),
        "YELLOW": ("moderati", "yellow"),
        "ORANGE": ("elevati", "orange"),
        "RED": ("molto elevati", "red"),
        "UNKNOWN": ("non disponibili", "gray"),
    }
    return mapping.get(level_band, ("non disponibili", "gray"))


def _badge_label(trend: str, level_band: str) -> str:
    if trend == "IN_AUMENTO" and level_band == "GREEN":
        return "IN LIEVE AUMENTO"
    if trend == "IN_AUMENTO":
        return "IN AUMENTO"
    if trend == "IN_CALO":
        return "IN CALO"
    if trend == "STABILE":
        return "STABILE"
    return "DATI NON DISPONIBILI"


def _ai_enabled() -> bool:
    return (
        os.getenv("FEATURE_AI_SUMMARY", "0").strip() == "1"
        and bool(os.getenv("OPENAI_API_KEY", "").strip())
    )


def _extract_response_text(response: Any) -> str | None:
    try:
        content_blocks = response.output[0].content  # type: ignore[index,attr-defined]
    except Exception:
        return None

    for block in content_blocks:
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            return str(text)
    return None


def _sanitize_ai_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    headline = str(payload.get("headline", "")).strip()[:60]
    explain = str(payload.get("explain", "")).strip()[:180]
    bullets_raw = payload.get("bullets", [])
    bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
    bullets = bullets[:3]
    risk = payload.get("risk") if payload.get("risk") in {"low", "moderate", "high"} else "low"
    disclaimer = str(payload.get("disclaimer", "")).strip()[:160]

    if not headline or not explain or not disclaimer:
        return None

    return {
        "headline": headline,
        "explain": explain,
        "bullets": bullets,
        "risk": risk,
        "disclaimer": disclaimer,
    }


def _ai_cache_valid(ts_utc: str | None) -> bool:
    if not ts_utc:
        return False
    expires_at = _AI_CACHE.get("expires_at")
    cached_ts = _AI_CACHE.get("ts_utc")
    if not expires_at or not cached_ts or cached_ts != ts_utc:
        return False
    return datetime.now(timezone.utc) < expires_at


def _store_ai_cache(ts_utc: str, payload: dict[str, Any]) -> None:
    _AI_CACHE["ts_utc"] = ts_utc
    _AI_CACHE["payload"] = payload
    _AI_CACHE["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    _AI_CACHE["last_error"] = None
    _AI_CACHE["last_error_at"] = None


def get_ai_cache_status() -> dict[str, Any]:
    expires_at = _AI_CACHE.get("expires_at")
    expires_at_iso = expires_at.isoformat() if expires_at else None
    return {
        "enabled": _ai_enabled(),
        "ts_utc": _AI_CACHE.get("ts_utc"),
        "expires_at": expires_at_iso,
        "has_payload": _AI_CACHE.get("payload") is not None,
        "last_error": _AI_CACHE.get("last_error"),
        "last_error_at": _AI_CACHE.get("last_error_at"),
        "valid": _ai_cache_valid(_AI_CACHE.get("ts_utc")),
    }


def _fetch_ai_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    client = OpenAI(api_key=api_key, timeout=8)

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["headline", "explain", "bullets", "risk", "disclaimer"],
        "properties": {
            "headline": {"type": "string", "maxLength": 60},
            "explain": {"type": "string", "maxLength": 180},
            "bullets": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "maxLength": 120},
            },
            "risk": {"type": "string", "enum": ["low", "moderate", "high"]},
            "disclaimer": {"type": "string", "maxLength": 160},
        },
    }

    system_prompt = (
        "Sei un assistente per EtnaMonitor. Scrivi in italiano, tono chiaro, "
        "prudente e non allarmistico. Non includere dati personali o identificativi. "
        "Usa solo i numeri e i flag forniti e non inventare previsioni o allerte ufficiali."
    )
    user_prompt = (
        "Sintetizza lo stato del tremore con linguaggio semplice. "
        "Dati disponibili (solo questi):\n"
        f"- status: {payload.get('status')}\n"
        f"- direction: {payload.get('direction')}\n"
        f"- value_mv: {payload.get('value_mv')}\n"
        f"- ts_utc: {payload.get('ts_utc')}\n"
        f"- window_min: {payload.get('window_min')}\n"
        f"- threshold: {payload.get('threshold')}\n"
        "Fornisci un riassunto sintetico e una spiegazione semplice per utenti generici."
    )

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "tremor_summary",
                "schema": schema,
                "strict": True,
            },
        },
        max_output_tokens=220,
    )

    content = _extract_response_text(response)
    if not content:
        return None

    parsed = json.loads(content)
    return _sanitize_ai_payload(parsed)


def _get_ai_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not _ai_enabled():
        return None

    ts_utc = payload.get("ts_utc")
    if not ts_utc or payload.get("value_mv") is None:
        return None
    if _ai_cache_valid(ts_utc):
        return _AI_CACHE.get("payload")

    logger = _get_logger()
    try:
        ai_payload = _fetch_ai_summary(payload)
    except Exception as exc:
        _AI_CACHE["last_error"] = str(exc)
        _AI_CACHE["last_error_at"] = datetime.now(timezone.utc).isoformat()
        logger.warning("[AI_SUMMARY] OpenAI request failed: %s", exc)
        return None

    if not ai_payload:
        _AI_CACHE["last_error"] = "Invalid or empty AI payload"
        _AI_CACHE["last_error_at"] = datetime.now(timezone.utc).isoformat()
        logger.warning("[AI_SUMMARY] Invalid AI payload")
        return None

    if ts_utc:
        _store_ai_cache(ts_utc, ai_payload)
    return ai_payload


def build_tremor_summary(window_minutes: int = 60) -> dict[str, Any]:
    df, reason = load_tremor_dataframe()
    trend = calculate_trend(df, window_minutes=window_minutes) if df is not None and not reason else None

    ingv_bands = get_ingv_band_thresholds(_get_logger())
    thresholds = ingv_bands.get("thresholds_mv") or {}
    verification = ingv_bands.get("verification") or {}

    if trend:
        status = trend.get("status")
        direction = trend.get("direction")
        value_mv = trend.get("value_mv")
        ts_utc = trend.get("ts_utc")
        window_min = trend.get("window_min", window_minutes)
        median_last_hour = trend.get("median_last_hour")
        median_prev_hour = trend.get("median_prev_hour")
        delta_pct = trend.get("delta_pct")
    else:
        status = "NON_DISPONIBILE"
        direction = "unknown"
        value_mv = None
        ts_utc = None
        window_min = window_minutes
        median_last_hour = None
        median_prev_hour = None
        delta_pct = None

    level_band = _classify_level_band(value_mv, thresholds) if value_mv is not None else "UNKNOWN"
    level_label, band_color = _level_label(level_band)
    trend_label = _badge_label(status, level_band)
    message_user_friendly = _build_level_message(status, level_label, level_band)

    summary: dict[str, Any] = {
        "status": status,
        "trend": status,
        "trend_label": trend_label,
        "direction": direction,
        "level_band": level_band,
        "level_label": level_label,
        "band_color": band_color,
        "value_mv": value_mv,
        "ts_utc": ts_utc,
        "window_min": window_min,
        "message_user_friendly": message_user_friendly,
        "message": message_user_friendly,
        "badge": f"{trend_label} · {level_band}" if level_band != "UNKNOWN" else trend_label,
        "median_last_hour": median_last_hour,
        "median_prev_hour": median_prev_hour,
        "delta_pct": delta_pct,
        "thresholds_used": {
            "t1": thresholds.get("t1"),
            "t2": thresholds.get("t2"),
            "t3": thresholds.get("t3"),
            "source": ingv_bands.get("source"),
        },
        "bands_px_used": ingv_bands.get("bands_px"),
        "verification_status": verification.get("status"),
        "debug": {
            "median_last_hour": median_last_hour,
            "median_prev_hour": median_prev_hour,
            "delta_pct": delta_pct,
        },
        "disclaimer": _DEFAULT_DISCLAIMER,
    }

    ai_payload = _get_ai_summary(
        {
            "status": status,
            "direction": direction,
            "value_mv": value_mv,
            "ts_utc": ts_utc,
            "window_min": window_min,
            "threshold": float(Config.ALERT_THRESHOLD_DEFAULT),
        }
    )
    if ai_payload:
        summary.update(
            {
                "ai_headline": ai_payload.get("headline"),
                "ai_explain": ai_payload.get("explain"),
                "ai_bullets": ai_payload.get("bullets"),
                "ai_risk": ai_payload.get("risk"),
                "ai_disclaimer": ai_payload.get("disclaimer"),
            }
        )

    return summary
