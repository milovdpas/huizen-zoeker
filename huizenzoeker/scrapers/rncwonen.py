"""rncwonen.nl — Drupal site with taxonomy filters in the URL.

Markup: each listing is `div.house`. Inside:
  - span.house-title-street      → street (e.g. "Vossehol") — no house number
  - span.house-title-location    → city  (e.g. "Oss")
  - span.house-details-item      → repeated; the one with '€' has the price
  - a.btn-orange[href]           → relative detail URL

The visible address is street-only, but the URL slug encodes the house
number, e.g. `/semi-studio-te-huur-vossehol-21-oss` → no. 21. We extract
that to enable cross-site address dedup.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


# URL slug pattern: ...-<street-words>-<number>[letter]-<city>[/]
# Captures '21', '12a', '100'. Falls back gracefully when the slug doesn't match.
_HOUSE_NUMBER_FROM_SLUG_RE = re.compile(r"-(\d+[a-z]?)-[a-z]+/?$", re.IGNORECASE)


class RncWonen(BaseScraper):
    SCRAPER_KEY = "rncwonen"
    DISPLAY_NAME = "RNC Wonen"
    SUPPORTED_TYPES = {"rent"}
    # Drupal taxonomy-ID URL can't be templated by city name → custom-URL only.
    # Admin must supply a custom_url per city (the escape hatch). The legacy
    # combined-area URL below is what the 0003 migration seeds for Oss/Berghem.
    URL_TEMPLATES = {}
    LEGACY_START_URL = (
        "https://www.rncwonen.nl/aanbod"
        "?field_location_taxonomy_target_id%5B%5D=718"
        "&field_location_taxonomy_target_id%5B%5D=712"
        "&range=10"
        "&field_house_type_target_id=All"
        "&field_price_deci_value=5"
    )
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "div.house"

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        seen: set[str] = set()

        for card in soup.select("div.house"):
            link = card.find("a", href=True)
            if not link:
                continue
            href = urljoin(self.START_URL, link["href"])
            if href in seen:
                continue
            seen.add(href)

            street_el = card.select_one("span.house-title-street")
            city_el = card.select_one("span.house-title-location")

            street = street_el.get_text(" ", strip=True) if street_el else ""
            city = city_el.get_text(" ", strip=True) if city_el else None

            number_match = _HOUSE_NUMBER_FROM_SLUG_RE.search(href)
            if street and number_match:
                street = f"{street} {number_match.group(1)}"

            price_text = None
            for item in card.select("span.house-details-item"):
                text = item.get_text(" ", strip=True)
                if "€" in text:
                    price_text = text
                    break

            if not street:
                continue

            address = ", ".join(p for p in (street, city) if p)

            out.append(
                Listing(
                    source_url=href,
                    address_raw=address,
                    city=city,
                    price_cents=parse_price_to_cents(price_text or ""),
                    raw_title=street,
                )
            )
        return out
