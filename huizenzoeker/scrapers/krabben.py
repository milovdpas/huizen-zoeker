"""krabben.nl — rentals within 10km of Oss.

Markup: each listing is itself an `<a class="flex flex-col group">` card. Inside:
  - h3                     → city (e.g. "Oss")
  - h2                     → street + house number (e.g. "Meijer van Leeuwenstraat 52")
  - div.mt-auto            → details line: "€ 1.152,00 / mnd. | 89 m² | 4 kamers | …"
  - href                   → absolute detail URL like /wonen/aanbod/oss-...

Krabben publishes full street + number, so address-based cross-site dedup
will work for these listings.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


_DETAIL_PATH_RE = re.compile(r"/wonen/aanbod/[^/?#]+")
_PRICE_RE = re.compile(r"€\s*[\d.,\s]+")


class Krabben(BaseScraper):
    SOURCE_NAME = "krabben"
    START_URL = (
        "https://www.krabben.nl/wonen/aanbod"
        "?price_type=rental"
        "&market%5B%5D=living"
        "&market%5B%5D=new-construction"
        "&search=Oss"
        "&search_type=city"
        "&distance=10"
        "&price_min=0"
    )
    CITY_HINT = None
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "a.group[href*='/wonen/aanbod/']"

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        seen: set[str] = set()

        for card in soup.select("a.group[href]"):
            href = card.get("href") or ""
            if not _DETAIL_PATH_RE.search(href):
                continue
            full_url = urljoin(self.START_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Only keep Beschikbaar listings — skip Verhuurd, Onder optie, etc.
            status_el = card.select_one("span[status]")
            status = status_el.get("status") if status_el else None
            if status != "Beschikbaar":
                continue

            address_el = card.select_one("h2")
            city_el = card.select_one("h3")
            details_el = card.select_one("div.mt-auto")

            street = address_el.get_text(" ", strip=True) if address_el else ""
            city = city_el.get_text(" ", strip=True) if city_el else None
            details = details_el.get_text(" ", strip=True) if details_el else ""

            if not street:
                continue

            address = ", ".join(p for p in (street, city) if p)

            price_match = _PRICE_RE.search(details)
            price_cents = (
                parse_price_to_cents(price_match.group(0)) if price_match else None
            )

            out.append(
                Listing(
                    source_url=full_url,
                    address_raw=address,
                    city=city,
                    price_cents=price_cents,
                    raw_title=street,
                )
            )
        return out
