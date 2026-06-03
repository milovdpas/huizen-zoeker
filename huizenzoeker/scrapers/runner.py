"""Run scrapers per (city, listing_type) job and notify each recipient
about only their matching new listings.

Coverage = union of recipient preferences ∩ enabled CityScraper rows. The job
list is snapshotted once per cycle so a mid-cycle toggle can't corrupt the
in-flight run. Dedup is by source_url (primary) and address (cross-site
fallback, scoped by listing_type).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from ..db import session_scope
from ..models import (
    City,
    CityScraper,
    EmailRecipient,
    House,
    Notification,
    ScrapeRun,
    recipient_cities,
)
from ..normalize import normalize_address
from ..notifier import send_listing_notification
from . import SCRAPERS, effective_supported_types
from .base import Listing


logger = logging.getLogger(__name__)

_DUTCH_POSTCODE_RE = re.compile(r"\d{4}\s*[A-Z]{2}", re.IGNORECASE)


@dataclass(frozen=True)
class Job:
    scraper_key: str
    city_id: int
    city_name: str
    city_slug: str
    listing_type: str
    custom_url: str | None


def _has_house_number(addr: str) -> bool:
    """A specific street address — only then is cross-site address dedup safe.

    Strip Dutch postcodes first so '5345JG Oss' isn't treated as a number.
    """
    if not addr:
        return False
    stripped = _DUTCH_POSTCODE_RE.sub("", addr)
    return bool(re.search(r"\d", stripped))


def _snapshot_jobs(
    session, scraper_key: str | None = None, require_wanted: bool = True
) -> list[Job]:
    """Snapshot the jobs to run: enabled CityScraper rows on enabled cities,
    whose scraper_key is known. When require_wanted, intersect with the set of
    (city, listing_type) at least one recipient wants."""
    stmt = (
        select(CityScraper, City)
        .join(City, City.id == CityScraper.city_id)
        .where(CityScraper.enabled.is_(True), City.enabled.is_(True))
    )
    if scraper_key is not None:
        stmt = stmt.where(CityScraper.scraper_key == scraper_key)

    wanted: set[tuple[int, str]] | None = None
    if require_wanted:
        wanted = _wanted_city_types(session)

    # A type the admin has marked unsupported for a scraper is never run, even
    # if a stale CityScraper row is still enabled.
    supported = effective_supported_types(session)

    jobs: list[Job] = []
    for cs, city in session.execute(stmt).all():
        if cs.scraper_key not in SCRAPERS:
            continue
        if cs.listing_type not in supported.get(cs.scraper_key, set()):
            continue
        if wanted is not None and (city.id, cs.listing_type) not in wanted:
            continue
        jobs.append(
            Job(
                scraper_key=cs.scraper_key,
                city_id=city.id,
                city_name=city.name,
                city_slug=city.slug,
                listing_type=cs.listing_type,
                custom_url=cs.custom_url,
            )
        )
    return jobs


def _wanted_city_types(session) -> set[tuple[int, str]]:
    """The (city_id, listing_type) combos at least one recipient wants."""
    wanted: set[tuple[int, str]] = set()
    for type_name, want_col in (("rent", EmailRecipient.wants_rent), ("buy", EmailRecipient.wants_buy)):
        rows = session.execute(
            select(recipient_cities.c.city_id)
            .join(EmailRecipient, EmailRecipient.id == recipient_cities.c.recipient_id)
            .where(want_col.is_(True))
            .distinct()
        ).all()
        for (city_id,) in rows:
            wanted.add((city_id, type_name))
    return wanted


def run_source(name: str) -> dict:
    """Run all enabled (city, type) jobs for a single scraper_key.

    Used by the 'Opnieuw' retry button and scheduler.trigger_source — runs
    every enabled job for the scraper regardless of recipient demand, so an
    admin can investigate a source's inventory.
    """
    if name not in SCRAPERS:
        raise ValueError(f"Unknown source: {name}")
    with session_scope() as s:
        jobs = _snapshot_jobs(s, scraper_key=name, require_wanted=False)
    if not jobs:
        return {"source": name, "status": "ok", "found": 0, "new": 0, "jobs": 0}

    total_new = total_found = 0
    for job in jobs:
        try:
            new_count, found_count = _run_one(job)
            total_new += new_count
            total_found += found_count
        except Exception:  # noqa: BLE001
            logger.exception("Manual scrape of %s (%s/%s) failed", name, job.city_slug, job.listing_type)
    return {
        "source": name,
        "status": "ok",
        "found": total_found,
        "new": total_new,
        "jobs": len(jobs),
    }


def run_all_scrapers() -> dict:
    """Run one cycle: snapshot wanted∩enabled jobs, run each in isolation."""
    with session_scope() as s:
        jobs = _snapshot_jobs(s, require_wanted=True)

    summary: dict = {"jobs": {}, "total_new": 0}
    logger.info("Scrape cycle: %d job(s) snapshotted", len(jobs))
    for job in jobs:
        label = f"{job.scraper_key}:{job.city_slug}:{job.listing_type}"
        try:
            new_count, found_count = _run_one(job)
            summary["jobs"][label] = {
                "found": found_count,
                "new": new_count,
                "status": "ok",
            }
            summary["total_new"] += new_count
        except Exception as e:  # noqa: BLE001
            logger.exception("Job %s failed", label)
            summary["jobs"][label] = {"status": "failed", "error": str(e)}
    logger.info("Scrape cycle done: %s", summary)
    return summary


def _run_one(job: Job) -> tuple[int, int]:
    """Run a single (scraper, city, type) job. Returns (new_count, found_count)."""
    scraper_cls = SCRAPERS[job.scraper_key]
    scraper = scraper_cls(
        city_name=job.city_name,
        city_slug=job.city_slug,
        listing_type=job.listing_type,
        url_override=job.custom_url,
    )

    with session_scope() as s:
        run = ScrapeRun(
            source=job.scraper_key,
            city=job.city_name,
            listing_type=job.listing_type,
            started_at=datetime.utcnow(),
            status="running",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    found_count = 0
    new_count = 0
    error_msg: str | None = None
    new_house_ids: list[int] = []
    is_warm_up = False

    try:
        if not scraper.START_URL:
            raise RuntimeError(
                f"No URL for {job.scraper_key}/{job.listing_type} in {job.city_slug} "
                "(no template and no custom URL configured)"
            )

        listings = scraper.run()
        found_count = len(listings)

        with session_scope() as s:
            # Warm-up: a (city, listing_type) with no prior houses would treat
            # every current listing as new and flood recipients. Suppress
            # notifications for this combo's first run.
            existing_for_combo = s.scalar(
                select(House.id)
                .where(House.city == job.city_name, House.listing_type == job.listing_type)
                .limit(1)
            )
            is_warm_up = existing_for_combo is None

            for listing in listings:
                house_id = _upsert_house(s, job.scraper_key, job.listing_type, listing)
                if house_id is None:
                    continue
                new_count += 1
                new_house_ids.append(house_id)

        if is_warm_up and new_house_ids:
            logger.info(
                "Warm-up for %s/%s: stored %d listing(s), suppressed notifications",
                job.city_slug,
                job.listing_type,
                len(new_house_ids),
            )
        elif new_house_ids:
            _notify_recipients(job, new_house_ids)

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


def _notify_recipients(job: Job, new_house_ids: list[int]) -> None:
    """Email each recipient who wants this job's city + type the new houses
    that fall within their per-type price cap, once each (notifications log)."""
    want_col = EmailRecipient.wants_rent if job.listing_type == "rent" else EmailRecipient.wants_buy
    cap_col = (
        EmailRecipient.max_rent_cents if job.listing_type == "rent" else EmailRecipient.max_buy_cents
    )

    with session_scope() as s:
        recips = s.execute(
            select(EmailRecipient.id, EmailRecipient.email, cap_col)
            .join(recipient_cities, recipient_cities.c.recipient_id == EmailRecipient.id)
            .where(recipient_cities.c.city_id == job.city_id, want_col.is_(True))
        ).all()
        if not recips:
            return

        for hid in new_house_ids:
            house = s.get(House, hid)
            if house is None:
                continue
            targets: list[tuple[int, str]] = []
            for rid, email, cap in recips:
                # NULL/0 = no cap.
                if cap and house.price_cents and house.price_cents > cap:
                    continue
                already = s.get(Notification, {"house_id": hid, "recipient_id": rid})
                if already is not None:
                    continue
                targets.append((rid, email))

            if not targets:
                continue

            err = send_listing_notification(house, [email for _, email in targets])
            if err is None:
                for rid, _ in targets:
                    # Insert-or-ignore: re-check inside the loop is cheap and
                    # the composite PK guards against double-insert.
                    if s.get(Notification, {"house_id": hid, "recipient_id": rid}) is None:
                        s.add(
                            Notification(
                                house_id=hid, recipient_id=rid, sent_at=datetime.utcnow()
                            )
                        )


def _upsert_house(session, source: str, listing_type: str, listing: Listing) -> int | None:
    """Insert if new (returns id), or update last_seen and return None.

    Dedup order:
      1. source_url match — same listing scraped again (type-agnostic: one URL
         is exactly one listing).
      2. address_normalized match scoped by listing_type, but only when the
         address has a house number. Street-only addresses ('Vossehol, Oss')
         would otherwise collapse distinct listings.
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
            select(House).where(
                House.address_normalized == norm,
                House.listing_type == listing_type,
            )
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
        listing_type=listing_type,
        first_seen=now,
        last_seen=now,
    )
    session.add(house)
    session.flush()
    return house.id
