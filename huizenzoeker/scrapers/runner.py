"""Run all scrapers, dedup by source_url (primary) and address (cross-site fallback)."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import select

from ..db import session_scope
from ..models import EmailRecipient, House, ScrapeRun, Settings
from ..normalize import normalize_address
from ..notifier import send_listing_notification
from . import ALL_SCRAPERS
from .base import BaseScraper, Listing


_DUTCH_POSTCODE_RE = re.compile(r"\d{4}\s*[A-Z]{2}", re.IGNORECASE)

TARGET_CITIES = {"oss", "berghem"}
_TARGET_CITY_RE = re.compile(r"\b(?:oss|berghem)\b", re.IGNORECASE)


def _is_in_target_area(listing: Listing) -> bool:
    """Only Oss and Berghem are kept. Trust the scraper-extracted city when set;
    otherwise fall back to a word-boundary scan of the raw address."""
    if listing.city:
        return listing.city.strip().lower() in TARGET_CITIES
    return bool(_TARGET_CITY_RE.search(listing.address_raw or ""))


def _has_house_number(addr: str) -> bool:
    """A specific street address — only then is cross-site address dedup safe.

    Strip Dutch postcodes first so '5345JG Oss' doesn't get treated as having
    a house number.
    """
    if not addr:
        return False
    stripped = _DUTCH_POSTCODE_RE.sub("", addr)
    return bool(re.search(r"\d", stripped))


logger = logging.getLogger(__name__)


def run_source(name: str) -> dict:
    """Run a single scraper identified by SOURCE_NAME."""
    matches = [c for c in ALL_SCRAPERS if c.SOURCE_NAME == name]
    if not matches:
        raise ValueError(f"Unknown source: {name}")
    cls = matches[0]
    try:
        new_count, found_count = _run_one(cls())
        return {"source": name, "found": found_count, "new": new_count, "status": "ok"}
    except Exception as e:  # noqa: BLE001
        logger.exception("Manual scrape of %s failed", name)
        return {"source": name, "status": "failed", "error": str(e)}


def run_all_scrapers() -> dict:
    """Run every scraper. Each runs in isolation; one failure doesn't stop the rest."""
    summary = {"sources": {}, "total_new": 0}
    for cls in ALL_SCRAPERS:
        try:
            new_count, found_count = _run_one(cls())
            summary["sources"][cls.SOURCE_NAME] = {
                "found": found_count,
                "new": new_count,
                "status": "ok",
            }
            summary["total_new"] += new_count
        except Exception as e:  # noqa: BLE001
            logger.exception("Scraper %s failed", cls.SOURCE_NAME)
            summary["sources"][cls.SOURCE_NAME] = {"status": "failed", "error": str(e)}
    logger.info("Scrape cycle done: %s", summary)
    return summary


def _run_one(scraper: BaseScraper) -> tuple[int, int]:
    """Returns (new_count, found_count)."""
    with session_scope() as s:
        run = ScrapeRun(source=scraper.SOURCE_NAME, started_at=datetime.utcnow(), status="running")
        s.add(run)
        s.flush()
        run_id = run.id

    found_count = 0
    new_count = 0
    error_msg: str | None = None
    new_houses_to_notify: list[int] = []
    recipients: list[str] = []

    try:
        listings = scraper.run()
        found_count = len(listings)

        with session_scope() as s:
            settings_row = s.get(Settings, 1)
            max_price_cents = settings_row.max_price_cents if settings_row else 0
            recipients = [r.email for r in s.scalars(select(EmailRecipient)).all()]

            for listing in listings:
                if not _is_in_target_area(listing):
                    continue
                house_id = _upsert_house(s, scraper.SOURCE_NAME, listing)
                if house_id is None:
                    continue
                new_count += 1
                # Apply max price filter for notification (0 = no max)
                if max_price_cents and listing.price_cents and listing.price_cents > max_price_cents:
                    continue
                new_houses_to_notify.append(house_id)

        # Send notifications outside the session — SMTP can be slow
        if recipients and new_houses_to_notify:
            with session_scope() as s:
                for hid in new_houses_to_notify:
                    house = s.get(House, hid)
                    if not house or house.notified:
                        continue
                    err = send_listing_notification(house, recipients)
                    if err is None:
                        house.notified = True

    except Exception as e:  # noqa: BLE001
        error_msg = str(e)
        raise
    finally:
        with session_scope() as s:
            run = s.get(ScrapeRun, run_id)
            if run is not None:
                run.finished_at = datetime.utcnow()
                run.listings_found = found_count
                run.new_listings = new_count
                run.status = "failed" if error_msg else "ok"
                if error_msg:
                    run.error_message = error_msg[:5000]

    return new_count, found_count


def _upsert_house(session, source: str, listing: Listing) -> int | None:
    """Insert if new (returns id), or update last_seen and return None.

    Dedup order:
      1. source_url match — same listing scraped again, even from a different
         page render. This is the strong signal.
      2. address_normalized match across sources, but only when the address
         contains a digit (i.e. has a house number). Anonymized street-only
         addresses ("Vossehol, Oss") would otherwise collapse distinct listings.
    """
    norm = normalize_address(listing.address_raw)
    if not norm or not listing.source_url:
        return None

    now = datetime.utcnow()

    existing = session.scalars(
        select(House).where(House.source_url == listing.source_url)
    ).first()

    if existing is None and _has_house_number(listing.address_raw):
        existing = session.scalars(
            select(House).where(House.address_normalized == norm)
        ).first()

    if existing:
        existing.last_seen = now
        if existing.price_cents is None and listing.price_cents is not None:
            existing.price_cents = listing.price_cents
        return None

    house = House(
        address_raw=listing.address_raw[:500],
        address_normalized=norm[:500],
        city=listing.city,
        price_cents=listing.price_cents,
        source=source,
        source_url=listing.source_url[:1000],
        raw_title=(listing.raw_title or listing.address_raw)[:500],
        first_seen=now,
        last_seen=now,
        notified=False,
    )
    session.add(house)
    session.flush()
    return house.id
