#!/usr/bin/env python3
"""
Startup script for Render deployment that ensures database migration runs
"""
import logging
import os
import subprocess

from app.utils.logger import configure_logging

logger = logging.getLogger(__name__)

def run_migration():
    """Run database migration"""
    try:
        logger.info("Running database migrations...")
        env = os.environ.copy()
        env.setdefault("FLASK_APP", "app:create_app")
        result = subprocess.run(
            ["flask", "db", "upgrade"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        if result.returncode == 0:
            logger.info("Database migration completed successfully")
            if result.stdout:
                logger.debug(result.stdout.strip())
        else:
            logger.warning("Database migration exited with code %s", result.returncode)
            if result.stdout:
                logger.warning(result.stdout.strip())
            if result.stderr:
                logger.warning(result.stderr.strip())
    except Exception:
        logger.exception("Migration command failed")
        logger.warning("Continuing with app startup despite migration error")

def main():
    """Main startup function"""
    configure_logging(os.getenv("LOG_DIR", "logs"))
    logger.info("Starting EtnaMonitor deployment...")

    data_dir = os.getenv('DATA_DIR', '/var/tmp')
    log_dir = os.getenv('LOG_DIR', '/var/tmp/log')

    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    logger.info("Data directories ready data_dir=%s log_dir=%s", data_dir, log_dir)

    run_migration()
    
    port = os.environ.get('PORT', '5000')
    workers = os.environ.get('WEB_CONCURRENCY', '2')
    
    cmd = [
        'gunicorn',
        '-w', str(workers),
        '-k', 'gthread',
        '-b', f'0.0.0.0:{port}',
        'app:app'
    ]
    
    logger.info("Starting gunicorn with command: %s", " ".join(cmd))
    os.execvp('gunicorn', cmd)

if __name__ == '__main__':
    main()
