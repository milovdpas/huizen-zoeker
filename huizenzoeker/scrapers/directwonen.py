"""directwonen.nl — Oss & Berghem listing pages.

Markup: each listing is a `div.tile`. Inside:
  - h3.location-text       → street + city (e.g. "Vossehol, Oss") — no house number
  - div.advert-location-price → price (e.g. "€ 1001")
  - span.advert-location-header → unit type (e.g. "Studio")
  - a.inner-content[href]  → detail page

Addresses are anonymized to street level, so dedup by URL — not address.
"""
from .base import BaseScraper


class _DirectwonenBase(BaseScraper):
    SOURCE_NAME = "directwonen"
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "div.tile"
    LISTING_CONTAINER_SELECTOR = "div.tile"
    ADDRESS_SELECTOR = "h3.location-text"
    PRICE_SELECTOR = "div.advert-location-price"
    TITLE_SELECTOR = "span.advert-location-header"


class DirectwonenOss(_DirectwonenBase):
    SOURCE_NAME = "directwonen-oss"
    START_URL = "https://directwonen.nl/huurwoningen-huren/oss"
    CITY_HINT = "Oss"


class DirectwonenBerghem(_DirectwonenBase):
    SOURCE_NAME = "directwonen-berghem"
    START_URL = "https://directwonen.nl/huurwoningen-huren/berghem"
    CITY_HINT = "Berghem"
