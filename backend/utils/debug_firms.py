from __future__ import annotations

import json
import logging

from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.diagnostics import diagnose_firms


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("hotspots.debug")

    config = HotspotsConfig.from_env()
    payload = diagnose_firms(config, logger)
    logger.info("[HOTSPOTS] FIRMS diagnostic payload: %s", json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
