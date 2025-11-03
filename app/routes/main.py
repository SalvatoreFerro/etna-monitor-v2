from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user

from ..utils.auth import get_current_user

from app.models import db
from app.models.user import User
from sqlalchemy import or_, text

from ..extensions import cache
from ..utils.metrics import get_csv_metrics, record_csv_error, record_csv_read
from app.security import build_csp, talisman
from backend.utils.time import to_iso_utc

bp = Blueprint("main", __name__)


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


@bp.route("/")
@cache.cached(timeout=90, key_prefix=_index_cache_key)
def index():
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH")
    csv_path = Path(csv_path_setting or "/var/tmp/curva.csv")
    timestamps: list[str] = []
    values: list[float] = []
    preview_rows: list[dict[str, object]] = []
    temporal_start_iso: str | None = None
    temporal_end_iso: str | None = None
    temporal_coverage: str | None = None
    latest_value: float | None = None
    latest_timestamp_iso: str | None = None
    latest_timestamp_display: str | None = None
    data_points = 0
    placeholder_reason: str | None = None

    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            placeholder_reason = "error"
            current_app.logger.exception("[HOME] Failed to read tremor CSV")
            record_csv_error(str(exc))
        else:
            if "timestamp" not in df.columns:
                placeholder_reason = "missing_timestamp"
                record_csv_error("curva.csv missing timestamp column")
            else:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df = df.dropna(subset=["timestamp"])

                if df.empty:
                    placeholder_reason = "empty"
                    record_csv_error("curva.csv empty")
                else:
                    df = df.sort_values("timestamp")
                    timestamps = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
                    values = df["value"].tolist()
                    data_points = len(df)

                    preview_slice = df.tail(2016)
                    preview_rows = []
                    for row in preview_slice.itertuples(index=False):
                        value = getattr(row, "value", None)
                        if value is None:
                            continue
                        ts = row.timestamp
                        preview_rows.append(
                            {
                                "timestamp": to_iso_utc(ts),
                                "value": float(value),
                            }
                        )

                    temporal_start = df["timestamp"].iloc[0]
                    temporal_end = df["timestamp"].iloc[-1]
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
    page_title = "Monitoraggio Etna in tempo reale – Grafico tremore vulcanico INGV"
    page_description = (
        "Grafico aggiornato del tremore vulcanico dell'Etna con dati ufficiali INGV, "
        "indicazioni sulle soglie operative e descrizione del monitoraggio in tempo reale."
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
        preview_rows=preview_rows,
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


_ETNA3D_CSP = build_csp()
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
    return render_template(
        "terms.html",
        page_title="Termini di servizio – EtnaMonitor",
        page_description="Condizioni di utilizzo della piattaforma EtnaMonitor e dei suoi servizi.",
        page_og_title="Termini di servizio – EtnaMonitor",
        page_og_description="Condizioni di utilizzo della piattaforma EtnaMonitor e dei suoi servizi.",
    )


@bp.route("/cookies")
def cookies():
    return render_template(
        "cookies.html",
        page_title="Cookie policy – EtnaMonitor",
        page_description="Informazioni sui cookie utilizzati da EtnaMonitor e su come gestirli.",
        page_og_title="Cookie policy – EtnaMonitor",
        page_og_description="Informazioni sui cookie utilizzati da EtnaMonitor e su come gestirli.",
    )

@bp.route("/healthz")
def healthcheck():
    uptime = None
    start_time = current_app.config.get("START_TIME")
    if isinstance(start_time, datetime):
        uptime = (datetime.utcnow() - start_time).total_seconds()

    csv_metrics = get_csv_metrics()

    premium_count = 0
    try:
        premium_count = (
            db.session.query(User)
            .filter(or_(User.premium.is_(True), User.is_premium.is_(True)))
            .count()
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning("[HEALTH] Failed to count premium users: %s", exc)

    telegram_status = current_app.config.get("TELEGRAM_BOT_STATUS", {})

    payload = {
        "ok": True,
        "uptime_seconds": uptime,
        "csv": csv_metrics,
        "telegram_bot": telegram_status,
        "premium_users": premium_count,
        "build_sha": current_app.config.get("BUILD_SHA"),
    }

    if current_app.debug:
        db_status = {
            "database_revision": None,
            "expected_head": None,
            "is_up_to_date": None,
            "error": None,
        }

        migrations_path = Path(current_app.root_path).parent / "migrations"
        try:
            from alembic.config import Config  # type: ignore import
            from alembic.script import ScriptDirectory  # type: ignore import

            if migrations_path.exists():
                cfg = Config()
                cfg.set_main_option("script_location", str(migrations_path))
                script_dir = ScriptDirectory.from_config(cfg)
                db_status["expected_head"] = script_dir.get_current_head()
            else:
                raise FileNotFoundError(f"Migrations path not found: {migrations_path}")
        except Exception as exc:  # pragma: no cover - diagnostic only
            current_app.logger.warning("[HEALTH] Failed to inspect Alembic head: %s", exc)
            db_status["error"] = f"alembic:{exc}"

        try:
            with db.engine.connect() as connection:
                result = connection.execute(text("SELECT version_num FROM alembic_version"))
                db_revision = result.scalar()
            db_status["database_revision"] = db_revision
            if db_status["expected_head"]:
                db_status["is_up_to_date"] = db_revision == db_status["expected_head"]
        except Exception as exc:  # pragma: no cover - diagnostic only
            current_app.logger.warning("[HEALTH] Failed to fetch alembic_version: %s", exc)
            existing_error = db_status.get("error")
            suffix = f"database:{exc}"
            db_status["error"] = f"{existing_error}; {suffix}" if existing_error else suffix

        payload["db_status"] = db_status

    current_app.logger.info("[HEALTH] ok=%s premium_users=%s", payload["ok"], premium_count)
    return jsonify(payload), 200
