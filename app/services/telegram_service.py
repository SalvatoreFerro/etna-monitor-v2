import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from numbers import Integral
from typing import Optional

import pandas as pd
from flask import current_app, has_app_context
from sqlalchemy import and_, func, or_

from app.models import db
from app.models.event import Event
from app.models.user import User
from app.utils.logger import get_logger
from app.utils.metrics import record_csv_error, record_csv_read
from alerts.notifier import send_telegram_alert
from config import Config

logger = get_logger(__name__)


class TelegramService:
    """Handle tremor alerts for Telegram subscribers."""

    RATE_LIMIT = timedelta(hours=2)
    UPSELL_COOLDOWN = timedelta(hours=24)

    def _alerts_debug_enabled(self) -> bool:
        return os.getenv("ETNAMONITOR_DEBUG_ALERTS") == "1"

    def _log_alert_decision(
        self,
        user: User,
        chat_id_present: bool,
        threshold: float,
        current_value: float,
        moving_avg: float,
        window_size: Optional[int],
        state_prev: str,
        state_new: str,
        sent: bool,
        reason: str,
    ) -> None:
        if not self._alerts_debug_enabled():
            return
        logger.debug(
            "alert_debug user_id=%s email=%s is_premium=%s chat_id_present=%s "
            "threshold=%.2f current=%.2f avg=%.2f window=%s state_prev=%s state_new=%s "
            "sent=%s reason=%s",
            user.id,
            user.email,
            user.has_premium_access,
            chat_id_present,
            float(threshold),
            float(current_value),
            float(moving_avg),
            window_size if window_size is not None else "n/a",
            state_prev,
            state_new,
            sent,
            reason,
        )

    def send_message(self, chat_id: int | str | None, text: str) -> bool:
        """Send Telegram message to user"""
        token = self._resolve_bot_token()
        normalized_chat_id = self._normalize_chat_id(chat_id)

        if not token or not normalized_chat_id:
            logger.warning("Missing bot token or chat_id")
            return False

        try:
            if send_telegram_alert(token, normalized_chat_id, text):
                logger.info("Telegram message sent to %s", normalized_chat_id)
                return True
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Unexpected error while sending Telegram message")
            return False

        logger.error("Failed to send Telegram message to %s", normalized_chat_id)
        return False

    def _resolve_bot_token(self) -> str:
        token: str = ""
        if has_app_context():
            token = (current_app.config.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
        return token

    def is_configured(self) -> bool:
        return bool(self._resolve_bot_token())

    def _normalize_chat_id(self, chat_id: int | str | None) -> Optional[str]:
        if chat_id is None or isinstance(chat_id, bool):
            return None

        value: Optional[int] = None

        if isinstance(chat_id, Integral):
            candidate = int(chat_id)
            value = candidate if candidate != 0 else None
        elif isinstance(chat_id, Decimal):
            if chat_id == 0:
                return None
            try:
                integral = chat_id.to_integral_value()
            except Exception:  # pragma: no cover - Decimal edge cases
                logger.warning("Invalid chat_id format received: %s", chat_id)
                return None
            if integral != chat_id:
                logger.warning("Invalid chat_id format received: %s", chat_id)
                return None
            value = int(integral)
        else:
            raw = str(chat_id).strip()
            if not raw:
                return None
            if raw.startswith("+"):
                raw = raw[1:]
            if raw.startswith("@"):
                return raw  # Allow usernames/channels for manual tests
            try:
                value = int(raw)
            except ValueError:
                try:
                    decimal_value = Decimal(raw)
                except (InvalidOperation, ValueError):
                    logger.warning("Invalid chat_id format received: %s", chat_id)
                    return None
                if decimal_value != decimal_value.to_integral_value():
                    logger.warning("Invalid chat_id format received: %s", chat_id)
                    return None
                value = int(decimal_value)

        if value is None or value == 0:
            return None

        return str(value)
    
    def calculate_moving_average(self, values, window_size=5):
        """Calculate moving average to avoid false positives"""
        if len(values) < window_size:
            return sum(values) / len(values) if values else 0
        return sum(values[-window_size:]) / window_size
    
    def check_and_send_alerts(self, raise_on_error: bool = False):
        """Evaluate tremor data and deliver alerts based on the user's plan."""

        try:
            dataset = self._load_dataset()
            if dataset is None:
                return {"sent": 0, "skipped": 0, "reason": "no_data"}

            recent_data = dataset.tail(10)
            current_value = recent_data['value'].iloc[-1]
            window_size = 5
            moving_avg = self.calculate_moving_average(recent_data['value'].tolist(), window_size=window_size)

            timestamp = recent_data['timestamp'].iloc[-1]
            event_ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
            event_id = self._compute_event_id(event_ts, moving_avg)
            now = datetime.utcnow()

            result = self._dispatch_alerts(
                event_id,
                current_value,
                moving_avg,
                now,
                window_size=window_size,
            )
            db.session.commit()
            return result
        except Exception as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            record_csv_error(str(exc))
            logger.exception("Error in alert checking")
            if raise_on_error:
                raise
            return {"sent": 0, "skipped": 0, "reason": "error"}

    # --- Internal helpers -------------------------------------------------

    def _load_dataset(self) -> Optional[pd.DataFrame]:
        data_dir = os.getenv("DATA_DIR", "data")
        curva_file = os.path.join(data_dir, "curva.csv")

        if not os.path.exists(curva_file):
            logger.warning("No tremor data available for alert checking")
            record_csv_error("curva.csv not found")
            return None

        df = pd.read_csv(curva_file)
        if 'timestamp' not in df.columns:
            logger.warning("Tremor CSV missing timestamp column")
            record_csv_error("curva.csv missing timestamp column")
            return None

        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
        df = df.dropna(subset=['timestamp'])

        if df.empty:
            logger.warning("Empty tremor data file")
            record_csv_error("curva.csv is empty")
            return None

        last_ts = df['timestamp'].iloc[-1].to_pydatetime()
        record_csv_read(len(df), last_ts)

        return df

    def _compute_event_id(self, timestamp: datetime, moving_avg: float) -> str:
        window_start = timestamp.replace(second=0, microsecond=0)
        window_minute = (window_start.minute // 5) * 5
        window_start = window_start.replace(minute=window_minute)
        return f"{window_start.isoformat()}_{moving_avg:.3f}"

    def send_alert(self, event_id: str, value_mv: float, ts: datetime) -> None:
        """Dispatch a pre-computed alert using the freemium rules."""

        now = datetime.utcnow()
        try:
            ts_label = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            logger.info("Manual alert dispatch triggered event_id=%s at %s", event_id, ts_label)
            self._dispatch_alerts(event_id, value_mv, value_mv, now, window_size=None)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            logger.exception("Error delivering manual alert: event_id=%s", event_id)
            raise

    def _get_subscribed_users(self):
        return (
            User.query.filter(
                User.telegram_opt_in.is_(True),
                or_(
                    User.telegram_chat_id.isnot(None),
                    User.chat_id.isnot(None),
                ),
            )
            .order_by(User.id.asc())
            .all()
        )

    def _dispatch_alerts(
        self,
        event_id: str,
        current_value: float,
        moving_avg: float,
        now: datetime,
        window_size: Optional[int],
    ) -> dict:
        users = self._get_subscribed_users()
        if not users:
            logger.debug("No Telegram subscribers eligible for alerts")
            return {"sent": 0, "skipped": 0, "reason": "no_subscribers"}

        sent = 0
        skipped = 0

        for user in users:
            threshold = self._resolve_threshold(user)
            last_alert = self._get_last_alert_event(user)
            self._register_hysteresis_release(user, threshold, moving_avg, now, last_alert)

            state_prev = "above" if last_alert and last_alert.value is not None and last_alert.value >= threshold else "below"
            state_new = "above" if moving_avg >= threshold else "below"

            if moving_avg < threshold:
                self._log_alert_decision(
                    user,
                    bool(user.telegram_chat_id or user.chat_id),
                    threshold,
                    current_value,
                    moving_avg,
                    window_size,
                    state_prev,
                    state_new,
                    False,
                    "below_threshold",
                )
                skipped += 1
                continue

            chat_id = user.telegram_chat_id or user.chat_id
            if not chat_id:
                self._log_alert_decision(
                    user,
                    False,
                    threshold,
                    current_value,
                    moving_avg,
                    window_size,
                    state_prev,
                    state_new,
                    False,
                    "no_chat_id",
                )
                skipped += 1
                continue

            if user.has_premium_access:
                sent_alert = self._process_premium_user(
                    user,
                    event_id,
                    current_value,
                    moving_avg,
                    threshold,
                    now,
                    last_alert,
                    chat_id,
                    window_size,
                    state_prev,
                    state_new,
                )
            else:
                sent_alert = self._process_free_user(
                    user,
                    event_id,
                    current_value,
                    moving_avg,
                    threshold,
                    now,
                    chat_id,
                    window_size,
                    state_prev,
                    state_new,
                )
            if sent_alert:
                sent += 1
            else:
                skipped += 1

        return {"sent": sent, "skipped": skipped, "reason": "completed"}

    def _resolve_threshold(self, user: User) -> float:
        if user.has_premium_access:
            return user.threshold or Config.PREMIUM_DEFAULT_THRESHOLD
        return Config.ALERT_THRESHOLD_DEFAULT

    def _get_last_alert_event(self, user: User) -> Optional[Event]:
        return (
            Event.query.filter_by(user_id=user.id, event_type='alert')
            .order_by(Event.timestamp.desc())
            .first()
        )

    def _register_hysteresis_release(
        self,
        user: User,
        threshold: float,
        moving_avg: float,
        now: datetime,
        last_alert: Optional[Event],
    ) -> None:
        if not last_alert:
            return

        lower_bound = threshold - Config.ALERT_HYSTERESIS_DELTA
        if moving_avg > lower_bound:
            return

        reset_exists = (
            Event.query.filter(
                Event.user_id == user.id,
                Event.event_type == 'hysteresis_reset',
                Event.timestamp > last_alert.timestamp,
            )
            .order_by(Event.timestamp.desc())
            .first()
        )

        if reset_exists:
            return

        db.session.add(
            Event(
                user_id=user.id,
                event_type='hysteresis_reset',
                value=moving_avg,
                threshold=threshold,
                message='Moving average returned below hysteresis threshold',
            )
        )
        logger.info("Hysteresis reset recorded for %s", user.email)

    def _process_premium_user(
        self,
        user: User,
        event_id: str,
        current_value: float,
        moving_avg: float,
        threshold: float,
        now: datetime,
        last_alert: Optional[Event],
        chat_id: Optional[int],
        window_size: Optional[int],
        state_prev: str,
        state_new: str,
    ) -> bool:
        if self._is_rate_limited(user, now):
            logger.debug("Rate limit active for %s", user.email)
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                current_value,
                moving_avg,
                window_size,
                state_prev,
                state_new,
                False,
                "cooldown",
            )
            return False

        if not self._passed_hysteresis(user, threshold, moving_avg, last_alert):
            logger.debug("Hysteresis gate blocked alert for %s", user.email)
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                current_value,
                moving_avg,
                window_size,
                state_prev,
                state_new,
                False,
                "no_state_change",
            )
            return False

        message = self._build_premium_message(current_value, moving_avg, threshold)
        if self.send_message(chat_id, message):
            user.last_alert_sent_at = now
            alert_event = Event(
                user_id=user.id,
                event_type='alert',
                value=moving_avg,
                threshold=threshold,
                message=f'Telegram alert sent (event_id={event_id})',
            )
            db.session.add(alert_event)
            self._update_alert_counters(user, now)
            logger.info("Premium alert delivered to %s", user.email)
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                current_value,
                moving_avg,
                window_size,
                state_prev,
                state_new,
                True,
                "sent",
            )
            return True
        else:
            logger.error("Failed to deliver premium alert to %s", user.email)
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                current_value,
                moving_avg,
                window_size,
                state_prev,
                state_new,
                False,
                "send_failed",
            )
            return False

    def _process_free_user(
        self,
        user: User,
        event_id: str,
        current_value: float,
        moving_avg: float,
        threshold: float,
        now: datetime,
        chat_id: Optional[int],
        window_size: Optional[int],
        state_prev: str,
        state_new: str,
    ) -> bool:
        if (user.free_alert_consumed or 0) == 0 and user.free_alert_event_id != event_id:
            message = self._build_free_trial_message(current_value, moving_avg, threshold)
            if self.send_message(chat_id, message):
                user.free_alert_consumed = (user.free_alert_consumed or 0) + 1
                user.free_alert_event_id = event_id
                user.last_alert_sent_at = now
                alert_event = Event(
                    user_id=user.id,
                    event_type='alert',
                    value=moving_avg,
                    threshold=threshold,
                    message=f'Free trial alert sent (event_id={event_id})',
                )
                db.session.add(alert_event)
                db.session.add(
                    Event(
                        user_id=user.id,
                        event_type='free_trial_consumed',
                        value=moving_avg,
                        threshold=threshold,
                        message='Free Telegram alert consumed',
                    )
                )
                self._update_alert_counters(user, now)
                logger.info("Free trial alert delivered to %s", user.email)
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    threshold,
                    current_value,
                    moving_avg,
                    window_size,
                    state_prev,
                    state_new,
                    True,
                    "sent_free_trial",
                )
                return True
            else:
                logger.error("Failed to deliver free trial alert to %s", user.email)
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    threshold,
                    current_value,
                    moving_avg,
                    window_size,
                    state_prev,
                    state_new,
                    False,
                    "send_failed",
                )
                return False

        self._log_alert_decision(
            user,
            bool(chat_id),
            threshold,
            current_value,
            moving_avg,
            window_size,
            state_prev,
            state_new,
            False,
            "free_alert_consumed",
        )
        self._send_upsell(user, now, chat_id)
        return False

    def _send_upsell(self, user: User, now: datetime, chat_id: Optional[int]) -> None:
        last_upsell = (
            Event.query.filter_by(user_id=user.id, event_type='upsell')
            .order_by(Event.timestamp.desc())
            .first()
        )
        if last_upsell and now - last_upsell.timestamp < self.UPSELL_COOLDOWN:
            logger.debug("Upsell cooldown active for %s", user.email)
            return

        message = self._build_upsell_message()
        if self.send_message(chat_id, message):
            db.session.add(
                Event(
                    user_id=user.id,
                    event_type='upsell',
                    message='Upsell message sent to promote Premium plan',
                )
            )
            logger.info("Upsell message sent to %s", user.email)
        else:
            logger.error("Failed to send upsell message to %s", user.email)

    def _is_rate_limited(self, user: User, now: datetime) -> bool:
        if not user.last_alert_sent_at:
            return False
        return now - user.last_alert_sent_at < self.RATE_LIMIT

    def _passed_hysteresis(
        self,
        user: User,
        threshold: float,
        moving_avg: float,
        last_alert: Optional[Event],
    ) -> bool:
        if not last_alert:
            return True

        lower_bound = threshold - Config.ALERT_HYSTERESIS_DELTA
        if moving_avg <= lower_bound:
            return True

        reset_exists = (
            Event.query.filter(
                Event.user_id == user.id,
                Event.event_type == 'hysteresis_reset',
                Event.timestamp > last_alert.timestamp,
            )
            .order_by(Event.timestamp.desc())
            .first()
        )
        return bool(reset_exists)

    def _update_alert_counters(self, user: User, now: datetime) -> None:
        window_start = now - timedelta(days=30)
        count = (
            Event.query.filter(
                Event.user_id == user.id,
                Event.event_type == 'alert',
                Event.timestamp >= window_start,
            )
            .with_entities(func.count())
            .scalar()
        )
        user.alert_count_30d = int(count or 0)

    def _build_premium_message(self, current_value: float, moving_avg: float, threshold: float) -> str:
        return (
            "\n".join(
                [
                    "🌋 ALLERTA ETNA",
                    "",
                    "Tremore vulcanico oltre la soglia personalizzata.",
                    f"Valore attuale: {current_value:.2f} mV",
                    f"Media mobile (ultimi 5 campioni): {moving_avg:.2f} mV",
                    f"Soglia: {threshold:.2f} mV",
                ]
            )
        )

    def _build_free_trial_message(self, current_value: float, moving_avg: float, threshold: float) -> str:
        donation_link = Config.PAYPAL_DONATION_LINK or 'https://paypal.me/'
        return (
            "\n".join(
                [
                    "🌋 ETNA – ALERT DI PROVA",
                    "",
                    "Questo è il tuo unico alert gratuito.",
                    f"Valore attuale: {current_value:.2f} mV",
                    f"Media mobile (ultimi 5 campioni): {moving_avg:.2f} mV",
                    f"Soglia di riferimento: {threshold:.2f} mV",
                    "",
                    f"Sostieni il progetto e attiva Premium: {donation_link}",
                ]
            )
        )

    def _build_upsell_message(self) -> str:
        donation_link = Config.PAYPAL_DONATION_LINK or 'https://paypal.me/'
        return (
            "\n".join(
                [
                    "🔔 Alert Premium disponibili",
                    "",
                    "Attiva il piano Premium per ricevere notifiche illimitate e personalizzare la soglia.",
                    f"Supportaci con una donazione: {donation_link}",
                ]
            )
        )
