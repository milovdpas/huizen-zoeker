import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from flask import Flask

from .config import settings


logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None

_REFRESH_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "refresh_funda_cookies.py"
)


def _job() -> None:
    # Lazy import to avoid Playwright startup cost at module load time
    from .scrapers.runner import run_all_scrapers

    logger.info("Scheduled scrape run starting")
    try:
        run_all_scrapers()
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled scrape run crashed")


def _refresh_funda_cookies_job() -> None:
    """Run the cookie refresh script as a subprocess so it can pop a browser
    window without blocking the Flask process or the scheduler thread."""
    if not _REFRESH_SCRIPT.is_file():
        logger.warning("Refresh script not found at %s", _REFRESH_SCRIPT)
        return
    logger.info("Refreshing funda cookies via %s", _REFRESH_SCRIPT.name)
    try:
        result = subprocess.run(
            [sys.executable, str(_REFRESH_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Cookie refresh OK: %s", result.stdout.strip().replace("\n", " | "))
        else:
            logger.warning(
                "Cookie refresh exit=%s stderr=%s",
                result.returncode,
                (result.stderr or "").strip(),
            )
    except subprocess.TimeoutExpired:
        logger.warning("Cookie refresh timed out after 180s")
    except Exception:  # noqa: BLE001
        logger.exception("Cookie refresh failed")


def _shifted_time(hh_mm: str, minutes_earlier: int) -> tuple[int, int]:
    """Return (hour, minute) shifted earlier by the given minutes, wrapping at midnight."""
    h, m = (int(p) for p in hh_mm.split(":"))
    total = (h * 60 + m - minutes_earlier) % (24 * 60)
    return divmod(total, 60)


def init_scheduler(app: Flask) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(daemon=True)

    # All scrape times are combined into a single job via OrTrigger so that
    # coalesce can collapse multiple missed slots (e.g. after the laptop slept
    # through the night) into one catch-up run on wake. misfire_grace_time
    # keeps a delayed run from being silently skipped.
    scrape_triggers: list[CronTrigger] = []
    refresh_triggers: list[CronTrigger] = []
    refresh_label_times: list[str] = []
    for hh_mm in settings.scrape_times:
        hour_str, minute_str = hh_mm.split(":")
        hour, minute = int(hour_str), int(minute_str)
        scrape_triggers.append(CronTrigger(hour=hour, minute=minute))

        if settings.auto_refresh_funda_cookies:
            rh, rm = _shifted_time(hh_mm, settings.funda_cookie_refresh_lead_minutes)
            refresh_triggers.append(CronTrigger(hour=rh, minute=rm))
            refresh_label_times.append(f"{rh:02d}:{rm:02d}")

    if scrape_triggers:
        sched.add_job(
            _job,
            trigger=scrape_triggers[0] if len(scrape_triggers) == 1 else OrTrigger(scrape_triggers),
            id="scrape_daily",
            name=f"Scrape at {','.join(settings.scrape_times)}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    if refresh_triggers:
        sched.add_job(
            _refresh_funda_cookies_job,
            trigger=refresh_triggers[0] if len(refresh_triggers) == 1 else OrTrigger(refresh_triggers),
            id="refresh_funda_cookies_daily",
            name=f"Refresh funda cookies at {','.join(refresh_label_times)}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    if settings.scrape_on_startup:
        sched.add_job(
            _job,
            trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=10)),
            id="scrape_startup",
            name="Scrape on startup",
        )

    sched.start()
    _scheduler = sched
    logger.info(
        "Scheduler started — times=%s, run_on_startup=%s, auto_refresh_cookies=%s (lead=%dm)",
        ",".join(settings.scrape_times),
        settings.scrape_on_startup,
        settings.auto_refresh_funda_cookies,
        settings.funda_cookie_refresh_lead_minutes,
    )
    return sched


def trigger_now() -> None:
    """Fire the scrape job immediately (used by the 'Run now' button)."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    _scheduler.add_job(_job, id=f"scrape_manual_{datetime.now().timestamp()}")


def trigger_refresh_funda_cookies() -> None:
    """Fire the cookie refresh job immediately (used by the manual refresh button)."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    _scheduler.add_job(
        _refresh_funda_cookies_job,
        id=f"refresh_funda_cookies_manual_{datetime.now().timestamp()}",
    )


def trigger_source(source_name: str) -> None:
    """Fire a scrape for a single scraper_key (retry button on the Runs page).

    run_source re-snapshots and expands the scraper_key into all its enabled
    (city, listing_type) jobs at execution time.
    """
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")

    def _one_off() -> None:
        from .scrapers.runner import run_source

        try:
            run_source(source_name)
        except Exception:  # noqa: BLE001
            logger.exception("Manual %s scrape crashed", source_name)

    _scheduler.add_job(
        _one_off, id=f"scrape_source_{source_name}_{datetime.now().timestamp()}"
    )
