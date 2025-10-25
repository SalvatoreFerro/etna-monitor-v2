from flask import Blueprint, render_template, jsonify, url_for
import pandas as pd
import os
import pathlib
from pathlib import Path
from backend.utils.extract_png import process_png_to_csv
from ..utils.decorators import requires_premium

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    csv_path = os.getenv("CSV_PATH", "/var/tmp/curva.csv")
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            if not df.empty:
                timestamps = df["timestamp"].dt.strftime('%Y-%m-%d %H:%M:%S').tolist()
                values = df["value"].tolist()
            else:
                timestamps = []
                values = []
        except Exception as e:
            print(f"Error reading CSV: {e}")
            timestamps = []
            values = []
    else:
        timestamps = []
        values = []
    
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
    return jsonify({"status": "ok"}), 200
