from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from backend.utils.time import to_iso_utc

from .config import HotspotsConfig
from .firms_provider import build_firms_url_public, fetch_firms_records
from .sources import build_sources


def _sample_from_record(record: dict[str, Any]) -> dict[str, Any]:
    sample = {
        "lat": record.get("latitude"),
        "lon": record.get("longitude"),
        "acq_date": record.get("acq_date"),
        "acq_time": record.get("acq_time"),
        "confidence": record.get("confidence"),
    }
    if "frp" in record:
        sample["frp"] = record.get("frp")
    return sample


def diagnose_firms(config: HotspotsConfig, logger: logging.Logger) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)

    sources, platforms = build_sources(config)
    results = []
    for source in sources:
        try:
            result = fetch_firms_records(
                config,
                logger,
                source=source,
                bbox=config.fetch_bbox,
                allow_error=True,
            )
        except requests.RequestException as exc:
            results.append(
                {
                    "source": source,
                    "url_public": build_firms_url_public(
                        config, source=source, bbox=config.fetch_bbox
                    ),
                    "status_code": None,
                    "body_preview": f"request_error: {exc}",
                    "records": [],
                }
            )
            continue
        results.append(result)

    parsed_records: list[dict[str, Any]] = []
    parsed_count = 0
    products_with_records: list[str] = []
    for result in results:
        records = result.records if hasattr(result, "records") else result.get("records", [])
        parsed_count += len(records)
        parsed_records.extend(records)
        if records:
            source = result.source if hasattr(result, "source") else result.get("source")
            if source:
                products_with_records.append(source)

    parsed_sample = [_sample_from_record(record) for record in parsed_records[:3]]

    primary_result = results[0] if results else None
    if primary_result is None:
        request_url = None
        http_status = None
        response_preview = ""
    elif hasattr(primary_result, "url_public"):
        request_url = primary_result.url_public
        http_status = primary_result.status_code
        response_preview = primary_result.body_preview
    else:
        request_url = primary_result.get("url_public")
        http_status = primary_result.get("status_code")
        response_preview = primary_result.get("body_preview", "")

    payload: dict[str, Any] = {
        "now_utc": to_iso_utc(now),
        "window_start_utc": to_iso_utc(window_start),
        "firms_source": config.dataset,
        "firms_platforms": platforms,
        "bbox": config.bbox,
        "bbox_raw": config.bbox_raw,
        "bbox_padding_deg": config.bbox_padding_deg,
        "fetch_bbox": config.fetch_bbox,
        "firms_request_url": request_url,
        "firms_http_status": http_status,
        "firms_response_preview": response_preview[:500],
        "parsed_count": parsed_count,
        "parsed_sample": parsed_sample,
        "products_with_records": products_with_records,
        "firms_requests": [
            {
                "source": result.source if hasattr(result, "source") else result.get("source"),
                "url_public": result.url_public if hasattr(result, "url_public") else result.get("url_public"),
                "status_code": result.status_code if hasattr(result, "status_code") else result.get("status_code"),
                "body_preview": (
                    result.body_preview if hasattr(result, "body_preview") else result.get("body_preview")
                ),
                "parsed_count": len(result.records) if hasattr(result, "records") else len(result.get("records", [])),
            }
            for result in results
        ],
    }
    return payload


__all__ = ["diagnose_firms"]
