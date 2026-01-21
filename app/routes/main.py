from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
from math import isfinite

import pandas as pd
import requests
from flask import (
    Blueprint,
    current_app,
    jsonify,
    abort,
    redirect,
    render_template,
    render_template_string,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user

from ..utils.auth import get_current_user, is_owner_or_admin

from app.bootstrap import get_alembic_status
from app.models import db
from app.models.user import User
from app.models.blog import BlogPost
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import cache
from ..utils.metrics import get_csv_metrics, record_csv_error, record_csv_read
from ..utils.plotly_helpers import build_plotly_html_from_pairs
from app.security import BASE_CSP, apply_csp_headers, serialize_csp, talisman
from backend.utils.time import to_iso_utc
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.storage import read_cache, unavailable_payload
from config import DEFAULT_GA_MEASUREMENT_ID
from app.models.hotspots_record import HotspotsRecord
from app.services.copernicus import (
    get_latest_copernicus_image,
    resolve_copernicus_bbox,
    resolve_copernicus_image_url,
)
from ..services.sentieri_geojson import read_geojson_file, validate_feature_collection
from ..utils.config import get_curva_csv_path, load_curva_dataframe, warn_if_stale_timestamp

bp = Blueprint("main", __name__)


@bp.route("/author/<slug>")
def author_detail(slug: str):
    author_slug = BlogPost.DEFAULT_AUTHOR_SLUG
    author_name = BlogPost.DEFAULT_AUTHOR_NAME
    if slug != author_slug:
        abort(404)
    author_url = url_for("main.author_detail", slug=author_slug, _external=True)
    return render_template(
        "author/detail.html",
        author_name=author_name,
        author_url=author_url,
    )


WEATHER_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Cielo sereno",
    1: "Cielo prevalentemente sereno",
    2: "Parzialmente nuvoloso",
    3: "Coperto",
    45: "Nebbia",
    48: "Nebbia gelata",
    51: "Pioviggine debole",
    53: "Pioviggine moderata",
    55: "Pioviggine intensa",
    61: "Pioggia debole",
    63: "Pioggia moderata",
    65: "Pioggia forte",
    66: "Pioggia gelata debole",
    67: "Pioggia gelata intensa",
    71: "Neve debole",
    73: "Neve moderata",
    75: "Neve intensa",
    77: "Cristalli di ghiaccio",
    80: "Rovesci deboli",
    81: "Rovesci moderati",
    82: "Rovesci violenti",
    85: "Rovesci di neve deboli",
    86: "Rovesci di neve intensi",
    95: "Temporale",
    96: "Temporale con grandine debole",
    99: "Temporale con grandine intensa",
}


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
        "SSO",
        "SO",
        "OSO",
        "O",
        "ONO",
        "NO",
        "NNO",
    ]
    index = int((degrees % 360) / 22.5 + 0.5) % len(directions)
    return directions[index]


