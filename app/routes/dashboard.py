from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..utils.auth import login_required, get_current_user
from ..utils.logger import get_logger
from ..utils.csrf import validate_csrf_token
from ..models import db
from ..models.event import Event
from ..utils.plot import make_tremor_figure
from ..utils.metrics import record_csv_error, record_csv_read
from config import Config
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

logger = get_logger(__name__)

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def dashboard_home():
    import pandas as pd
    import plotly

    user = get_current_user()
    
    DATA_DIR = os.getenv("DATA_DIR", "data")
    
    try:
        curva_file = os.path.join(DATA_DIR, "curva.csv")
        if os.path.exists(curva_file):
            df = pd.read_csv(curva_file)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
                df = df.dropna(subset=['timestamp'])
            else:
                record_csv_error('curva.csv missing timestamp column')
                df = pd.DataFrame(columns=['timestamp', 'value'])

            df = df.tail(100)  # Last 100 points for performance
            last_ts = df['timestamp'].iloc[-1].to_pydatetime() if not df.empty else None
            record_csv_read(len(df), last_ts)
        else:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            empty_df = pd.DataFrame(columns=['timestamp', 'value'])
            empty_df.to_csv(curva_file, index=False)
            df = empty_df
        
        threshold = user.threshold if user.has_premium_access and user.threshold else Config.ALERT_THRESHOLD_DEFAULT
        
        fig = make_tremor_figure(df['timestamp'], df['value'], threshold)
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='#e6e7ea',
            height=400
        )
        graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
        latest_value = df['value'].iloc[-1] if not df.empty else 0
        status = 'above' if latest_value > threshold else 'below'
        
    except Exception as e:
        graph_json = None
        latest_value = 0
        status = 'unknown'
        threshold = Config.ALERT_THRESHOLD_DEFAULT
        record_csv_error(str(e))
        logger.exception("Dashboard data preparation failed")
    
    recent_events = []
    if user.has_premium_access:
        recent_events = Event.query.filter_by(user_id=user.id)\
                                 .order_by(Event.timestamp.desc())\
                                 .limit(10).all()
    
    return render_template("dashboard.html",
                         user=user,
                         graph_json=graph_json,
                         latest_value=latest_value,
                         threshold=threshold,
                         status=status,
                         recent_events=recent_events,
                         page_title="Dashboard tremore Etna – EtnaMonitor",
                         page_description="Grafico del tremore vulcanico dell'Etna, soglie personalizzate e storico eventi per utenti Premium.")

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = get_current_user()

    if request.method == "POST":
        if not user.has_premium_access:
            return jsonify({"status": "error", "message": "Premium account required"}), 403

        raw_threshold = (request.form.get("threshold") or "").strip()
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Invalid threshold value"}), 400

        if not 0.1 <= threshold <= 10:
            return jsonify({"status": "error", "message": "Threshold out of range"}), 400

        try:
            user.threshold = threshold

            event = Event(
                user_id=user.id,
                event_type="threshold_change",
                threshold=threshold,
                message=f"Threshold updated to {threshold:.2f} mV",
            )
            db.session.add(event)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to update threshold for user %s", user.id)
            return jsonify({"status": "error", "message": "Failed to update threshold"}), 500

        return jsonify({"status": "success", "threshold": threshold})

    return render_template("dashboard_settings.html", user=user, default_threshold=Config.ALERT_THRESHOLD_DEFAULT)

@bp.route("/telegram/connect", methods=["POST"])
@login_required
def connect_telegram():
    user = get_current_user()

    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta, riprova.", "error")
        return redirect(url_for('dashboard.dashboard_home'))
    
    raw_chat_id = request.form.get("chat_id")
    chat_id = None
    if raw_chat_id is not None:
        raw_chat_id = str(raw_chat_id).strip()
        if raw_chat_id:
            try:
                chat_id = int(raw_chat_id)
            except ValueError:
                logger.warning("Invalid chat ID format submitted: %s", raw_chat_id)
                flash("Invalid chat ID format", "error")
                return redirect(url_for('dashboard.dashboard_home'))

    if chat_id is None:
        flash("Please provide your Telegram chat ID", "error")
        return redirect(url_for('dashboard.dashboard_home'))

    try:
        user.chat_id = chat_id
        user.telegram_chat_id = chat_id
        user.telegram_opt_in = True
        user.consent_ts = user.consent_ts or datetime.utcnow()
        user.privacy_version = Config.PRIVACY_POLICY_VERSION

        event = Event(
            user_id=user.id,
            event_type='telegram_connected',
            message=f'Telegram connected: {chat_id}'
        )
        db.session.add(event)
        db.session.commit()
        logger.info("[TRACK] telegram_collegato_success")

        if user.has_premium_access:
            flash("Telegram collegato. Riceverai gli alert Premium.", "success")
        elif (user.free_alert_consumed or 0) == 0:
            flash("Telegram collegato. Riceverai un alert gratuito di prova alla prima occasione utile.", "info")
        else:
            flash("Telegram collegato. Attiva Premium per ricevere nuovi alert.", "warning")
    except Exception as e:
        flash("Error connecting Telegram", "error")
        logger.error(f"Telegram connection error: {e}")
    
    return redirect(url_for('dashboard.dashboard_home'))

@bp.route("/telegram/disconnect", methods=["POST"])
@login_required
def disconnect_telegram():
    user = get_current_user()
    
    user.chat_id = None
    user.telegram_chat_id = None
    user.telegram_opt_in = False

    event = Event(
        user_id=user.id,
        event_type='telegram_disconnected',
        message='Telegram disconnected'
    )
    db.session.add(event)
    db.session.commit()
    
    flash("Telegram disconnected", "info")
    return redirect(url_for('dashboard.dashboard_home'))

@bp.route("/alerts/toggle", methods=["POST"])
@login_required
def toggle_alerts():
    user = get_current_user()
    
    if not user.has_premium_access:
        flash("Premium account required", "error")
        return redirect(url_for('dashboard.dashboard_home'))
    
    alert_type = request.form.get("alert_type")
    enabled = request.form.get("enabled") == "true"
    
    if alert_type == "email":
        user.email_alerts = enabled
        db.session.commit()
        flash(f"Email alerts {'enabled' if enabled else 'disabled'}", "success")
    
    return redirect(url_for('dashboard.dashboard_home'))
