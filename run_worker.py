"""Headless entry — runs only the scraper/notifier scheduler, no Flask UI.

Intended to be launched at logon by Windows Task Scheduler via pythonw.exe so
it lives in the background with no console window.
"""
import logging
import signal
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from huizenzoeker.config import settings
from huizenzoeker.db import init_db
from huizenzoeker.scheduler import init_scheduler


def _configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "worker.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> None:
    _configure_logging()
    logging.getLogger(__name__).info("Worker starting")

    init_db(settings.database_url)
    init_scheduler(app=None)  # type: ignore[arg-type]  # app param is unused

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()


if __name__ == "__main__":
    main()