def _format_weather_timestamp(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None, value

    return dt.strftime("%d/%m/%Y %H:%M"), dt.isoformat()


def _format_hotspots_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def _format_display_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.strftime("%d/%m/%Y %H:%M UTC")


def _sentieri_paths() -> tuple[Path, Path]:
    """Return absolute paths to the trails/POI GeoJSON files."""
    data_dir = Path(current_app.root_path) / "static" / "data"
    return data_dir / "trails.geojson", data_dir / "pois.geojson"


def _load_sentieri_geojson(kind: str) -> dict | None:
    """Load GeoJSON from disk and validate minimal requirements for sentieri pages."""
    trails_path, pois_path = _sentieri_paths()
    path = trails_path if kind == "trails" else pois_path
    _, data, error = read_geojson_file(path)
    if error:
        current_app.logger.warning("[SENTIERI] GeoJSON missing: %s", error.get("message"))
        return None

    report = validate_feature_collection(data, kind=kind)
    if not report.get("ok"):
        current_app.logger.warning("[SENTIERI] GeoJSON validation failed: %s", report.get("errors"))
        return None
    return data


def _describe_weather_code(code: int | None) -> str | None:
    if code is None:
        return None

    return WEATHER_CODE_DESCRIPTIONS.get(code)


def _index_cache_key() -> str:
    """Return a cache key scoped to the request path and the current user."""

    user_id: str | None = None
    if current_user.is_authenticated:
        user_id = str(current_user.get_id()) if current_user.get_id() is not None else "auth"
    else:
        # Flask-Login clears its session keys on logout, but the legacy session
        # helpers still mirror the integer ``user_id``. Reuse it when present so
        # cached pages remain isolated per authenticated session while visitors
        # without a profile still share the anonymous entry.
        raw_session_id = session.get("user_id")
        if raw_session_id is not None:
            user_id = str(raw_session_id)

    if not user_id:
        user_id = "anon"

    # Include the query string (if any) to avoid collisions across anchors or
    # tracking parameters while keeping the cache key deterministic.
    full_path = request.full_path or request.path or "/"
    full_path = full_path.rstrip("?")
    return f"index::{user_id}::{full_path}"


@bp.route("/ga4/diagnostics")
def ga4_diagnostics():
    return render_template(
        "ga4_diagnostics.html",
        page_title="GA4 Diagnostics",
        page_description="Snapshot di window.dataLayer, user agent e stato di window.gtag.",
    )


@bp.route("/csp/test")
def csp_test():
    """Return the CSP header applied to the home page response."""

    with current_app.test_client() as client:
        home_response = client.get(url_for("main.index"))

    policy_header = home_response.headers.get("Content-Security-Policy", "")
    return jsonify(
        {
            "status_code": home_response.status_code,
            "content_security_policy": policy_header,
        }
    )


@bp.route("/")
@cache.cached(timeout=180, key_prefix=_index_cache_key)
def index():
    csv_path = get_curva_csv_path()
    timestamps: list[str] = []
    values: list[float] = []
    temporal_start_iso: str | None = None
    temporal_end_iso: str | None = None
    temporal_coverage: str | None = None
    latest_value: float | None = None
    latest_timestamp_iso: str | None = None
    latest_timestamp_display: str | None = None
    data_points = 0
    placeholder_reason: str | None = None
    csv_mtime_utc: str | None = None
    csv_debug: dict[str, str | int | None] | None = None
    df = None
    plot_html: str | None = None

    if csv_path.exists():
        try:
            stat = csv_path.stat()
            csv_mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            csv_mtime_utc = None
        df, load_reason = load_curva_dataframe(csv_path)
        if load_reason:
            placeholder_reason = load_reason
            if load_reason == "csv_missing":
                placeholder_reason = "missing"
            elif load_reason in {"missing_timestamp", "missing_value"}:
                placeholder_reason = "missing_timestamp"
            elif load_reason == "empty":
                placeholder_reason = "empty"
            else:
                placeholder_reason = "error"
            if load_reason.startswith("read_error"):
                current_app.logger.exception("[HOME] Failed to read tremor CSV: %s", load_reason)
            else:
                current_app.logger.warning("[HOME] CSV validation failed: %s", load_reason)
            record_csv_error(str(load_reason))
        elif df is not None:
            df = df.sort_values("timestamp")
            timestamps = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
            values = df["value"].tolist()
            data_points = len(df)

            temporal_start = df["timestamp"].iloc[0]
            temporal_end = df["timestamp"].iloc[-1]
            warn_if_stale_timestamp(temporal_end, current_app.logger, "homepage")
            temporal_start_iso = to_iso_utc(temporal_start)
            temporal_end_iso = to_iso_utc(temporal_end)
            temporal_coverage = (
                f"{temporal_start_iso}/{temporal_end_iso}"
                if temporal_start_iso and temporal_end_iso
                else None
            )
            latest_value = float(df["value"].iloc[-1])
            latest_timestamp_iso = temporal_end_iso
            temporal_end_display = (
                temporal_end.tz_convert("UTC")
                if getattr(temporal_end, "tz", None) is not None
                else temporal_end.tz_localize("UTC")
            )
            latest_timestamp_display = temporal_end_display.strftime("%d/%m/%Y %H:%M")
            record_csv_read(len(df), temporal_end.to_pydatetime())

            plot_df = df[df["value"].notna()].copy()
            clean_pairs = []
            if not plot_df.empty:
                for ts, value in zip(
                    plot_df["timestamp"].tolist(), plot_df["value"].tolist()
                ):
                    if value is None or not isfinite(value) or value <= 0:
                        continue
                    ts_iso = to_iso_utc(ts)
                    if ts_iso is None:
                        continue
                    clean_pairs.append((ts_iso, float(value)))
            if clean_pairs:
                threshold_level = 4
                shapes = []
                if threshold_level:
                    shapes.append(
                        {
                            "type": "line",
                            "x0": clean_pairs[0][0],
                            "x1": clean_pairs[-1][0],
                            "y0": threshold_level,
                            "y1": threshold_level,
                            "line": {"color": "#ef4444", "width": 2, "dash": "dash"},
                        }
                    )
                layout = {
                    "margin": {"l": 64, "r": 32, "t": 24, "b": 56},
                    "hovermode": "x unified",
                    "plot_bgcolor": "rgba(0,0,0,0)",
                    "paper_bgcolor": "rgba(0,0,0,0)",
                    "font": {"color": "#e2e8f0"},
                    "xaxis": {
                        "type": "date",
                        "title": "",
                        "showgrid": True,
                        "gridcolor": "#1f2937",
                        "linewidth": 1,
                        "linecolor": "#334155",
                        "hoverformat": "%d/%m %H:%M",
                        "tickfont": {"size": 12},
                        "ticks": "outside",
                        "tickcolor": "#334155",
                    },
                    "yaxis": {
                        "title": "Ampiezza (mV)",
                        "type": "log",
                        "showgrid": True,
                        "gridcolor": "#1f2937",
                        "linewidth": 1,
                        "linecolor": "#334155",
                        "tickfont": {"size": 12},
                        "tickvals": [0.1, 0.2, 0.5, 1, 2, 5, 10],
                        "ticktext": ["10⁻¹", "0.2", "0.5", "1", "2", "5", "10¹"],
                        "ticksuffix": " mV",
                        "exponentformat": "power",
                        "minor": {"ticklen": 4, "showgrid": False},
                        "zeroline": False,
                    },
                    "shapes": shapes,
                    "hoverlabel": {
                        "bgcolor": "rgba(15, 23, 42, 0.92)",
                        "bordercolor": "#ef4444",
                        "font": {"color": "#f8fafc"},
                    },
                }
                plot_html = build_plotly_html_from_pairs(
                    clean_pairs,
                    include_plotlyjs=False,
                    line={
                        "color": "#4ade80",
                        "width": 2.4,
                        "shape": "spline",
                        "smoothing": 1.15,
                    },
                    layout=layout,
                    name="Tremore",
                    min_points=1,
                    eps=0.1,
                    trace_kwargs={
                        "fill": "tozeroy",
                        "fillcolor": "rgba(74, 222, 128, 0.08)",
                        "hovertemplate": "<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>",
                        "showlegend": False,
                    },
                )
    else:
        placeholder_reason = "missing"
        if not current_app.config.get("_home_csv_missing_warned"):
            current_app.logger.info(
                "[HOME] Tremor CSV not found at %s; rendering placeholder UI", csv_path
            )
            current_app.config["_home_csv_missing_warned"] = True
        record_csv_error(f"Missing CSV at {csv_path}")

    canonical_home = url_for("main.index", _external=True)
    chart_url = f"{canonical_home}#grafico-etna"
    og_image = url_for("static", filename="icons/icon-512.png", _external=True)
    page_title = "Monitoraggio Etna in tempo reale – Grafico INGV | EtnaMonitor"
    page_description = (
        "Dati ufficiali INGV e grafico del tremore dell'Etna aggiornato con lettura chiara delle soglie. "
        "EtnaMonitor offre un monitoraggio affidabile e avvisi Telegram quando serve."
    )

    webpage_structured_data = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page_title,
        "url": canonical_home,
        "inLanguage": "it-IT",
        "description": page_description,
        "primaryImageOfPage": og_image,
        "about": [
            {"@type": "Thing", "name": "Etna"},
            {"@type": "Thing", "name": "Tremore vulcanico"},
        ],
    }

    dataset_structured_data = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Serie temporale tremore vulcanico Etna – ultime 24 ore",
        "description": (
            "Misurazioni dell'ampiezza del tremore vulcanico dell'Etna aggiornate in tempo reale "
            "sulla base dei dati pubblici diffusi dall'Osservatorio Etneo INGV."
        ),
        "inLanguage": "it",
        "url": chart_url,
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "creator": {
            "@type": "Organization",
            "name": "Istituto Nazionale di Geofisica e Vulcanologia (INGV)",
            "url": "https://www.ct.ingv.it",
        },
        "citation": "https://www.ct.ingv.it/index.php/monitoraggio/monitoraggio-sismico",
        "isBasedOn": "https://www.ct.ingv.it",
        "keywords": [
            "Etna",
            "tremore vulcanico",
            "monitoraggio Etna",
            "grafico INGV",
        ],
        "distribution": [
            {
                "@type": "DataDownload",
                "encodingFormat": "text/csv",
                "contentUrl": chart_url,
                "description": "Visualizzazione interattiva del tremore vulcanico basata su dati INGV.",
            }
        ],
        "measurementTechnique": "Analisi dei segnali di tremore vulcanico registrati dalle stazioni sismiche INGV.",
        "variableMeasured": [
            {
                "@type": "PropertyValue",
                "name": "Ampiezza del tremore vulcanico",
                "unitText": "mV",
            }
        ],
        "spatialCoverage": {
            "@type": "Place",
            "name": "Monte Etna, Sicilia, Italia",
            "geo": {
                "@type": "GeoCoordinates",
                "latitude": 37.751,
                "longitude": 14.9934,
            },
        },
    }
    if temporal_coverage:
        dataset_structured_data["temporalCoverage"] = temporal_coverage
    if data_points:
        dataset_structured_data["numberOfDataPoints"] = data_points

    faq_structured_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Ogni quanto vengono aggiornati i dati del tremore vulcanico?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Il grafico si aggiorna automaticamente ogni cinque minuti, sincronizzandosi con l'ultimo feed pubblico dell'INGV per garantire una lettura quasi real-time del tremore.",
                },
            },
            {
                "@type": "Question",
                "name": "Cosa indica il valore di ampiezza in millivolt?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "L'ampiezza in millivolt rappresenta l'energia delle vibrazioni interne dell'Etna. Valori sotto 1 mV descrivono un'attività bassa, tra 1 e 5 mV un'attività moderata e oltre 5 mV possibili fenomeni eruttivi imminenti.",
                },
            },
        ],
    }

    software_structured_data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "EtnaMonitor",
        "applicationCategory": "WebApplication",
        "operatingSystem": "Web",
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "EUR",
        },
        "url": canonical_home,
        "description": "Piattaforma web per il monitoraggio del tremore vulcanico dell'Etna con grafici interattivi e alert personalizzabili.",
    }

    page_structured_data = [
        webpage_structured_data,
        dataset_structured_data,
        faq_structured_data,
        software_structured_data,
    ]

    csv_snapshot = {
        "path": str(csv_path),
        "rows": data_points,
        "placeholder_reason": placeholder_reason,
        "has_data": placeholder_reason is None,
    }

    debug_requested = (request.args.get("dbg") or "").strip().lower() in {"1", "true", "yes"}
    show_csv_debug = debug_requested and is_owner_or_admin(get_current_user())
    if show_csv_debug:
        csv_debug = {
            "csv_path": str(csv_path),
            "mtime_utc": csv_mtime_utc,
            "rowcount": data_points,
            "first_ts": temporal_start_iso,
            "last_ts": temporal_end_iso,
        }
        current_app.logger.info(
            "[HOME] CSV debug path=%s mtime=%s rows=%s first_ts=%s last_ts=%s",
            csv_debug["csv_path"],
            csv_debug["mtime_utc"],
            csv_debug["rowcount"],
            csv_debug["first_ts"],
            csv_debug["last_ts"],
        )

    return render_template(
        "index.html",
        labels=timestamps,
        values=values,
        page_title=page_title,
        page_description=page_description,
        page_og_title=page_title,
        page_og_description=page_description,
        page_og_image=og_image,
        page_structured_data=page_structured_data,
        latest_value=latest_value,
        latest_timestamp_iso=latest_timestamp_iso,
        latest_timestamp_display=latest_timestamp_display,
        data_points_count=data_points,
        temporal_coverage=temporal_coverage,
        csv_snapshot=csv_snapshot,
        show_csv_debug=show_csv_debug,
        csv_debug=csv_debug,
        plot_html=plot_html,
    )


