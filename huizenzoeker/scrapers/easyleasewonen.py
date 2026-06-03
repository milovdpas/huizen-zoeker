"""easyleasewonen.nl — pre-filtered to Oss + max €1500.

Markup: each listing is itself an `<a class="eazlee_object">`. Inside:
  - .eazlee_object_bottom_price          → "€1.500 per maand"
  - .eazlee_object_bottom_street_nummer  → "Bessenlaan" (no house number)
  - .eazlee_object_bottom_postcode_city  → "5345JG Oss"

Addresses are anonymized (no house number), so dedup by URL — the URL slug
contains a unique listing ID like H104920233.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


class EasyLeaseWonen(BaseScraper):
    SCRAPER_KEY = "easyleasewonen"
    DISPLAY_NAME = "EasyLease Wonen"
    SUPPORTED_TYPES = {"rent"}
    # Drop the old maxprice=1500 cap — per-recipient price caps handle that now.
    URL_TEMPLATES = {
        "rent": "https://www.easyleasewonen.nl/woning-aanbod?offer=rent&location={city}",
    }
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "a.eazlee_object"

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        for card in soup.select("a.eazlee_object[href]"):
            href = urljoin(self.START_URL, card["href"])

            street_el = card.select_one(".eazlee_object_bottom_street_nummer")
            postcode_el = card.select_one(".eazlee_object_bottom_postcode_city")
            price_el = card.select_one(".eazlee_object_bottom_price")

            street = street_el.get_text(" ", strip=True) if street_el else ""
            postcode_city = postcode_el.get_text(" ", strip=True) if postcode_el else ""
            if not street and not postcode_city:
                continue

            address = ", ".join(p for p in (street, postcode_city) if p)

            # "5345JG Oss" → "Oss"
            city = self.city_hint
            if postcode_city:
                parts = postcode_city.split()
                if parts:
                    city = parts[-1]

            price_text = price_el.get_text(" ", strip=True) if price_el else None

            out.append(
                Listing(
                    source_url=href,
                    address_raw=address,
                    city=city,
                    price_cents=parse_price_to_cents(price_text or ""),
                    raw_title=street or address,
                )
            )
        return out
