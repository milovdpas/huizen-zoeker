"""makelaardijdeleygraaf.nl — rental listings near Oss, +10km.

Markup: each listing is `li.al4woning`. Inside:
  - h3.street-address               → street + house number ("Johan van Bijnenstraat 23")
  - span.postal-code                → "5348 BK"
  - span.locality                   → "Oss"
  - span.kenmerkValue (.koopprijs)  → price (e.g. "€ 325.000,- k.k." or "€ 1.500,- per maand")
  - a.aanbodEntryLink[href]         → relative detail URL

When the user-configured URL has no current rental listings, the page may
still render `koop` (purchase) listings depending on the site. We restrict
inserts to URLs containing `/huur/` so we never accidentally save buy listings.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import parse_price_to_cents
from .base import BaseScraper, Listing


class DeLeygraaf(BaseScraper):
    SCRAPER_KEY = "deleygraaf"
    DISPLAY_NAME = "Makelaardij de Leygraaf"
    SUPPORTED_TYPES = {"rent", "buy"}
    URL_TEMPLATES = {
        "rent": "https://www.makelaardijdeleygraaf.nl/aanbod/woningaanbod/{slug_upper}/+10km/huur/",
        "buy": "https://www.makelaardijdeleygraaf.nl/aanbod/woningaanbod/{slug_upper}/+10km/koop/",
    }
    USE_PLAYWRIGHT = True
    WAIT_FOR_SELECTOR = "li.al4woning, .geen-resultaten, body"

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        seen: set[str] = set()

        # The page can render the other type's listings when the requested type
        # is empty; restrict to hrefs matching the type we asked for.
        wanted_segment = "/koop/" if self.listing_type == "buy" else "/huur/"

        for card in soup.select("li.al4woning"):
            link = card.select_one("a.aanbodEntryLink[href]")
            if not link:
                continue
            href = link.get("href") or ""
            if wanted_segment not in href.lower():
                continue

            full_url = urljoin(self.START_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            street_el = card.select_one("h3.street-address")
            postcode_el = card.select_one("span.postal-code")
            city_el = card.select_one("span.locality")
            price_el = card.select_one("span.kenmerkValue")

            street = street_el.get_text(" ", strip=True) if street_el else ""
            postcode = postcode_el.get_text(" ", strip=True) if postcode_el else ""
            city = city_el.get_text(" ", strip=True) if city_el else None
            price_text = price_el.get_text(" ", strip=True) if price_el else None

            if not street:
                continue

            postcode_city = " ".join(p for p in (postcode, city or "") if p).strip()
            address = ", ".join(p for p in (street, postcode_city) if p)

            out.append(
                Listing(
                    source_url=full_url,
                    address_raw=address,
                    city=city,
                    price_cents=parse_price_to_cents(price_text or ""),
                    raw_title=street,
                )
            )
        return out