@bp.route("/ads.txt")
@cache.cached(timeout=3600)
def ads_txt():
    project_root = Path(current_app.root_path).parent
    return send_from_directory(project_root, "ads.txt", mimetype="text/plain")

@bp.route("/pricing")
def pricing():
    return render_template(
        "pricing.html",
        page_title="Prezzi e piani – EtnaMonitor",
        page_description="Scopri i piani Free e Premium di EtnaMonitor per accedere a grafici avanzati e avvisi sul tremore dell'Etna.",
        page_og_title="Prezzi e piani – EtnaMonitor",
        page_og_description="Scopri i piani Free e Premium di EtnaMonitor per accedere a grafici avanzati e avvisi sul tremore dell'Etna.",
    )


@bp.route("/etna-bot")
def etna_bot():
    page_title = "EtnaBot – Notifiche Telegram sul tremore dell'Etna"
    page_description = (
        "Attiva EtnaBot per ricevere alert automatici via Telegram sul tremore vulcanico dell'Etna con soglie personalizzabili."
    )

    page_structured_data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "EtnaBot",
        "operatingSystem": "Telegram",
        "applicationCategory": "UtilityApplication",
        "description": page_description,
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "EUR",
        },
    }

    return render_template(
        "etna_bot.html",
        page_title=page_title,
        page_description=page_description,
        page_og_title=page_title,
        page_og_description=page_description,
        page_structured_data=page_structured_data,
    )


@bp.route("/bot")
def bot_redirect():
    return redirect(url_for("main.etna_bot"))


