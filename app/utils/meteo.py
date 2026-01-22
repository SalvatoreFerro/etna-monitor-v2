"""Meteo utilities for EtnaMonitor pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Tuple

import requests

from app.extensions import cache

POI_PRESETS: dict[str, dict[str, Any]] = {
    "crateri": {
        "id": "crateri",
        "label": "Crateri Sommitali",
        "lat": 37.751,
        "lon": 14.993,
        "altitude": "3.300 m",
        "note": "Area sommitale più esposta a vento e nubi veloci.",
        "webcam_key": "summit",
    },
    "sapienza": {
        "id": "sapienza",
        "label": "Rifugio Sapienza",
        "lat": 37.699,
        "lon": 14.973,
        "altitude": "1.910 m",
        "note": "Punto di osservazione a sud, utile per valutare l'accesso in quota.",
        "webcam_key": "south",
    },
    "provenzana": {
        "id": "provenzana",
        "label": "Piano Provenzana",
        "lat": 37.824,
        "lon": 15.025,
        "altitude": "1.800 m",
        "note": "Versante nord con inquadratura ampia dei crateri.",
        "webcam_key": "north",
    },
}

DEFAULT_POI_ID = "crateri"


def get_poi_preset(poi_id: str | None) -> dict[str, Any]:
    return POI_PRESETS.get(poi_id or "", POI_PRESETS[DEFAULT_POI_ID])


def _format_weather_timestamp(value: str | None) -> Tuple[str | None, str | None]:
    if not value:
        return None, None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None, None
    return dt.strftime("%H:%M"), dt.isoformat()


def _wind_direction_to_cardinal(degrees: float | None) -> str | None:
    if degrees is None:
        return None
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = int((degrees + 11.25) / 22.5) % len(directions)
    return directions[index]


def _describe_weather_code(code: int | None) -> str | None:
    mapping = {
        0: "Cielo sereno",
        1: "Prevalentemente sereno",
        2: "Parzialmente nuvoloso",
        3: "Coperto",
        45: "Nebbia",
        48: "Nebbia con brina",
        51: "Pioviggine leggera",
        53: "Pioviggine moderata",
        55: "Pioviggine intensa",
        61: "Pioggia leggera",
        63: "Pioggia moderata",
        65: "Pioggia intensa",
        71: "Neve leggera",
        73: "Neve moderata",
        75: "Neve intensa",
        77: "Granelli di neve",
        80: "Rovesci leggeri",
        81: "Rovesci moderati",
        82: "Rovesci intensi",
        95: "Temporale",
        96: "Temporale con grandine leggera",
        99: "Temporale con grandine intensa",
    }
    return mapping.get(code)


def _select_hourly_value(hourly: dict[str, Any], current_time: str | None, key: str) -> Any:
    values = hourly.get(key) or []
    times = hourly.get("time") or []
    if not values:
        return None

    if current_time and current_time in times:
        try:
            return values[times.index(current_time)]
        except (ValueError, IndexError):
            return values[0]
    return values[0]


def _visibility_assessment(cloud_cover: float | None, precip_probability: float | None) -> dict[str, str]:
    cloud_value = cloud_cover or 0
    precip_value = precip_probability or 0

    if precip_value >= 70 or cloud_value >= 75:
        return {
            "label": "Bassa",
            "note": "Nubi o precipitazioni possono coprire i crateri.",
        }
    if precip_value >= 35 or cloud_value >= 45:
        return {
            "label": "Media",
            "note": "Possibili banchi di nube o foschia: la vista può variare.",
        }
    return {
        "label": "Buona",
        "note": "Condizioni favorevoli per osservare i crateri.",
    }


def _compute_operational_index(
    wind_speed: float | None,
    cloud_cover: float | None,
    precip_probability: float | None,
) -> dict[str, Any]:
    wind_value = wind_speed or 0
    cloud_value = cloud_cover or 0
    precip_value = precip_probability or 0

    # Heuristic index: weights reflect impact on visibility (cloud), safety/comfort (wind), and disturbances (precip).
    # Cloud cover > 70% and precip probability > 60% heavily reduce the score; wind > 50 km/h adds a strong penalty.
    cloud_score = max(0, 100 - cloud_value)
    precip_score = max(0, 100 - precip_value)
    wind_score = max(0, 100 - min(wind_value, 80) * 1.1)

    visibility_score = max(0, 100 - (cloud_value * 0.7 + precip_value * 0.5))

    score = round(
        cloud_score * 0.35
        + precip_score * 0.25
        + wind_score * 0.25
        + visibility_score * 0.15
    )

    # Thresholds tuned for Etna observations: higher scores reflect clear skies and manageable winds.
    if score >= 75:
        label = "OTTIMO"
        message = "Condizioni favorevoli per osservare i crateri e leggere le webcam con chiarezza."
        badge_class = "badge--excellent"
    elif score >= 55:
        label = "OK"
        message = "Visibilità discreta: qualche nube o vento può limitare i dettagli."
        badge_class = "badge--good"
    elif score >= 35:
        label = "SCARSO"
        message = "Meteo incerto: dettagli sui crateri poco affidabili."
        badge_class = "badge--warning"
    else:
        label = "CRITICO"
        message = "Condizioni poco adatte alla lettura live: visibilità molto ridotta."
        badge_class = "badge--critical"

    return {
        "score": max(0, min(score, 100)),
        "label": label,
        "message": message,
        "badge_class": badge_class,
    }


def _trend_labels(times: list[str]) -> list[str]:
    labels = []
    for value in times:
        if "T" in value:
            labels.append(value.split("T", 1)[1][:5])
        else:
            labels.append(value)
    return labels


def _extract_trend(hourly: dict[str, Any]) -> dict[str, list[Any]]:
    times = hourly.get("time") or []
    trimmed_times = times[-24:] if len(times) >= 24 else times
    size = len(trimmed_times)

    def _slice(values: list[Any]) -> list[Any]:
        if not values:
            return []
        return values[-size:] if size else []

    return {
        "labels": _trend_labels(trimmed_times),
        "temperature": _slice(hourly.get("temperature_2m") or []),
        "wind": _slice(hourly.get("wind_speed_10m") or []),
        "cloud": _slice(hourly.get("cloud_cover") or []),
        "precip": _slice(hourly.get("precipitation_probability") or []),
    }


def _fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "wind_speed_10m,wind_direction_10m,weather_code,cloud_cover"
            ),
            "hourly": (
                "temperature_2m,wind_speed_10m,cloud_cover,precipitation_probability"
            ),
            "forecast_days": 2,
            "past_days": 1,
            "timezone": "Europe/Rome",
        },
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def get_webcam_weather_payload(poi_id: str | None) -> tuple[dict[str, Any] | None, str | None]:
    poi = get_poi_preset(poi_id)
    cache_key = f"webcam-meteo:{poi['id']}"
    cached = cache.get(cache_key)
    if cached:
        return cached, None

    try:
        weather_data = _fetch_open_meteo(poi["lat"], poi["lon"])
    except requests.RequestException:
        return None, "Dati meteo temporaneamente non disponibili."

    current = (weather_data or {}).get("current") or {}
    units = (weather_data or {}).get("current_units") or {}
    hourly = (weather_data or {}).get("hourly") or {}

    precipitation_probability = _select_hourly_value(
        hourly, current.get("time"), "precipitation_probability"
    )

    cloud_cover = current.get("cloud_cover")
    wind_direction_deg = current.get("wind_direction_10m")
    updated_at_display, updated_at_iso = _format_weather_timestamp(current.get("time"))

    visibility = _visibility_assessment(cloud_cover, precipitation_probability)
    operational_index = _compute_operational_index(
        current.get("wind_speed_10m"),
        cloud_cover,
        precipitation_probability,
    )

    trend = _extract_trend(hourly)

    weather_preview = {
        "temperature": current.get("temperature_2m"),
        "temperature_unit": units.get("temperature_2m", "°C"),
        "apparent_temperature": current.get("apparent_temperature"),
        "apparent_temperature_unit": units.get("apparent_temperature", "°C"),
        "humidity": current.get("relative_humidity_2m"),
        "humidity_unit": units.get("relative_humidity_2m", "%"),
        "wind_speed": current.get("wind_speed_10m"),
        "wind_speed_unit": units.get("wind_speed_10m", "km/h"),
        "wind_direction": wind_direction_deg,
        "wind_direction_cardinal": _wind_direction_to_cardinal(wind_direction_deg),
        "precipitation_probability": precipitation_probability,
        "precipitation_unit": "%",
        "cloud_cover": cloud_cover,
        "cloud_cover_unit": units.get("cloud_cover", "%"),
        "updated_at": updated_at_display,
        "updated_at_iso": updated_at_iso,
        "weather_code": current.get("weather_code"),
        "weather_description": _describe_weather_code(current.get("weather_code")),
        "visibility_label": visibility["label"],
        "visibility_note": visibility["note"],
        "operational_note": (
            "Le webcam dipendono da luce e meteo: se l'immagine è poco chiara, "
            "controlla le condizioni prima di trarre conclusioni."
        ),
    }

    payload = {
        "poi": poi,
        "weather_preview": weather_preview,
        "operational_index": operational_index,
        "trend": trend,
    }
    cache.set(cache_key, payload, timeout=600)
    return payload, None
