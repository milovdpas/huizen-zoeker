"""funda.nl — Cloudflare-protected, requires real browser.

Markup (search results, both /zoeken/huur and /makelaars/.../woningaanbod/...):
  - a[data-testid="listingDetailsAddress"][href="/detail/huur/<city>/<slug>/<id>/"]
      div.font-semibold       → street + house number, e.g. "Palmstraat 49"
      div.text-neutral-80     → postcode + city,        e.g. "5342 AN Oss"
  - Price lives in a sibling block within the same card, formatted "€ 1.750 /maand"

If Funda blocks via Cloudflare, the runner records a failed scrape — try
HEADLESS=false in .env to see what's happening.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


logger = logging.getLogger(__name__)


_POSTCODE_RE = re.compile(r"^\s*\d{4}\s*[A-Z]{2}\s*", re.IGNORECASE)
_PRICE_RE = re.compile(r"€\s*[\d.,\s]+")


class Funda(BaseScraper):
    SCRAPER_KEY = "funda"
    DISPLAY_NAME = "Funda"
    SUPPORTED_TYPES = {"rent", "buy"}
    URL_TEMPLATES = {
        "rent": 'https://www.funda.nl/zoeken/huur/?selected_area=["{slug}"]',
        "buy": 'https://www.funda.nl/zoeken/koop/?selected_area=["{slug}"]',
    }

    USE_PLAYWRIGHT = True
    USE_STEALTH = True
    COOKIES_FILE = "cookies/funda.txt"
    COOKIES_DOMAIN = ".funda.nl"
    WAIT_FOR_SELECTOR = 'a[data-testid="listingDetailsAddress"]'
    COOKIE_ACCEPT_SELECTORS = [
        "#didomi-notice-agree-button",
        "button[aria-label='Akkoord']",
        "button:has-text('Akkoord')",
        "button:has-text('Accept')",
    ]

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        seen: set[str] = set()

        for addr_link in soup.select('a[data-testid="listingDetailsAddress"][href]'):
            href = addr_link.get("href") or ""
            full_url = urljoin(self.START_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            street_el = addr_link.select_one("div.font-semibold")
            postcode_city_el = addr_link.select_one("div.text-neutral-80")

            street = street_el.get_text(" ", strip=True) if street_el else ""
            postcode_city = (
                postcode_city_el.get_text(" ", strip=True) if postcode_city_el else ""
            )
            if not street and not postcode_city:
                continue

            address = ", ".join(p for p in (street, postcode_city) if p)

            city = self.city_hint
            if postcode_city:
                city_part = _POSTCODE_RE.sub("", postcode_city).strip()
                if city_part:
                    city = city_part

            price_cents = _find_price_for(addr_link, self.listing_type)

            out.append(
                Listing(
                    source_url=full_url,
                    address_raw=address,
                    city=city,
                    price_cents=price_cents,
                    raw_title=street or address,
                )
            )

        logger.debug("%s: extracted %d funda listings", self.SOURCE_NAME, len(out))
        return out


# Buy listings price the card with "k.k." (kosten koper) or "v.o.n." (vrij op
# naam) instead of "/maand"; match the right marker per listing type.
_RENT_MARKER_RE = re.compile(r"maand", re.IGNORECASE)
_BUY_MARKER_RE = re.compile(r"k\.?\s*k\.?|v\.?\s*o\.?\s*n\.?|kosten\s+koper", re.IGNORECASE)


def _find_price_for(addr_link, listing_type: str) -> int | None:
    """Walk up to the smallest ancestor card that contains '€' plus the
    price marker appropriate for the listing type (rent → 'maand';
    buy → 'k.k.'/'v.o.n.')."""
    marker = _BUY_MARKER_RE if listing_type == "buy" else _RENT_MARKER_RE
    card = addr_link.find_parent(
        lambda t: (
            t.name == "div"
            and "€" in t.get_text()
            and bool(marker.search(t.get_text()))
        )
    )
    if not card:
        return None
    m = _PRICE_RE.search(card.get_text(" ", strip=True))
    if not m:
        return None
    return parse_price_to_cents(m.group(0))
