import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
DEFAULT_LOG_DIR = Path("logs")
_configured = False
_configured_dir: Path | None = None


def configure_logging(log_dir: Optional[str] = None) -> None:
    """Configure global logging with stream + rotating file handlers."""

    global _configured
    global _configured_dir

    requested_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR

    if _configured and _configured_dir == requested_dir:
        return

    directory = requested_dir
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "app.log"

    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers when running in debug/reload mode
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    _configured = True
    _configured_dir = directory


def get_logger(name: str = "etnamonitor"):
    configure_logging()
    return logging.getLogger(name)