@bp.route("/eruzione-etna-oggi")
def eruzione_oggi():
    """Real-time eruption monitoring page for high-volume search queries."""
    from datetime import datetime
    
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH")
    csv_path = Path(csv_path_setting or "/var/tmp/curva.csv")
    
    # Reuse data loading logic from index
    preview_rows: list[dict[str, object]] = []
    latest_value: float | None = None
    latest_timestamp_display: str | None = None
    placeholder_reason: str | None = None
    activity_level = "unknown"
    activity_level_text = "In caricamento"
    
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            if "timestamp" in df.columns and not df.empty:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df = df.dropna(subset=["timestamp"])
                
                if not df.empty:
                    df = df.sort_values("timestamp")
                    preview_slice = df.tail(2016)
                    preview_rows = []
                    for row in preview_slice.itertuples(index=False):
                        value = getattr(row, "value", None)
                        if value is None:
                            continue
                        ts = row.timestamp
                        preview_rows.append({
                            "timestamp": to_iso_utc(ts),
                            "value": float(value),
                        })
                    
                    latest_value = float(df["value"].iloc[-1])
                    temporal_end = df["timestamp"].iloc[-1]
                    temporal_end_display = (
                        temporal_end.tz_convert("UTC")
                        if getattr(temporal_end, "tz", None) is not None
                        else temporal_end.tz_localize("UTC")
                    )
                    latest_timestamp_display = temporal_end_display.strftime("%d/%m/%Y %H:%M")
                    
                    # Determine activity level
                    if latest_value < 0.5:
                        activity_level = "low"
                        activity_level_text = "Basso (normale)"
                    elif latest_value < 1.0:
                        activity_level = "moderate"
                        activity_level_text = "Moderato"
                    elif latest_value < 2.0:
                        activity_level = "elevated"
                        activity_level_text = "Elevato"
                    else:
                        activity_level = "high"
                        activity_level_text = "Molto elevato"
                else:
                    placeholder_reason = "empty"
            else:
                placeholder_reason = "missing_timestamp"
        except Exception as exc:
            placeholder_reason = "error"
            current_app.logger.exception("[ERUPTION_TODAY] Failed to read tremor CSV")
    else:
        placeholder_reason = "missing"
    
    csv_snapshot = type('obj', (object,), {
        'has_data': placeholder_reason is None,
        'path': csv_path,
        'placeholder_reason': placeholder_reason
    })()
    
    current_date = datetime.now().strftime("%d/%m/%Y")
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    
    # LiveBlogPosting structured data for real-time updates
    page_structured_data = {
        "@context": "https://schema.org",
        "@type": "LiveBlogPosting",
        "headline": f"Eruzione Etna Oggi {current_date} – Monitoraggio Live",
        "description": "Aggiornamenti in tempo reale sull'attività dell'Etna: grafico tremore INGV, webcam live e bollettini ufficiali",
        "datePublished": datetime.now().isoformat(),
        "dateModified": datetime.now().isoformat(),
        "author": {
            "@type": "Organization",
            "name": "EtnaMonitor",
            "url": url_for('main.index', _external=True)
        },
        "publisher": {
            "@type": "Organization",
            "name": "EtnaMonitor",
            "url": url_for('main.index', _external=True),
            "logo": {
                "@type": "ImageObject",
                "url": og_image
            }
        },
        "coverageStartTime": datetime.now().isoformat(),
        "liveBlogUpdate": [
            {
                "@type": "BlogPosting",
                "headline": f"Tremore attuale: {latest_value:.2f} mV" if latest_value else "Dati in caricamento",
                "articleBody": f"Ultimo aggiornamento INGV: {latest_timestamp_display}" if latest_timestamp_display else "In attesa di dati",
                "datePublished": datetime.now().isoformat()
            }
        ]
    }
    
    return render_template(
        "eruzione_oggi.html",
        page_title=f"Eruzione Etna oggi {current_date} – Dati INGV | EtnaMonitor",
        page_description=(
            "Aggiornamenti affidabili sull'attività dell'Etna oggi: grafico tremore INGV, webcam live, "
            "bollettini ufficiali e indicazioni di sicurezza."
        ),
        page_og_image=og_image,
        canonical_url=url_for('main.eruzione_oggi', _external=True),
        page_structured_data=page_structured_data,
        csv_snapshot=csv_snapshot,
        preview_rows=preview_rows,
        latest_value=latest_value,
        latest_timestamp_display=latest_timestamp_display,
        activity_level=activity_level,
        activity_level_text=activity_level_text,
        current_date=current_date,
    )


@bp.route("/webcam-etna")
def webcam_etna():
    og_image = "https://embed.skylinewebcams.com/img/741.jpg"
    canonical = url_for("main.webcam_etna", _external=True)

    webcams = [
        {
            "name": "Vulcano Etna – Crateri sommitali",
            "url": "https://www.skylinewebcams.com/it/webcam/italia/sicilia/catania/vulcano-etna.html",
            "thumbnail": "https://embed.skylinewebcams.com/img/741.jpg",
            "description": "Vista panoramica sulle Bocchette e i crateri sommitali dell'Etna.",
        },
        {
            "name": "Vulcano Etna – Versante Nord",
            "url": "https://www.skylinewebcams.com/it/webcam/italia/sicilia/catania/vulcano-etna-versante-nord.html",
            "thumbnail": "https://embed.skylinewebcams.com/img/1737.jpg",
            "description": "Inquadratura dal versante nord con dettaglio sull'area di Piano Provenzana.",
        },
        {
            "name": "Vulcano Etna – Versante Sud",
            "url": "https://www.skylinewebcams.com/it/webcam/italia/sicilia/catania/vulcano-etna-crateri.html",
            "thumbnail": "https://embed.skylinewebcams.com/img/1092.jpg",
            "description": "Prospettiva sui crateri meridionali con il Rifugio Sapienza in primo piano.",
        },
    ]

    weather_preview: dict[str, object] | None = None
    weather_error: str | None = None

    try:
        weather_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 37.75,
                "longitude": 14.99,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,weather_code",
                "hourly": "precipitation_probability",
                "forecast_days": 1,
                "timezone": "Europe/Rome",
            },
            timeout=5,
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()
    except requests.RequestException:
        weather_error = "Impossibile recuperare i dati meteo in tempo reale. Riprova più tardi."
    else:
        current = (weather_data or {}).get("current") or {}
        units = (weather_data or {}).get("current_units") or {}
        hourly = (weather_data or {}).get("hourly") or {}
        precipitation_probability = None

        hourly_probabilities = hourly.get("precipitation_probability") or []
        hourly_times = hourly.get("time") or []
        current_time = current.get("time")

        if hourly_probabilities and hourly_times and current_time in hourly_times:
            try:
                precipitation_probability = hourly_probabilities[hourly_times.index(current_time)]
            except (ValueError, IndexError):
                precipitation_probability = hourly_probabilities[0]
        elif hourly_probabilities:
            precipitation_probability = hourly_probabilities[0]

        wind_direction_deg = current.get("wind_direction_10m")
        updated_at_display, updated_at_iso = _format_weather_timestamp(current.get("time"))

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
            "updated_at": updated_at_display,
            "updated_at_iso": updated_at_iso,
            "weather_code": current.get("weather_code"),
            "weather_description": _describe_weather_code(current.get("weather_code")),
        }

    page_structured_data: list[dict[str, object]] = [
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Webcam Etna in diretta",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index + 1,
                    "name": camera["name"],
                    "url": camera["url"],
                    "image": camera["thumbnail"],
                    "description": camera["description"],
                }
                for index, camera in enumerate(webcams)
            ],
        }
    ]

    if weather_preview and weather_preview.get("updated_at_iso"):
        page_structured_data.append(
            {
                "@context": "https://schema.org",
                "@type": "WeatherObservation",
                "name": "Condizioni meteo live sull'Etna",
                "observationDate": weather_preview["updated_at_iso"],
                "weatherCondition": weather_preview.get("weather_description"),
                "temperature": weather_preview.get("temperature"),
                "windSpeed": weather_preview.get("wind_speed"),
                "windDirection": weather_preview.get("wind_direction"),
                "humidity": weather_preview.get("humidity"),
            }
        )

    return render_template(
        "webcam.html",
        page_title="Webcam Etna in diretta e meteo – EtnaMonitor",
        page_description=(
            "Webcam live dell'Etna con meteo aggiornato, spiegazioni per leggere le immagini e "
            "dati EtnaMonitor sul tremore e gli hotspot."
        ),
        page_og_title="Webcam Etna in diretta – EtnaMonitor",
        page_og_description=(
            "Tre webcam live dell'Etna con meteo aggiornato e un contesto dati chiaro firmato EtnaMonitor."
        ),
        page_og_image=og_image,
        canonical_url=canonical,
        webcams=webcams,
        weather_preview=weather_preview,
        weather_error=weather_error,
        page_structured_data=page_structured_data,
    )


