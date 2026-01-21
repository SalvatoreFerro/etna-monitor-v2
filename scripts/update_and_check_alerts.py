import logging
import os
import sys

from app import create_app
from app.services.telegram_service import TelegramService
from scripts.csv_updater import update_with_retries
from app.utils.config import get_curva_csv_path


log = logging.getLogger("update_and_check_alerts")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ingv_url = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    colored_url = (os.getenv("INGV_COLORED_URL") or "").strip() or None
    csv_path = get_curva_csv_path()

    result = update_with_retries(ingv_url, colored_url, csv_path)
    if not result.get("ok"):
        sys.exit(1)

    if not result.get("updated"):
        log.info("No new CSV data detected; skipping alert check")
        return

    app = create_app()
    with app.app_context():
        TelegramService().check_and_send_alerts()


if __name__ == "__main__":
    main()
