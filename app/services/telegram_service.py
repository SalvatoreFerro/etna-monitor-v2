import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from numbers import Integral
from typing import Optional

import pandas as pd
from flask import current_app, has_app_context
from sqlalchemy import and_, func, or_

from app.models import db
from app.models.alert_state import AlertState
from app.models.event import Event
from app.models.user import User
from app.utils.logger import get_logger
from app.utils.metrics import record_csv_error, record_csv_read
from alerts.notifier import send_telegram_alert
from config import Config

logger = get_logger(__name__)


class TelegramService:
    """Handle tremor alerts for Telegram subscribers."""

    RATE_LIMIT = timedelta(minutes=Config.ALERT_RATE_LIMIT_MINUTES)
    RENOTIFY_INTERVAL = timedelta(minutes=Config.ALERT_RENOTIFY_MINUTES)
    MOVING_AVG_WINDOW = Config.ALERT_MOVING_AVG_WINDOW
    UPSELL_COOLDOWN = timedelta(hours=24)

    def __init__(self) -> None:
        self._cooldown_skipped_count = 0

    def _alerts_debug_enabled(self) -> bool:
        return os.getenv("ETNAMONITOR_DEBUG_ALERTS") == "1"

    def _log_alert_decision(
        self,
        user: User,
        chat_id_present: bool,
        threshold: float,
        threshold_fallback_used: bool,
        current_value: float,
        peak_value: float,
        moving_avg_real: Optional[float],
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
            "threshold=%.2f threshold_fallback_used=%s current=%.2f peak_value=%.2f "
            "media_mobile_diagnostica=%s window=%s "
            "state_prev=%s state_new=%s sent=%s reason=%s",
            user.id,
            user.email,
            user.has_premium_access,
            chat_id_present,
            float(threshold),
            threshold_fallback_used,
            float(current_value),
            float(peak_value),
            f"{moving_avg_real:.2f}" if moving_avg_real is not None else "n/a",
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

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def calculate_moving_average(self, values, window_size=5):
        """Calculate moving average to avoid false positives"""
        if len(values) < window_size:
            return sum(values) / len(values) if values else 0
        return sum(values[-window_size:]) / window_size

    def _get_alert_state(self) -> AlertState:
        state = AlertState.query.order_by(AlertState.id.asc()).first()
        if not state:
            state = AlertState()
            db.session.add(state)
        return state

    @staticmethod
    def _format_timestamp(value: datetime | None) -> str:
        if not value:
            return "none"
        return value.isoformat()

    def _log_alert_evaluation(
        self,
        user: User,
        threshold: float,
        evaluation_value: float,
        decision: str,
        reason: str,
        *,
        cooldown_remaining: timedelta | None = None,
    ) -> None:
        cooldown_seconds = (
            round(cooldown_remaining.total_seconds())
            if cooldown_remaining
            else None
        )
        logger.info(
            "alert_check user_id=%s email=%s threshold=%.2f evaluation_value=%.2f decision=%s "
            "reason=%s cooldown_remaining_s=%s",
            user.id,
            user.email,
            float(threshold),
            float(evaluation_value),
            decision,
            reason,
            cooldown_seconds,
        )
    
    def check_and_send_alerts(self, raise_on_error: bool = False):
        """Evaluate tremor data and deliver alerts based on the user's plan."""

        try:
            self._cooldown_skipped_count = 0
            if not self.is_configured():
                return {
                    "sent": 0,
                    "skipped": 0,
                    "cooldown_skipped": self._cooldown_skipped_count,
                    "skipped_by_reason": {},
                    "reason": "no_token",
                }

            dataset = self._load_dataset()
            if dataset is None:
                return {
                    "sent": 0,
                    "skipped": 0,
                    "cooldown_skipped": self._cooldown_skipped_count,
                    "skipped_by_reason": {"dataset_invalid": 1},
                    "reason": "dataset_invalid",
                }

            dataset = dataset.sort_values("timestamp").reset_index(drop=True)
            alert_state = self._get_alert_state()
            last_checked_ts = self._utc(alert_state.last_checked_ts)

            if last_checked_ts:
                new_points = dataset[dataset["timestamp"] > last_checked_ts]
            else:
                new_points = dataset

            if new_points.empty:
                logger.info(
                    "alert_check no new points last_checked_ts=%s total_points=%s",
                    self._format_timestamp(last_checked_ts),
                    len(dataset),
                )
                return {
                    "sent": 0,
                    "skipped": 0,
                    "cooldown_skipped": self._cooldown_skipped_count,
                    "skipped_by_reason": {"no_new_points": 1},
                    "reason": "no_new_points",
                }

            peak_value = float(new_points["value"].max())
            latest_row = new_points.iloc[-1]
            current_value = float(latest_row["value"])
            timestamp = latest_row["timestamp"]
            event_ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
            event_ts = self._utc(event_ts)
            event_id = self._compute_event_id(event_ts, peak_value)
            window_size = max(1, int(self.MOVING_AVG_WINDOW))
            diagnostics_window = max(window_size, 10)
            diagnostics_window = min(diagnostics_window, 50)
            diagnostics_values = dataset["value"].tail(diagnostics_window).tolist()
            moving_avg_real = float(
                self.calculate_moving_average(
                    diagnostics_values,
                    window_size=window_size,
                )
            )

            logger.info(
                "alert_check last_checked_ts=%s new_points=%s last_point_ts=%s peak_value=%.3f",
                self._format_timestamp(last_checked_ts),
                len(new_points),
                self._format_timestamp(event_ts),
                peak_value,
            )
            baseline_threshold = float(Config.ALERT_THRESHOLD_DEFAULT)
            baseline_decision = "send" if peak_value >= baseline_threshold else "skip"
            logger.info(
                "alert_check evaluation baseline_threshold=%.2f decision=%s",
                baseline_threshold,
                baseline_decision,
            )
            now = datetime.now(timezone.utc)

            result = self._dispatch_alerts(
                event_id,
                current_value,
                peak_value,
                moving_avg_real,
                now,
                window_size=window_size,
            )
            alert_state.last_checked_ts = event_ts
            alert_state.touch()
            db.session.commit()
            return result
        except Exception as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            record_csv_error(str(exc))
            logger.exception("Error in alert checking")
            if raise_on_error:
                raise
            return {
                "sent": 0,
                "skipped": 0,
                "cooldown_skipped": self._cooldown_skipped_count,
                "skipped_by_reason": {"exception": 1},
                "reason": "error",
            }

    # --- Internal helpers -------------------------------------------------

    def _load_dataset(self) -> Optional[pd.DataFrame]:
        data_dir = os.getenv("DATA_DIR", "data")
        curva_file = os.path.join(data_dir, "curva.csv")

        if not os.path.exists(curva_file):
            logger.warning("No tremor data available for alert checking")
            record_csv_error("curva.csv not found")
            return None

        df = pd.read_csv(curva_file)
        if 'timestamp' not in df.columns or 'value' not in df.columns:
            logger.warning("Tremor CSV missing required columns")
            record_csv_error("curva.csv missing required columns")
            return None

        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
        df = df.dropna(subset=['timestamp'])
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna(subset=['value'])

        if df.empty:
            logger.warning("Empty tremor data file")
            record_csv_error("curva.csv is empty")
            return None

        last_ts = df['timestamp'].iloc[-1].to_pydatetime()
        last_ts = self._utc(last_ts)
        record_csv_read(len(df), last_ts)

        return df

    def _compute_event_id(self, timestamp: datetime, peak_value: float) -> str:
        window_start = timestamp.replace(second=0, microsecond=0)
        window_minute = (window_start.minute // 5) * 5
        window_start = window_start.replace(minute=window_minute)
        return f"{window_start.isoformat()}_{peak_value:.3f}"

    def send_alert(self, event_id: str, value_mv: float, ts: datetime) -> None:
        """Dispatch a pre-computed alert using the freemium rules."""

        now = datetime.now(timezone.utc)
        try:
            ts_label = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            logger.info("Manual alert dispatch triggered event_id=%s at %s", event_id, ts_label)
            self._dispatch_alerts(
                event_id,
                value_mv,
                value_mv,
                None,
                now,
                window_size=None,
                allow_free=True,
            )
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            logger.exception("Error delivering manual alert: event_id=%s", event_id)
            raise

    def _get_candidate_users(self):
        return (
            User.query.filter(
                or_(
                    User.telegram_opt_in.is_(True),
                    User.telegram_chat_id.isnot(None),
                    User.chat_id.isnot(None),
                )
            )
            .order_by(User.id.asc())
            .all()
        )

    def _dispatch_alerts(
        self,
        event_id: str,
        current_value: float,
        peak_value: float,
        moving_avg_real: Optional[float],
        now: datetime,
        window_size: Optional[int],
        *,
        allow_free: bool = False,
    ) -> dict:
        users = self._get_candidate_users()
        if not users:
            logger.debug("No Telegram subscribers eligible for alerts")
            return {
                "sent": 0,
                "skipped": 0,
                "cooldown_skipped": self._cooldown_skipped_count,
                "skipped_by_reason": {},
                "reason": "no_subscribers",
            }

        sent = 0
        skipped = 0
        skipped_by_reason: dict[str, int] = {}
        premium_samples: list[dict] = []

        for user in users:
            if not user.telegram_opt_in:
                self._log_alert_decision(
                    user,
                    bool(user.telegram_chat_id or user.chat_id),
                    0,
                    False,
                    current_value,
                    peak_value,
                    moving_avg_real,
                    window_size,
                    "n/a",
                    "n/a",
                    False,
                    "opt_in_false",
                )
                skipped += 1
                skipped_by_reason["opt_in_false"] = skipped_by_reason.get("opt_in_false", 0) + 1
                continue

            chat_id = self._resolve_effective_chat_id(user, allow_update=True)
            if not chat_id:
                self._log_alert_decision(
                    user,
                    False,
                    0,
                    False,
                    current_value,
                    peak_value,
                    moving_avg_real,
                    window_size,
                    "n/a",
                    "n/a",
                    False,
                    "no_chat_id",
                )
                skipped += 1
                skipped_by_reason["no_chat_id"] = (
                    skipped_by_reason.get("no_chat_id", 0) + 1
                )
                continue

            if not user.has_premium_access and not allow_free:
                threshold, _ = self._resolve_threshold(user)
                self._log_alert_evaluation(
                    user,
                    threshold,
                    peak_value,
                    "skip",
                    "not_premium",
                )
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    0,
                    False,
                    current_value,
                    peak_value,
                    moving_avg_real,
                    window_size,
                    "n/a",
                    "n/a",
                    False,
                    "not_premium",
                )
                skipped += 1
                skipped_by_reason["not_premium"] = (
                    skipped_by_reason.get("not_premium", 0) + 1
                )
                continue

            threshold, threshold_fallback_used = self._resolve_threshold(user)
            last_alert = self._get_last_alert_event(user)
            last_alert_event_ts = self._utc(last_alert.timestamp) if last_alert else None
            last_alert_sent_at = self._utc(user.last_alert_sent_at)
            self._register_hysteresis_release(user, threshold, peak_value, now, last_alert_event_ts)

            state_prev = (
                "above"
                if last_alert and last_alert.value is not None and last_alert.value >= threshold
                else "below"
            )
            state_new = "above" if peak_value >= threshold else "below"

            if peak_value < threshold:
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    threshold,
                    threshold_fallback_used,
                    current_value,
                    peak_value,
                    moving_avg_real,
                    window_size,
                    state_prev,
                    state_new,
                    False,
                    "below_threshold",
                )
                self._log_alert_evaluation(
                    user,
                    threshold,
                    peak_value,
                    "skip",
                    "below_threshold",
                )
                skipped += 1
                skipped_by_reason["below_threshold"] = (
                    skipped_by_reason.get("below_threshold", 0) + 1
                )
                self._record_premium_sample(
                    premium_samples,
                    user,
                    threshold,
                    threshold_fallback_used,
                    peak_value,
                    moving_avg_real,
                    last_alert_sent_at,
                    last_alert_event_ts,
                    self._next_allowed_at_short(last_alert_sent_at),
                    self._next_allowed_at_renotify(last_alert_event_ts),
                    user.has_premium_access,
                    False,
                    "below_threshold",
                )
                continue

            if user.has_premium_access:
                sent_alert, decision_reason = self._process_premium_user(
                    user,
                    event_id,
                    current_value,
                    peak_value,
                    threshold,
                    threshold_fallback_used,
                    now,
                    last_alert_event_ts,
                    last_alert,
                    chat_id,
                    window_size,
                    state_prev,
                    state_new,
                )
            else:
                sent_alert, decision_reason = self._process_free_user(
                    user,
                    event_id,
                    current_value,
                    peak_value,
                    threshold,
                    now,
                    chat_id,
                    window_size,
                    state_prev,
                    state_new,
                )
            if sent_alert:
                sent += 1
                self._record_premium_sample(
                    premium_samples,
                    user,
                    threshold,
                    threshold_fallback_used,
                    peak_value,
                    moving_avg_real,
                    last_alert_sent_at,
                    last_alert_event_ts,
                    self._next_allowed_at_short(last_alert_sent_at),
                    self._next_allowed_at_renotify(last_alert_event_ts),
                    user.has_premium_access,
                    True,
                    decision_reason or "sent",
                )
            else:
                skipped += 1
                if decision_reason is None:
                    decision_reason = "error"
                skipped_by_reason[decision_reason] = skipped_by_reason.get(decision_reason, 0) + 1
                self._record_premium_sample(
                    premium_samples,
                    user,
                    threshold,
                    threshold_fallback_used,
                    peak_value,
                    moving_avg_real,
                    last_alert_sent_at,
                    last_alert_event_ts,
                    self._next_allowed_at_short(last_alert_sent_at),
                    self._next_allowed_at_renotify(last_alert_event_ts),
                    user.has_premium_access,
                    False,
                    decision_reason,
                )

        return {
            "sent": sent,
            "skipped": skipped,
            "cooldown_skipped": self._cooldown_skipped_count,
            "skipped_by_reason": skipped_by_reason,
            "premium_samples": premium_samples,
            "reason": "completed",
        }

    def _resolve_threshold(self, user: User) -> tuple[float, bool]:
        if user.has_premium_access:
            if user.threshold is not None:
                return float(user.threshold), False
            logger.info(
                "threshold_fallback_used=true user_id=%s email=%s",
                user.id,
                user.email,
            )
            return float(Config.ALERT_THRESHOLD_DEFAULT), True
        return float(Config.ALERT_THRESHOLD_DEFAULT), False

    @staticmethod
    def _record_premium_sample(
        samples: list[dict],
        user: User,
        threshold: float,
        threshold_fallback_used: bool,
        peak_value: float,
        moving_avg_real: Optional[float],
        last_alert_sent_at: Optional[datetime],
        last_alert_event_ts: Optional[datetime],
        next_allowed_at_short: Optional[datetime],
        next_allowed_at_renotify: Optional[datetime],
        has_premium_access: bool,
        will_send: bool,
        reason: str,
    ) -> None:
        if len(samples) >= 5:
            return
        samples.append(
            {
                "email": user.email,
                "last_alert_sent_at": last_alert_sent_at.isoformat() if last_alert_sent_at else None,
                "last_alert_event_ts": last_alert_event_ts.isoformat()
                if last_alert_event_ts
                else None,
                "next_allowed_at_short": (
                    next_allowed_at_short.isoformat() if next_allowed_at_short else None
                ),
                "next_allowed_at_renotify": (
                    next_allowed_at_renotify.isoformat() if next_allowed_at_renotify else None
                ),
                "renotify_interval_minutes": int(TelegramService.RENOTIFY_INTERVAL.total_seconds() // 60),
                "rate_limit_minutes": int(TelegramService.RATE_LIMIT.total_seconds() // 60),
                "hysteresis_delta": float(Config.ALERT_HYSTERESIS_DELTA),
                "threshold": float(threshold),
                "threshold_fallback_used": threshold_fallback_used,
                "threshold_source": "fallback_default" if threshold_fallback_used else "user",
                "moving_avg": float(peak_value),
                "peak_value": float(peak_value),
                "moving_avg_real": float(moving_avg_real) if moving_avg_real is not None else None,
                "is_premium": bool(has_premium_access),
                "will_send": will_send,
                "reason": reason,
            }
        )

    def _resolve_effective_chat_id(
        self,
        user: User,
        *,
        allow_update: bool,
    ) -> Optional[int]:
        if user.telegram_chat_id:
            return user.telegram_chat_id
        if user.chat_id:
            if allow_update:
                user.telegram_chat_id = user.chat_id
            return user.chat_id
        return None

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
        peak_value: float,
        now: datetime,
        last_alert_event_ts: Optional[datetime],
    ) -> None:
        if not last_alert_event_ts:
            return

        lower_bound = threshold - Config.ALERT_HYSTERESIS_DELTA
        if peak_value > lower_bound:
            return

        reset_exists = (
            Event.query.filter(
                Event.user_id == user.id,
                Event.event_type == 'hysteresis_reset',
                Event.timestamp > last_alert_event_ts,
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
                value=peak_value,
                threshold=threshold,
                message='Signal returned below hysteresis threshold',
            )
        )
        logger.info("Hysteresis reset recorded for %s", user.email)

    def _process_premium_user(
        self,
        user: User,
        event_id: str,
        current_value: float,
        peak_value: float,
        threshold: float,
        threshold_fallback_used: bool,
        now: datetime,
        last_alert_event_ts: Optional[datetime],
        last_alert: Optional[Event],
        chat_id: Optional[int],
        window_size: Optional[int],
        state_prev: str,
        state_new: str,
    ) -> tuple[bool, Optional[str]]:
        if self._is_rate_limited(user, now):
            logger.debug("Rate limit active for %s", user.email)
            self._cooldown_skipped_count += 1
            cooldown_remaining = self.RATE_LIMIT - (now - self._utc(user.last_alert_sent_at))
            logger.info(
                "alert_check cooldown active user_id=%s email=%s remaining_s=%s",
                user.id,
                user.email,
                round(cooldown_remaining.total_seconds()),
            )
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                threshold_fallback_used,
                current_value,
                peak_value,
                None,
                window_size,
                state_prev,
                state_new,
                False,
                "cooldown",
            )
            self._log_alert_evaluation(
                user,
                threshold,
                peak_value,
                "skip",
                "cooldown",
                cooldown_remaining=cooldown_remaining,
            )
            return False, "cooldown"

        # Hysteresis uses Event timestamps; rate limit uses user.last_alert_sent_at.
        hysteresis_rearmed = self._passed_hysteresis(
            user,
            threshold,
            peak_value,
            last_alert_event_ts,
        )
        renotify_due = (
            last_alert_event_ts is not None
            and now - last_alert_event_ts >= self.RENOTIFY_INTERVAL
        )

        if not hysteresis_rearmed and not renotify_due:
            logger.debug("Hysteresis gate blocked alert for %s", user.email)
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                threshold_fallback_used,
                current_value,
                peak_value,
                None,
                window_size,
                state_prev,
                state_new,
                False,
                "already_sent_hysteresis",
            )
            self._log_alert_evaluation(
                user,
                threshold,
                peak_value,
                "skip",
                "already_sent_hysteresis",
            )
            return False, "already_sent_hysteresis"

        send_reason = (
            "persistent_above_threshold_renotify"
            if renotify_due and not hysteresis_rearmed
            else "sent"
        )
        message = self._build_premium_message(current_value, peak_value, threshold)
        if self.send_message(chat_id, message):
            user.last_alert_sent_at = now
            alert_event = Event(
                user_id=user.id,
                event_type='alert',
                value=peak_value,
                threshold=threshold,
                message=f'Telegram alert sent (event_id={event_id})',
            )
            db.session.add(alert_event)
            self._update_alert_counters(user, now)
            logger.info("Premium alert delivered to %s", user.email)
            self._log_alert_evaluation(
                user,
                threshold,
                peak_value,
                "sent",
                send_reason,
            )
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                threshold_fallback_used,
                current_value,
                peak_value,
                None,
                window_size,
                state_prev,
                state_new,
                True,
                send_reason,
            )
            return True, send_reason
        else:
            logger.error("Failed to deliver premium alert to %s", user.email)
            self._log_alert_evaluation(
                user,
                threshold,
                peak_value,
                "skip",
                "error",
            )
            self._log_alert_decision(
                user,
                bool(chat_id),
                threshold,
                threshold_fallback_used,
                current_value,
                peak_value,
                None,
                window_size,
                state_prev,
                state_new,
                False,
                "error",
            )
            return False, "error"

    def _process_free_user(
        self,
        user: User,
        event_id: str,
        current_value: float,
        peak_value: float,
        threshold: float,
        now: datetime,
        chat_id: Optional[int],
        window_size: Optional[int],
        state_prev: str,
        state_new: str,
    ) -> tuple[bool, Optional[str]]:
        if (user.free_alert_consumed or 0) == 0 and user.free_alert_event_id != event_id:
            message = self._build_free_trial_message(current_value, peak_value, threshold)
            if self.send_message(chat_id, message):
                user.free_alert_consumed = (user.free_alert_consumed or 0) + 1
                user.free_alert_event_id = event_id
                user.last_alert_sent_at = now
                alert_event = Event(
                    user_id=user.id,
                    event_type='alert',
                    value=peak_value,
                    threshold=threshold,
                    message=f'Free trial alert sent (event_id={event_id})',
                )
                db.session.add(alert_event)
                db.session.add(
                    Event(
                        user_id=user.id,
                        event_type='free_trial_consumed',
                        value=peak_value,
                        threshold=threshold,
                        message='Free Telegram alert consumed',
                    )
                )
                self._update_alert_counters(user, now)
                logger.info("Free trial alert delivered to %s", user.email)
                self._log_alert_evaluation(
                    user,
                    threshold,
                    peak_value,
                    "sent",
                    "sent_free_trial",
                )
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    threshold,
                    False,
                    current_value,
                    peak_value,
                    None,
                    window_size,
                    state_prev,
                    state_new,
                    True,
                    "sent_free_trial",
                )
                return True, None
            else:
                logger.error("Failed to deliver free trial alert to %s", user.email)
                self._log_alert_evaluation(
                    user,
                    threshold,
                    peak_value,
                    "skip",
                    "error",
                )
                self._log_alert_decision(
                    user,
                    bool(chat_id),
                    threshold,
                    False,
                    current_value,
                    peak_value,
                    None,
                    window_size,
                    state_prev,
                    state_new,
                    False,
                    "error",
                )
                return False, "error"

        self._log_alert_decision(
            user,
            bool(chat_id),
            threshold,
            False,
            current_value,
            peak_value,
            None,
            window_size,
            state_prev,
            state_new,
            False,
            "not_premium",
        )
        self._log_alert_evaluation(
            user,
            threshold,
            peak_value,
            "skip",
            "not_premium",
        )
        self._send_upsell(user, now, chat_id)
        return False, "not_premium"

    def _send_upsell(self, user: User, now: datetime, chat_id: Optional[int]) -> None:
        last_upsell = (
            Event.query.filter_by(user_id=user.id, event_type='upsell')
            .order_by(Event.timestamp.desc())
            .first()
        )
        last_upsell_ts = self._utc(last_upsell.timestamp) if last_upsell else None
        if last_upsell_ts and now - last_upsell_ts < self.UPSELL_COOLDOWN:
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
        last_alert = self._utc(user.last_alert_sent_at)
        if not last_alert:
            return False
        return now - last_alert < self.RATE_LIMIT

    def _passed_hysteresis(
        self,
        user: User,
        threshold: float,
        peak_value: float,
        last_alert_event_ts: Optional[datetime],
    ) -> bool:
        if not last_alert_event_ts:
            return True

        lower_bound = threshold - Config.ALERT_HYSTERESIS_DELTA
        if peak_value <= lower_bound:
            return True

        return self._has_hysteresis_reset_since(user, last_alert_event_ts)

    def _has_hysteresis_reset_since(
        self,
        user: User,
        last_alert_event_ts: datetime,
    ) -> bool:
        reset_exists = (
            Event.query.filter(
                Event.user_id == user.id,
                Event.event_type == 'hysteresis_reset',
                Event.timestamp > last_alert_event_ts,
            )
            .order_by(Event.timestamp.desc())
            .first()
        )
        return bool(reset_exists)

    def _next_allowed_at_short(self, last_alert_sent_at: Optional[datetime]) -> Optional[datetime]:
        if not last_alert_sent_at:
            return None
        return last_alert_sent_at + self.RATE_LIMIT

    def _next_allowed_at_renotify(
        self, last_alert_event_ts: Optional[datetime]
    ) -> Optional[datetime]:
        if not last_alert_event_ts:
            return None
        return last_alert_event_ts + self.RENOTIFY_INTERVAL

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

    def _build_premium_message(self, current_value: float, peak_value: float, threshold: float) -> str:
        return (
            "\n".join(
                [
                    "🌋 ALLERTA ETNA",
                    "",
                    "Tremore vulcanico oltre la soglia personalizzata.",
                    f"Valore attuale: {current_value:.2f} mV",
                    f"Picco massimo (nuovi campioni): {peak_value:.2f} mV",
                    f"Soglia: {threshold:.2f} mV",
                ]
            )
        )

    def _build_free_trial_message(self, current_value: float, peak_value: float, threshold: float) -> str:
        donation_link = Config.PAYPAL_DONATION_LINK or 'https://paypal.me/'
        return (
            "\n".join(
                [
                    "🌋 ETNA – ALERT DI PROVA",
                    "",
                    "Questo è il tuo unico alert gratuito.",
                    f"Valore attuale: {current_value:.2f} mV",
                    f"Picco massimo (nuovi campioni): {peak_value:.2f} mV",
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

    @staticmethod
    def simulate_premium_alert_flow(
        values: list[float],
        *,
        threshold: float,
        start_time: Optional[datetime] = None,
        sample_minutes: int = 1,
        hysteresis_delta: Optional[float] = None,
        rate_limit_minutes: Optional[int] = None,
        renotify_minutes: Optional[int] = None,
    ) -> list[dict]:
        """Deterministic simulation of premium alert decisions (no DB/network)."""
        start_time = start_time or datetime(2024, 1, 1, tzinfo=timezone.utc)
        hysteresis_delta = (
            Config.ALERT_HYSTERESIS_DELTA if hysteresis_delta is None else hysteresis_delta
        )
        rate_limit = timedelta(
            minutes=Config.ALERT_RATE_LIMIT_MINUTES
            if rate_limit_minutes is None
            else rate_limit_minutes
        )
        renotify_interval = timedelta(
            minutes=Config.ALERT_RENOTIFY_MINUTES
            if renotify_minutes is None
            else renotify_minutes
        )
        last_alert_event_ts: Optional[datetime] = None
        last_hysteresis_reset_at: Optional[datetime] = None
        results: list[dict] = []

        for index, value in enumerate(values):
            now = start_time + timedelta(minutes=sample_minutes * index)
            lower_bound = threshold - hysteresis_delta
            reason = None
            sent = False

            if value <= lower_bound:
                last_hysteresis_reset_at = now

            if value < threshold:
                reason = "below_threshold"
            elif last_alert_event_ts and now - last_alert_event_ts < rate_limit:
                reason = "cooldown"
            else:
                rearmed = (
                    last_alert_event_ts is None
                    or value <= lower_bound
                    or (
                        last_hysteresis_reset_at
                        and last_hysteresis_reset_at > last_alert_event_ts
                    )
                )
                renotify_due = (
                    last_alert_event_ts is not None
                    and now - last_alert_event_ts >= renotify_interval
                )
                if not rearmed and not renotify_due:
                    reason = "already_sent_hysteresis"
                else:
                    sent = True
                    reason = (
                        "persistent_above_threshold_renotify"
                        if renotify_due and not rearmed
                        else "sent"
                    )
                    last_alert_event_ts = now

            results.append(
                {
                    "timestamp": now.isoformat(),
                    "value": float(value),
                    "sent": sent,
                    "reason": reason,
                    "last_alert_event_ts": last_alert_event_ts.isoformat()
                    if last_alert_event_ts
                    else None,
                }
            )

        return results