@bp.route("/sentieri")
def sentieri():
    return render_template(
        "sentieri.html",
        page_title="Sentieri Etna – Mappa e percorsi con POI | EtnaMonitor",
        page_description=(
            "Esplora i sentieri dell'Etna con mappa interattiva, difficoltà, lunghezze e punti di interesse "
            "filtrabili per categoria."
        ),
        page_og_title="Sentieri Etna – Mappa e percorsi",
        page_og_description=(
            "Mappa sentieri Etna con tracciati, POI e filtri per grotte, monti e rifugi."
        ),
        canonical_url=url_for("main.sentieri", _external=True),
    )


@bp.route("/sentieri/<slug>")
def sentiero_detail(slug: str):
    trails_data = _load_sentieri_geojson("trails")
    if not trails_data:
        abort(404)

    trail_feature = None
    for feature in trails_data.get("features", []):
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        if properties.get("slug") == slug:
            trail_feature = properties
            break

    if not trail_feature:
        abort(404)

    # TODO: increment trail visits once a dedicated model/table is available.

    return render_template(
        "sentiero_detail.html",
        page_title=f"{trail_feature.get('name')} – Sentiero Etna",
        page_description=trail_feature.get("description"),
        page_og_title=trail_feature.get("name"),
        page_og_description=trail_feature.get("description"),
        canonical_url=url_for("main.sentiero_detail", slug=slug, _external=True),
        trail=trail_feature,
    )


@bp.route("/hotspots")
def hotspots():
    config = HotspotsConfig.from_env()
    if not config.enabled:
        return abort(404)

    cache = read_cache(config.cache_path)
    if cache is None:
        cache = unavailable_payload("Dati non disponibili")

    items = cache.get("items", []) if cache.get("available") else []
    generated_at_display = _format_hotspots_timestamp(cache.get("generated_at"))

    west, south, east, north = config.bbox_coords
    map_center = {"lat": (south + north) / 2, "lon": (west + east) / 2}
    map_bounds = [[south, west], [north, east]]

    return render_template(
        "hotspots.html",
        page_title="Hotspot Etna oggi: anomalie termiche satellitari | EtnaMonitor",
        page_description="Mappa aggiornata degli hotspot termici satellitari sull'Etna (NASA FIRMS) con intensità, stato e coordinate nelle ultime 24 ore.",
        page_og_title="Hotspot termici satellitari sull'Etna",
        page_og_description="Consulta gli hotspot termici rilevati da NASA FIRMS sull'Etna con intensità, stato e coordinate aggiornate.",
        canonical_url=url_for("main.hotspots", _external=True),
        hotspots=cache,
        items=items,
        generated_at_display=generated_at_display,
        map_center=map_center,
        map_bounds=map_bounds,
    )


