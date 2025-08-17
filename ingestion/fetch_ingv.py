from pathlib import Path
import requests
from app.utils.logger import get_logger
from config import Config

logger = get_logger(__name__)

def download_latest_png(dest: Path) -> Path:
    url = Config.INGV_URL
    if not url:
        raise RuntimeError("INGV_URL non configurato")
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    logger.info("Scaricato PNG INGV in %s", dest)
    return dest
