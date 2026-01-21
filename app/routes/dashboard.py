from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from ..utils.auth import login_required, get_current_user
from ..utils.logger import get_logger
from ..utils.config import get_curva_csv_path
from ..utils.csrf import validate_csrf_token
from ..models import db, TelegramLinkToken
from ..models.event import Event
from ..utils.plot import make_tremor_figure
from ..utils.metrics import record_csv_error, record_csv_read
from config import Config
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import secrets

logger = get_logger(__name__)

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def dashboard_home():
    import pandas as pd
    import plotly

    user = get_current_user()
    
    try:
        curva_path = get_curva_csv_path()
        if curva_path.exists():
            df = pd.read_csv(curva_path)
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
            curva_path.parent.mkdir(parents=True, exist_ok=True)
            empty_df = pd.DataFrame(columns=['timestamp', 'value'])
            empty_df.to_csv(curva_path, index=False)
            df = empty_df
        
        debug_alerts_enabled = os.getenv("ETNAMONITOR_DEBUG_ALERTS") == "1"
        if user.has_premium_access:
            if user.threshold:
                threshold = user.threshold
                threshold_source = "user/custom"
            else:
                threshold = Config.PREMIUM_DEFAULT_THRESHOLD
                threshold_source = "default"
        else:
            threshold = Config.ALERT_THRESHOLD_DEFAULT
            threshold_source = "default"

        if not df.empty and 'value' in df.columns:
            raw_series = df['value']
        elif not df.empty and df.shape[1] > 1:
            raw_series = df.iloc[:, 1]
        else:
            raw_series = df['timestamp'] * 0 if 'timestamp' in df.columns else df.index.to_series() * 0
        smooth_source = df['value_avg'] if 'value_avg' in df.columns else raw_series
        smooth_series = smooth_source.rolling(window=9, min_periods=1, center=True).median()
        fig = make_tremor_figure(df['timestamp'], raw_series, threshold, smooth_series)
        if debug_alerts_enabled:
            logger.debug(
                "plot_threshold=%.2f source=%s user_id=%s",
                float(threshold),
                threshold_source,
                user.id,
            )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='#e6e7ea',
            height=400
        )
        graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
        latest_value = raw_series.iloc[-1] if not df.empty else 0
        status = 'above' if latest_value > threshold else 'below'
        if debug_alerts_enabled:
            logger.debug(
                "badge_threshold=%.2f source=%s current=%.2f user_id=%s",
                float(threshold),
                threshold_source,
                float(latest_value),
                user.id,
            )
        
    except Exception as e:
        graph_json = None
        latest_value = 0
        status = 'unknown'
        debug_alerts_enabled = os.getenv("ETNAMONITOR_DEBUG_ALERTS") == "1"
        threshold = Config.ALERT_THRESHOLD_DEFAULT
        threshold_source = "default"
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
                         active_threshold=threshold,
                         threshold_source=threshold_source,
                         debug_alerts_enabled=debug_alerts_enabled,
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
                flash("ID chat non valido: usa solo numeri.", "error")
                return redirect(url_for('dashboard.dashboard_home'))

    if chat_id is not None and chat_id <= 0:
        logger.warning("Invalid chat ID value submitted: %s", chat_id)
        flash("ID chat non valido: inserisci un numero positivo.", "error")
        return redirect(url_for('dashboard.dashboard_home'))

    if chat_id is None:
        flash("Inserisci il tuo ID chat Telegram.", "error")
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


@bp.route("/telegram/link", methods=["POST"])
@login_required
def generate_telegram_link():
    user = get_current_user()

    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta, riprova.", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    if user.telegram_chat_id or user.chat_id:
        flash("Telegram è già attivo sul tuo profilo.", "info")
        return redirect(url_for("dashboard.dashboard_home"))

    bot_username = (current_app.config.get("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    if not bot_username:
        flash("Bot Telegram non configurato. Riprova più tardi.", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=15)
    token_value = secrets.token_urlsafe(32)

    try:
        TelegramLinkToken.query.filter(
            TelegramLinkToken.user_id == user.id,
            TelegramLinkToken.used_at.is_(None),
            TelegramLinkToken.expires_at > now,
        ).update({"used_at": now}, synchronize_session=False)

        token = TelegramLinkToken(
            user_id=user.id,
            token=token_value,
            expires_at=expires_at,
        )
        db.session.add(token)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to generate Telegram link token for user %s", user.id)
        flash("Errore durante la generazione del link Telegram.", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    deep_link = f"https://t.me/{bot_username}?start=LINK_{token_value}"
    return redirect(deep_link)

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