@bp.route("/observatory")
def observatory():
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH")
    csv_path = Path(csv_path_setting or "/var/tmp/curva.csv")
    preview_rows: list[dict[str, object]] = []
    latest_timestamp_display: str | None = None
    data_points = 0
    placeholder_reason: str | None = None

    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            if "timestamp" not in df.columns:
                placeholder_reason = "missing_timestamp"
            else:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df = df.dropna(subset=["timestamp"])
                if df.empty:
                    placeholder_reason = "empty"
                else:
                    df = df.sort_values("timestamp")
                    data_points = len(df)
                    preview_slice = df.tail(2016)
                    preview_rows = [
                        {
                            "timestamp": to_iso_utc(row.timestamp),
                            "value": float(getattr(row, "value", 0)),
                        }
                        for row in preview_slice.itertuples(index=False)
                        if getattr(row, "value", None) is not None
                    ]
                    temporal_end = df["timestamp"].iloc[-1]
                    temporal_end_display = (
                        temporal_end.tz_convert("UTC")
                        if getattr(temporal_end, "tz", None) is not None
                        else temporal_end.tz_localize("UTC")
                    )
                    latest_timestamp_display = temporal_end_display.strftime("%d/%m/%Y %H:%M")
        except Exception:
            placeholder_reason = "error"
            current_app.logger.exception("[OBSERVATORY] Failed to read tremor CSV")
    else:
        placeholder_reason = "missing"

    csv_snapshot = {
        "path": str(csv_path),
        "rows": data_points,
        "placeholder_reason": placeholder_reason,
        "has_data": placeholder_reason is None,
    }

    hotspots_config = HotspotsConfig.from_env()
    hotspots_cache = read_cache(hotspots_config.cache_path) if hotspots_config.enabled else None
    hotspots_last_fetch = None
    if hotspots_cache:
        hotspots_last_fetch = hotspots_cache.get("last_fetch_at") or hotspots_cache.get("generated_at")

    hotspot_count_24h = 0
    hotspot_latest_record = None
    try:
        window_start = datetime.now(timezone.utc) - timedelta(hours=24)
        hotspot_count_24h = (
            HotspotsRecord.query.filter(HotspotsRecord.acq_datetime >= window_start).count()
        )
        hotspot_latest_record = (
            HotspotsRecord.query.order_by(HotspotsRecord.acq_datetime.desc()).first()
        )
    except SQLAlchemyError:
        current_app.logger.exception("[OBSERVATORY] Hotspots summary lookup failed")

    copernicus_latest = get_latest_copernicus_image()
    copernicus_image_url = resolve_copernicus_image_url(copernicus_latest)

    copernicus_acquired_display = _format_display_datetime(
        copernicus_latest.acquired_at if copernicus_latest else None
    )
    copernicus_updated_display = _format_display_datetime(
        copernicus_latest.created_at if copernicus_latest else None
    )
    copernicus_bbox = resolve_copernicus_bbox(copernicus_latest)
    current_app.logger.info(
        "[OBSERVATORY] Copernicus bbox=%s product_id=%s",
        copernicus_bbox,
        copernicus_latest.product_id if copernicus_latest else None,
    )

    return render_template(
        "observatory.html",
        page_title="Osservatorio Etna – Tremore, Hotspot NASA e Copernicus",
        page_description=(
            "Pagina unica di osservazione EtnaMonitor con grafico del tremore INGV, "
            "hotspot NASA FIRMS e immagini satellitari Copernicus Sentinel-2."
        ),
        canonical_url=url_for("main.observatory", _external=True),
        csv_snapshot=csv_snapshot,
        preview_rows=preview_rows,
        latest_timestamp_display=latest_timestamp_display,
        data_points_count=data_points,
        hotspots_summary={
            "last_fetch_display": _format_hotspots_timestamp(hotspots_last_fetch),
            "count_24h": hotspot_count_24h,
            "latest_acquired_display": _format_display_datetime(
                hotspot_latest_record.acq_datetime if hotspot_latest_record else None
            ),
        },
        copernicus_latest=copernicus_latest,
        copernicus_image_url=copernicus_image_url,
        copernicus_acquired_display=copernicus_acquired_display,
        copernicus_updated_display=copernicus_updated_display,
        copernicus_bbox=copernicus_bbox,
    )


@bp.route("/tecnologia")
def tecnologia():
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    return render_template(
        "tecnologia.html",
        page_title="Tecnologia EtnaMonitor – Pipeline dati INGV, AI e Telegram",
        page_description="Scopri la pipeline tecnologica di EtnaMonitor: download PNG INGV, estrazione dati, normalizzazione CSV, modelli AI e distribuzione tramite bot Telegram.",
        page_og_title="Tecnologia EtnaMonitor – Pipeline dati INGV, AI e Telegram",
        page_og_description="Scopri la pipeline tecnologica di EtnaMonitor: download PNG INGV, estrazione dati, normalizzazione CSV, modelli AI e distribuzione tramite bot Telegram.",
        page_og_image=og_image,
        canonical_url=url_for('main.tecnologia', _external=True),
    )


@bp.route("/progetto")
def progetto():
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    return render_template(
        "progetto.html",
        page_title="Il progetto EtnaMonitor – Visione, roadmap e filosofia",
        page_description="Scopri la visione di EtnaMonitor: trasparenza sui dati del tremore vulcanico dell'Etna, roadmap evolutiva e collaborazione con la community scientifica.",
        page_og_title="Il progetto EtnaMonitor – Visione, roadmap e filosofia",
        page_og_description="Scopri la visione di EtnaMonitor: trasparenza sui dati del tremore vulcanico dell'Etna, roadmap evolutiva e collaborazione con la community scientifica.",
        page_og_image=og_image,
        canonical_url=url_for('main.progetto', _external=True),
    )


@bp.route("/team")
def team():
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    return render_template(
        "team.html",
        page_title="Team EtnaMonitor – Chi c'è dietro il monitoraggio",
        page_description="Conosci il team di EtnaMonitor: missione, competenze e valori di trasparenza che guidano il monitoraggio del tremore vulcanico dell'Etna.",
        page_og_title="Team EtnaMonitor – Chi c'è dietro il monitoraggio",
        page_og_description="Conosci il team di EtnaMonitor: missione, competenze e valori di trasparenza che guidano il monitoraggio del tremore vulcanico dell'Etna.",
        page_og_image=og_image,
        canonical_url=url_for('main.team', _external=True),
    )


@bp.route("/news")
def news():
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    return render_template(
        "news.html",
        page_title="News EtnaMonitor – Aggiornamenti su tremore e piattaforma",
        page_description="Rimani aggiornato sulle news di EtnaMonitor: articoli, analisi del tremore vulcanico dell'Etna e aggiornamenti sulla piattaforma.",
        page_og_title="News EtnaMonitor – Aggiornamenti su tremore e piattaforma",
        page_og_description="Rimani aggiornato sulle news di EtnaMonitor: articoli, analisi del tremore vulcanico dell'Etna e aggiornamenti sulla piattaforma.",
        page_og_image=og_image,
        canonical_url=url_for('main.news', _external=True),
    )


