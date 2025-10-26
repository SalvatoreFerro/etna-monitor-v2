import os
from datetime import datetime

import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, url_for

from ..utils.auth import get_current_user

from app.models import db
from app.models.user import User
from sqlalchemy import or_

from ..utils.metrics import get_csv_metrics, record_csv_error, record_csv_read

bp = Blueprint("main", __name__)

@bp.route("/")
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

@bp.route("/pricing")
def pricing():
    return render_template(
        "pricing.html",
        page_title="Prezzi e piani – EtnaMonitor",
        page_description="Scopri i piani Free e Premium di EtnaMonitor per accedere a grafici avanzati e avvisi sul tremore dell'Etna.",
    )


@bp.route("/etna-3d")
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

    current_app.logger.info("[HEALTH] ok=%s premium_users=%s", payload["ok"], premium_count)
    return jsonify(payload), 200
