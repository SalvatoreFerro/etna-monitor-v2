import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, send_from_directory, url_for

from ..utils.auth import get_current_user

from app.models import db
from app.models.user import User
from sqlalchemy import or_, text

from ..extensions import cache
from ..utils.metrics import get_csv_metrics, record_csv_error, record_csv_read
from app.security import build_csp, talisman

bp = Blueprint("main", __name__)

@bp.route("/")
@cache.cached(timeout=90)
def index():
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    timestamps: list[str] = []
    values: list[float] = []

    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            if not df.empty:
                timestamps = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
                values = df["value"].tolist()
            record_csv_read(len(df), df["timestamp"].max() if not df.empty else None)
        except Exception as exc:
            current_app.logger.exception("Failed to read tremor CSV for index page")
            record_csv_error(str(exc))
    else:
        current_app.logger.warning("Tremor CSV not found at %s", csv_path)
        record_csv_error(f"Missing CSV at {csv_path}")

    return render_template(
        "index.html",
        labels=timestamps,
        values=values,
        page_title="EtnaMonitor – Monitoraggio Etna in tempo reale",
        page_description="Grafici aggiornati del tremore vulcanico dell'Etna con dati INGV e avvisi personalizzati per gli appassionati.",
        page_og_image=url_for("static", filename="icons/icon-512.png", _external=True),
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
    )


@bp.route("/roadmap")
def roadmap():
    return render_template(
        "roadmap.html",
        page_title="Roadmap – Evoluzione di EtnaMonitor",
        page_description="Aggiornamenti pianificati, nuove funzionalità e obiettivi futuri per EtnaMonitor.",
    )


@bp.route("/sponsor")
def sponsor():
    return render_template(
        "sponsor.html",
        page_title="Sponsor – Supporta EtnaMonitor",
        page_description="Scopri i partner che sostengono EtnaMonitor e le opportunità di sponsorship.",
    )


@bp.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        page_title="Informativa Privacy – EtnaMonitor",
        page_description="Come EtnaMonitor gestisce i dati personali in conformità con il GDPR.",
    )


@bp.route("/terms")
def terms():
    return render_template(
        "terms.html",
        page_title="Termini di servizio – EtnaMonitor",
        page_description="Condizioni di utilizzo della piattaforma EtnaMonitor e dei suoi servizi.",
    )


@bp.route("/cookies")
def cookies():
    return render_template(
        "cookies.html",
        page_title="Cookie policy – EtnaMonitor",
        page_description="Informazioni sui cookie utilizzati da EtnaMonitor e su come gestirli.",
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