@bp.route("/faq")
def faq():
    og_image = url_for('static', filename='icons/icon-512.png', _external=True)
    
    # FAQPage structured data for Google Featured Snippets
    faq_structured_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Cosa significa quando il tremore dell'Etna aumenta?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Il tremore vulcanico è una vibrazione continua del terreno causata dal movimento di magma, gas e fluidi all'interno del vulcano. Un aumento del tremore può indicare: aumento dell'attività magmatica (il magma si muove verso la superficie), degassamento intenso (i gas si liberano dal magma), o fratturazione delle rocce. Un aumento del tremore non significa necessariamente che ci sarà un'eruzione imminente."
                }
            },
            {
                "@type": "Question",
                "name": "Come capire se l'Etna sta per eruttare?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "I vulcanologi INGV monitorano diversi parametri: tremore vulcanico (aumenti prolungati possono precedere un'eruzione), sciami sismici (terremoti frequenti indicano movimenti di magma), deformazione del suolo (rigonfiamento dell'edificio vulcanico), degassamento (aumento delle emissioni di SO₂), e anomalie termiche. Segui sempre i bollettini ufficiali dell'INGV Catania per previsioni affidabili."
                }
            },
            {
                "@type": "Question",
                "name": "Il grafico INGV del tremore è affidabile?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Sì, i dati del tremore vulcanico pubblicati dall'INGV sono estremamente affidabili e provengono da una rete di sensori sismici calibrati posizionati sull'Etna. EtnaMonitor scarica e visualizza questi dati ufficiali ogni 5 minuti senza modificare i valori, ma li rende più facili da consultare con grafici interattivi."
                }
            },
            {
                "@type": "Question",
                "name": "Cosa fare se sono in escursione sull'Etna e il tremore aumenta?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Mantieni la calma (un aumento del tremore non significa pericolo immediato), allontanati dai crateri scendendo di quota, segui le indicazioni delle guide alpine certificate, monitora i canali ufficiali INGV e Protezione Civile. In caso di eruzione improvvisa, allontanati dalla zona sommitale, proteggi naso e bocca dalla cenere, e chiama il 118 per emergenze mediche o il 1515 per soccorso alpino."
                }
            },
            {
                "@type": "Question",
                "name": "Dove trovare i bollettini ufficiali INGV sull'Etna?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "I bollettini ufficiali sono disponibili su: INGV Catania (www.ct.ingv.it) per bollettini settimanali e comunicati urgenti, la sezione monitoraggio sismico per grafici aggiornati, Protezione Civile Sicilia per allerte di sicurezza, e Twitter @INGVvulcani per aggiornamenti rapidi durante eventi significativi."
                }
            },
            {
                "@type": "Question",
                "name": "Come funziona il bot Telegram EtnaMonitor?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Il bot Telegram @etna_turi_bot invia notifiche automatiche quando il tremore supera soglie personalizzabili. Offre 4 livelli di allerta (Informativo, Attenzione, Preallarme, Operativo), include snapshot del grafico e link alle webcam. Per attivarlo: registrati su EtnaMonitor, vai su @etna_turi_bot, clicca Start e configura le soglie dal dashboard."
                }
            },
            {
                "@type": "Question",
                "name": "Le webcam dell'Etna mostrano eruzioni in diretta?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Sì, le webcam disponibili su EtnaMonitor mostrano immagini live dei crateri sommitali, versante nord (Piano Provenzana) e versante sud (Rifugio Sapienza). Durante un'eruzione permettono di vedere fontane di lava, colate, emissioni di cenere e gas, e attività stromboliana notturna. La visibilità dipende dalle condizioni meteo."
                }
            },
            {
                "@type": "Question",
                "name": "Quando è sicuro fare trekking sull'Etna?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "È sicuro quando: il tremore è basso e stabile (zona verde), non ci sono alert INGV in corso, le condizioni meteo sono buone, e si utilizza una guida certificata sopra i 2.500m. Fino a 2.900m (Rifugio Sapienza) è sempre accessibile tranne ordinanze specifiche. Zone sommitali (2.900-3.300m) solo con guida e senza restrizioni INGV. Rispetta sempre le ordinanze della Protezione Civile."
                }
            }
        ]
    }
    
    return render_template(
        "faq.html",
        page_title="FAQ Etna – Domande frequenti su tremore, eruzioni e monitoraggio",
        page_description="Risposte alle domande più frequenti sul tremore vulcanico dell'Etna, come interpretare il grafico INGV, cosa fare in caso di eruzione e come funzionano gli alert.",
        page_og_title="FAQ Etna – Domande frequenti su tremore, eruzioni e monitoraggio",
        page_og_description="Risposte alle domande più frequenti sul tremore vulcanico dell'Etna, come interpretare il grafico INGV, cosa fare in caso di eruzione e come funzionano gli alert.",
        page_og_image=og_image,
        canonical_url=url_for('main.faq', _external=True),
        page_structured_data=faq_structured_data,
    )


_ETNA3D_CSP = copy.deepcopy(BASE_CSP)
_SKETCHFAB_SOURCES = [
    "https://sketchfab.com",
    "https://*.sketchfab.com",
    "https://static.sketchfab.com",
]
for directive in ("frame-src", "child-src"):
    allowed_sources = _ETNA3D_CSP.setdefault(directive, [])
    if isinstance(allowed_sources, str):
        allowed_sources = [allowed_sources]
        _ETNA3D_CSP[directive] = allowed_sources
    for source in _SKETCHFAB_SOURCES:
        if source not in allowed_sources:
            allowed_sources.append(source)


@bp.route("/etna-3d")
@talisman(frame_options="ALLOWALL", content_security_policy=_ETNA3D_CSP)
def etna3d():
    user = get_current_user()
    plan_type = (getattr(user, "plan_type", "free") or "free") if user else "free"

    return render_template(
        "etna3d.html",
        plan_type=plan_type,
        page_title="Modello 3D dell'Etna – EtnaMonitor",
        page_description="Esplora il modello 3D interattivo dell'Etna con visualizzazione Sketchfab in tema scuro.",
        page_og_title="Modello 3D dell'Etna – EtnaMonitor",
        page_og_description="Esplora il modello 3D interattivo dell'Etna con visualizzazione Sketchfab in tema scuro.",
    )


@bp.route("/roadmap")
def roadmap():
    return render_template(
        "roadmap.html",
        page_title="Roadmap – Evoluzione di EtnaMonitor",
        page_description="Aggiornamenti pianificati, nuove funzionalità e obiettivi futuri per EtnaMonitor.",
        page_og_title="Roadmap – Evoluzione di EtnaMonitor",
        page_og_description="Aggiornamenti pianificati, nuove funzionalità e obiettivi futuri per EtnaMonitor.",
    )


@bp.route("/experience")
def experience():
    return render_template(
        "experience.html",
        page_title="Etna Experience – Vivi l'Etna come un insider",
        page_description=(
            "La pagina madre di guide, hotel e ristoranti selezionati da EtnaMonitor per vivere l'Etna in modo autentico."
        ),
        page_og_title="Etna Experience – Vivi l'Etna come un insider",
        page_og_description="Scopri guide autorizzate, hotel e ristoranti consigliati per la tua esperienza sull'Etna.",
        canonical_url=url_for("main.experience", _external=True),
    )


