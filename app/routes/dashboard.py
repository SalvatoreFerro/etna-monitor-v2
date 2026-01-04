from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..utils.auth import login_required, get_current_user
from ..utils.logger import get_logger
from ..utils.csrf import validate_csrf_token
from ..models import db
from ..models.cron_run_log import CronRunLog
from ..models.event import Event
from ..services.telegram_service import TelegramService
from ..utils.plot import make_tremor_figure
from ..utils.metrics import record_csv_error, record_csv_read
from config import Config
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

logger = get_logger(__name__)

bp = Blueprint("dashboard", __name__)


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _build_alert_status(user) -> dict:
    telegram_service = TelegramService()
    dataset = telegram_service._load_dataset()
    now = datetime.now(timezone.utc)
    moving_avg = None
    last_point_value = None
    last_point_ts = None
    reason = None
    will_send = False
    event_id = None

    if dataset is None or dataset.empty:
        reason = "dataset_invalid"
    else:
        recent_data = dataset.tail(10)
        last_point_value = float(recent_data["value"].iloc[-1])
        moving_avg = float(
            telegram_service.calculate_moving_average(recent_data["value"].tolist(), window_size=5)
        )
        timestamp = recent_data["timestamp"].iloc[-1]
        event_ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
        event_ts = telegram_service._utc(event_ts)
        last_point_ts = _serialize_dt(event_ts)
        event_id = telegram_service._compute_event_id(event_ts, moving_avg) if event_ts else None

    threshold_used = telegram_service._resolve_threshold(user)
    effective_chat_id = telegram_service._resolve_effective_chat_id(user, allow_update=False)
    last_alert_sent_at = telegram_service._utc(user.last_alert_sent_at)

    cooldown_seconds_remaining = 0
    if last_alert_sent_at:
        cooldown_remaining = telegram_service.RATE_LIMIT - (now - last_alert_sent_at)
        if cooldown_remaining.total_seconds() > 0:
            cooldown_seconds_remaining = int(cooldown_remaining.total_seconds())

    if reason is None:
        if not user.telegram_opt_in:
            reason = "opt_in_false"
        elif not effective_chat_id:
            reason = "missing_chat_id"
        elif moving_avg is None or moving_avg < threshold_used:
            reason = "below_threshold"
        elif user.has_premium_access:
            if telegram_service._is_rate_limited(user, now):
                reason = "cooldown"
            else:
                last_alert = telegram_service._get_last_alert_event(user)
                if not telegram_service._passed_hysteresis(user, threshold_used, moving_avg, last_alert):
                    reason = "already_sent"
                else:
                    reason = "send"
                    will_send = True
        else:
            if (
                event_id
                and (user.free_alert_consumed or 0) == 0
                and user.free_alert_event_id != event_id
            ):
                reason = "send_free_trial"
                will_send = True
            else:
                reason = "not_premium"

    return {
        "telegram_connected": bool(effective_chat_id) and bool(user.telegram_opt_in),
        "threshold_used": float(threshold_used),
        "moving_avg": moving_avg,
        "last_point_value": last_point_value,
        "last_point_ts": last_point_ts,
        "last_alert_sent_at": _serialize_dt(last_alert_sent_at),
        "cooldown_seconds_remaining": cooldown_seconds_remaining,
        "reason": reason,
        "will_send": will_send,
    }

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

        fig = make_tremor_figure(df['timestamp'], df['value'], threshold)
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
        
        latest_value = df['value'].iloc[-1] if not df.empty else 0
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
        recent_events = (
            Event.query.filter_by(user_id=user.id)
            .order_by(Event.timestamp.desc())
            .limit(10)
            .all()
        )

    last_cron_run = CronRunLog.query.order_by(CronRunLog.created_at.desc()).first()
    recent_cron_runs = (
        CronRunLog.query.order_by(CronRunLog.created_at.desc()).limit(10).all()
    )
    last_alert_event = (
        Event.query.filter_by(user_id=user.id, event_type="alert")
        .order_by(Event.timestamp.desc())
        .first()
    )
    alert_status = _build_alert_status(user)

    return render_template(
        "dashboard.html",
        user=user,
        graph_json=graph_json,
        latest_value=latest_value,
        threshold=threshold,
        active_threshold=threshold,
        threshold_source=threshold_source,
        debug_alerts_enabled=debug_alerts_enabled,
        status=status,
        recent_events=recent_events,
        last_cron_run=last_cron_run,
        recent_cron_runs=recent_cron_runs,
        last_alert_event=last_alert_event,
        alert_status=alert_status,
        page_title="Dashboard tremore Etna – EtnaMonitor",
        page_description="Grafico del tremore vulcanico dell'Etna, soglie personalizzate e storico eventi per utenti Premium.",
    )

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


@bp.route("/telegram/test", methods=["POST"])
@login_required
def test_telegram_alert():
    user = get_current_user()
    csrf_token = request.form.get("csrf_token")
    if not validate_csrf_token(csrf_token):
        flash("Sessione scaduta, riprova.", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    chat_id = user.telegram_chat_id or user.chat_id
    if not chat_id:
        flash("Collega Telegram per inviare un test.", "warning")
        return redirect(url_for("dashboard.dashboard_home"))

    telegram_service = TelegramService()
    if not telegram_service.is_configured():
        flash("Bot Telegram non configurato. Riprova più tardi.", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    try:
        sent = telegram_service.send_message(
            chat_id,
            "🔔 Test alert EtnaMonitor\nQuesto messaggio conferma il collegamento Telegram.",
        )
    except Exception as exc:  # pragma: no cover - external service safeguard
        logger.exception("Telegram test alert failed for user %s", user.id)
        flash(f"Errore durante l'invio del test: {exc}", "error")
        return redirect(url_for("dashboard.dashboard_home"))

    if sent:
        flash("Alert di test inviato su Telegram.", "success")
    else:
        flash("Telegram ha rifiutato il messaggio di test.", "error")
    return redirect(url_for("dashboard.dashboard_home"))

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
