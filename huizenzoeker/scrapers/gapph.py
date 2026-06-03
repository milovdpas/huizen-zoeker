"""gapph.nl — region search for Oss.

Markup: each listing is `div.card-zoom`. Inside:
  - h2                       → city/village name (e.g. "Vinkel")
  - h3 > a                   → housing type (e.g. "Tijdelijke huurwoning") + relative href
  - div.ribbon > span        → price (e.g. "€ 499,-")
  - p.text-xl                → free-text description ("Ruim appartement van 80m²…")

Gapph never publishes a street address. The URL slug
(woonruimte/tijdelijk-huren/<city>/<id>) carries the unique listing ID, so
URL-based dedup is the only reliable identity here.

Note: region_search=oss returns nearby villages too (Vinkel, etc.), so the
card's h2 city is what counts — not the search query.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


class Gapph(BaseScraper):
    SOURCE_NAME = "gapph"
    START_URL = "https://www.gapph.nl/woonruimte/zoeken?region_search=oss"
    CITY_HINT = "Oss"
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "div.card-zoom"

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        seen: set[str] = set()

        for card in soup.select("div.card-zoom"):
            link = card.find("a", href=True)
            if not link:
                continue
            href = urljoin(self.START_URL, link["href"])
            if href in seen:
                continue
            seen.add(href)

            city_el = card.select_one("h2")
            type_el = card.select_one("h3")
            price_el = card.select_one("div.ribbon span")
            desc_el = card.select_one("p.text-xl, p.leading-relaxed")

            city = city_el.get_text(" ", strip=True) if city_el else self.CITY_HINT
            type_text = type_el.get_text(" ", strip=True) if type_el else ""
            price_text = price_el.get_text(" ", strip=True) if price_el else None
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            address_parts = [p for p in (type_text, city) if p]
            if not address_parts:
                continue
            address = ", ".join(address_parts)

            out.append(
                Listing(
                    source_url=href,
                    address_raw=address,
                    city=city,
                    price_cents=parse_price_to_cents(price_text or ""),
                    raw_title=type_text or description or address,
                )
            )
        return out