@bp.route("/about")
def about():
    description = (
        "Scopri cos'è EtnaMonitor: piattaforma indipendente per monitoraggio del tremore vulcanico dell'Etna, notifiche Telegram"
        " e dashboard realtime."
    )
    about_structured_data = {
        "@context": "https://schema.org",
        "@type": "AboutPage",
        "name": "Cos'è EtnaMonitor",
        "description": description,
        "url": url_for("main.about", _external=True),
        "creator": {
            "@type": "Person",
            "name": "Salvatore Ferro",
            "url": url_for("main.about", _external=True),
        },
        "publisher": {
            "@type": "Organization",
            "name": "EtnaMonitor",
            "url": url_for("main.index", _external=True),
        },
    }
    person_structured_data = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": "Salvatore Ferro",
        "url": url_for("main.about", _external=True),
        "worksFor": {
            "@type": "Organization",
            "name": "EtnaMonitor",
            "url": url_for("main.index", _external=True),
        },
    }
    organization_structured_data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "EtnaMonitor",
        "url": url_for("main.index", _external=True),
        "founder": {
            "@type": "Person",
            "name": "Salvatore Ferro",
            "url": url_for("main.about", _external=True),
        },
    }

    return render_template(
        "about.html",
        page_title="Cos'è EtnaMonitor – Monitoraggio tremore Etna",
        page_description="Scopri cos'è EtnaMonitor: piattaforma indipendente per monitoraggio tremore vulcanico dell'Etna, notifiche Telegram e grafico realtime.",
        page_og_title="Cos'è EtnaMonitor – Monitoraggio tremore Etna",
        page_og_description="Scopri cos'è EtnaMonitor: piattaforma indipendente per monitoraggio tremore vulcanico dell'Etna, notifiche Telegram e grafico realtime.",
        canonical_url=url_for("main.about", _external=True),
        page_structured_data=[
            about_structured_data,
            person_structured_data,
            organization_structured_data,
        ],
    )


@bp.route("/sponsor")
def sponsor():
    return render_template(
        "sponsor.html",
        page_title="Sponsor – Supporta EtnaMonitor",
        page_description="Scopri i partner che sostengono EtnaMonitor e le opportunità di sponsorship.",
        page_og_title="Sponsor – Supporta EtnaMonitor",
        page_og_description="Scopri i partner che sostengono EtnaMonitor e le opportunità di sponsorship.",
    )


@bp.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        page_title="Informativa Privacy – EtnaMonitor",
        page_description="Come EtnaMonitor gestisce i dati personali in conformità con il GDPR.",
        page_og_title="Informativa Privacy – EtnaMonitor",
        page_og_description="Come EtnaMonitor gestisce i dati personali in conformità con il GDPR.",
    )


@bp.route("/terms")
def terms():
    return redirect(url_for("main.termini"))


@bp.route("/cookies")
def cookies():
    return redirect(url_for("main.cookie"))


@bp.route("/termini")
def termini():
    return render_template(
        "termini.html",
        page_title="Termini di servizio – EtnaMonitor",
        page_description="Condizioni complete di utilizzo di EtnaMonitor, del sito e dei bot Telegram correlati.",
        page_og_title="Termini di servizio – EtnaMonitor",
        page_og_description="Condizioni complete di utilizzo di EtnaMonitor, del sito e dei bot Telegram correlati.",
    )


@bp.route("/cookie")
def cookie():
    return render_template(
        "cookie.html",
        page_title="Cookie policy – EtnaMonitor",
        page_description="Spiegazione completa dei cookie tecnici, analitici e di terze parti utilizzati da EtnaMonitor.",
        page_og_title="Cookie policy – EtnaMonitor",
        page_og_description="Spiegazione completa dei cookie tecnici, analitici e di terze parti utilizzati da EtnaMonitor.",
    )


@bp.route("/sostieni-il-progetto")
def sostieni_progetto():
    return render_template(
        "sostieni_progetto.html",
        page_title="Sostieni EtnaMonitor",
        page_description="Perché sostenere EtnaMonitor, come funziona il progetto e come contribuire via PayPal o contattando il team.",
        page_og_title="Sostieni EtnaMonitor",
        page_og_description="Perché sostenere EtnaMonitor, come funziona il progetto e come contribuire via PayPal o contattando il team.",
    )

@bp.route("/healthz")
def healthcheck():
    uptime = None
    start_time = current_app.config.get("START_TIME")
    if isinstance(start_time, datetime):
        uptime = (datetime.utcnow() - start_time).total_seconds()

    csv_metrics = get_csv_metrics()

    database_status = get_alembic_status(current_app)
    db_online = bool(database_status.get("database_online"))
    db_current = bool(database_status.get("is_up_to_date"))

    premium_count = 0
    premium_error = None
    if db_online:
        try:
            premium_count = (
                db.session.query(User)
                .filter(or_(User.premium.is_(True), User.is_premium.is_(True)))
                .count()
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            premium_error = str(exc)
            current_app.logger.warning("[HEALTH] Failed to count premium users: %s", exc)
    else:
        premium_error = database_status.get("error")

    telegram_status = current_app.config.get("TELEGRAM_BOT_STATUS", {})

    ok = db_online and db_current
    payload = {
        "ok": ok,
        "uptime_seconds": uptime,
        "csv": csv_metrics,
        "telegram_bot": telegram_status,
        "premium_users": premium_count,
        "premium_users_error": premium_error,
        "build_sha": current_app.config.get("BUILD_SHA"),
        "database": database_status,
    }

    if current_app.debug:
        payload["db_status"] = database_status

    current_app.logger.info("[HEALTH] ok=%s premium_users=%s", payload["ok"], premium_count)
    status_code = 200 if ok else 503
    return jsonify(payload), status_code


@bp.route("/ga4/test-csp")
def ga4_test_csp():
    return jsonify(dict(csp=copy.deepcopy(talisman.content_security_policy)))


@bp.route("/csp/echo")
def csp_echo():
    response = jsonify({"header": ""})
    response = apply_csp_headers(response)
    header_value = response.headers.get("Content-Security-Policy", "")
    response.set_data(json.dumps({"header": header_value}))
    response.mimetype = "application/json"
    return response


@bp.route("/csp/probe")
def csp_probe():
    policy = copy.deepcopy(talisman.content_security_policy)
    policy_str = serialize_csp(policy)
    html = render_template_string(
        """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Content Security Policy Probe</title>
    <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css\">
  </head>
  <body>
    <h1>Content Security Policy Probe</h1>
    <pre>{{ policy }}</pre>
    <script async src=\"https://www.googletagmanager.com/gtag/js?id=AW-17681413584\"></script>
  </body>
</html>""",
        policy=policy_str,
    )
    return html
