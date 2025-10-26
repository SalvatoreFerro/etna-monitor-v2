from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..utils.auth import login_required, get_current_user
from ..utils.logger import get_logger
from ..models import db
from ..models.event import Event
from ..utils.plot import make_tremor_figure
from ..utils.metrics import record_csv_error, record_csv_read
from config import Config
import pandas as pd
import plotly
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

logger = get_logger(__name__)

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def dashboard_home():
    user = get_current_user()
    
    DATA_DIR = os.getenv("DATA_DIR", "data")
    
    try:
        curva_file = os.path.join(DATA_DIR, "curva.csv")
        if os.path.exists(curva_file):
            df = pd.read_csv(curva_file, parse_dates=['timestamp'])
            df = df.tail(100)  # Last 100 points for performance
            record_csv_read(len(df), df['timestamp'].max() if not df.empty else None)
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

@bp.route("/settings")
@login_required
def settings():
    user = get_current_user()

    return render_template("dashboard_settings.html", user=user, default_threshold=Config.ALERT_THRESHOLD_DEFAULT)

@bp.route("/telegram/connect", methods=["POST"])
@login_required
def connect_telegram():
    user = get_current_user()
    
    chat_id = request.form.get("chat_id", "").strip()
    if not chat_id:
        flash("Please provide your Telegram chat ID", "error")
        return redirect(url_for('dashboard.dashboard_home'))

    try:
        int(chat_id)
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

        if user.has_premium_access:
            flash("Telegram collegato. Riceverai gli alert Premium.", "success")
        elif not user.free_alert_consumed:
            flash("Telegram collegato. Riceverai un alert gratuito di prova alla prima occasione utile.", "info")
        else:
            flash("Telegram collegato. Attiva Premium per ricevere nuovi alert.", "warning")
    except ValueError:
        flash("Invalid chat ID format", "error")
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
