from __future__ import annotations

from flask import Blueprint, jsonify

from ..utils.api_keys import require_api_key
from ..utils.attribution import attribution_snippet, powered_by_payload
from ..services.tremor_summary import calculate_trend, load_tremor_dataframe

api_v1_bp = Blueprint("api_v1", __name__)


def _error_response(code: str, message: str, status_code: int):
    return (
        jsonify(
            {
                "error": {"code": code, "message": message},
                "powered_by": powered_by_payload(),
            }
        ),
        status_code,
    )


@api_v1_bp.get("/api/v1/tremor/status")
@require_api_key()
def tremor_status():
    df, reason = load_tremor_dataframe()
    if reason or df is None:
        return _error_response(
            "data_unavailable",
            "Dati INGV non disponibili al momento.",
            503,
        )

    trend = calculate_trend(df)
    if trend is None:
        return _error_response(
            "data_unavailable",
            "Dati INGV non disponibili al momento.",
            503,
        )

    trend["powered_by"] = powered_by_payload()
    return jsonify(trend)


@api_v1_bp.get("/api/v1/attribution/snippet")
def attribution_snippet_endpoint():
    payload = attribution_snippet()
    payload["powered_by"] = powered_by_payload()
    return jsonify(payload)
