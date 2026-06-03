from .base import BaseScraper, Listing
from .directwonen import Directwonen
from .krabben import Krabben
from .funda import Funda
from .rncwonen import RncWonen
from .easyleasewonen import EasyLeaseWonen
from .gapph import Gapph
from .deleygraaf import DeLeygraaf


# Keyed by SCRAPER_KEY — the stable id stored in CityScraper.scraper_key,
# ScrapeRun.source, and House.source.
SCRAPERS: dict[str, type[BaseScraper]] = {
    cls.SCRAPER_KEY: cls
    for cls in (
        Directwonen,
        Krabben,
        Funda,
        RncWonen,
        EasyLeaseWonen,
        Gapph,
        DeLeygraaf,
    )
}


def effective_supported_types(session) -> dict[str, set[str]]:
    """Per-scraper supported listing types: the admin-editable ScraperConfig
    rows override the class-level SUPPORTED_TYPES defaults. Scrapers without a
    config row fall back to their class default."""
    from sqlalchemy import select
    from ..models import ScraperConfig

    overrides = {
        sc.scraper_key: sc for sc in session.scalars(select(ScraperConfig)).all()
    }
    result: dict[str, set[str]] = {}
    for key, cls in SCRAPERS.items():
        sc = overrides.get(key)
        if sc is None:
            result[key] = set(cls.SUPPORTED_TYPES)
            continue
        types: set[str] = set()
        if sc.supports_rent:
            types.add("rent")
        if sc.supports_buy:
            types.add("buy")
        result[key] = types
    return result


__all__ = ["BaseScraper", "Listing", "SCRAPERS", "effective_supported_types"]
