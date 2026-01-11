"""Minimal smoke check for the Telegram worker build."""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from telegram.ext import Application

from config import Config, normalize_database_uri


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    raw_uri = Config.SQLALCHEMY_DATABASE_URI
    normalized_uri = normalize_database_uri(raw_uri)
    url = make_url(normalized_uri)
    logging.info("Smoke check database dialect: %s", url.drivername)
    create_engine(url)

    Application.builder().token("smoke-test").build()
    logging.info("Smoke check OK")


if __name__ == "__main__":
    main()
