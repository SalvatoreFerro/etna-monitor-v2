from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.utils.logger import get_logger
from .telegram_service import TelegramService
from .prediction_service import resolve_expired_predictions
import atexit

logger = get_logger(__name__)

class SchedulerService:
    def __init__(self, app=None):
        self.scheduler = None
        self.telegram_service = TelegramService()
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize scheduler with Flask app"""
        self.scheduler = BackgroundScheduler()
        
        self.scheduler.add_job(
            func=self._check_alerts_with_context,
            trigger=IntervalTrigger(hours=1),
            id='telegram_alerts',
            name='Check tremor levels and send Telegram alerts',
            replace_existing=True
        )
        self.scheduler.add_job(
            func=self._resolve_predictions_with_context,
            trigger=IntervalTrigger(minutes=10),
            id="tremor_predictions",
            name="Resolve tremor prediction game results",
            replace_existing=True,
        )
        
        self.scheduler.start()
        logger.info("Scheduler started - checking alerts every hour")

        def _shutdown():
            if self.scheduler and self.scheduler.running:
                try:
                    self.scheduler.shutdown(wait=False)
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.exception("Scheduler shutdown encountered an error")

        atexit.register(_shutdown)
    
    def _check_alerts_with_context(self):
        """Run alert checking within Flask app context"""
        from flask import current_app
        with current_app.app_context():
            started_at = datetime.now(timezone.utc)
            logger.info(
                "[WORKER] scheduler.job.start",
                extra={"job_id": "telegram_alerts", "started_at": started_at.isoformat()},
            )
            try:
                self.telegram_service.check_and_send_alerts(allow_free=True)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("[WORKER] scheduler.job.error", extra={"job_id": "telegram_alerts"})
            else:
                finished_at = datetime.now(timezone.utc)
                duration = (finished_at - started_at).total_seconds()
                logger.info(
                    "[WORKER] scheduler.job.stop",
                    extra={
                        "job_id": "telegram_alerts",
                        "finished_at": finished_at.isoformat(),
                        "duration_s": duration,
                    },
                )

    def _resolve_predictions_with_context(self):
        from flask import current_app
        with current_app.app_context():
            started_at = datetime.now(timezone.utc)
            logger.info(
                "[WORKER] scheduler.job.start",
                extra={"job_id": "tremor_predictions", "started_at": started_at.isoformat()},
            )
            try:
                resolved = resolve_expired_predictions(now=started_at)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("[WORKER] scheduler.job.error", extra={"job_id": "tremor_predictions"})
            else:
                finished_at = datetime.now(timezone.utc)
                duration = (finished_at - started_at).total_seconds()
                logger.info(
                    "[WORKER] scheduler.job.stop",
                    extra={
                        "job_id": "tremor_predictions",
                        "finished_at": finished_at.isoformat(),
                        "duration_s": duration,
                        "resolved_count": resolved,
                    },
                )
