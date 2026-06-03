"""Base scraper.

Each site subclasses BaseScraper and either:
  - Sets the class-level CSS selector knobs and lets the default parse() work, or
  - Overrides parse() entirely for sites with unusual structure.

Selectors here are best-effort guesses — if a site changes its markup or
returns nothing, log into the UI ('Runs' page) shows the error message; tune
the selectors in the relevant subclass and restart.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import settings
from ..normalize import parse_price_to_cents


logger = logging.getLogger(__name__)


@dataclass
class Listing:
    source_url: str
    address_raw: str
    city: Optional[str] = None
    price_cents: Optional[int] = None
    raw_title: Optional[str] = None
    extra: dict = field(default_factory=dict)


class BaseScraper:
    SOURCE_NAME: str = ""
    START_URL: str = ""
    CITY_HINT: Optional[str] = None
    USE_PLAYWRIGHT: bool = True
    WAIT_FOR_SELECTOR: Optional[str] = None  # only used with playwright
    # Try each in order before waiting for content. First match is clicked.
    COOKIE_ACCEPT_SELECTORS: list[str] = []
    # Apply playwright-stealth (hides webdriver flag, plugins, languages, etc.)
    USE_STEALTH: bool = False
    # Path (relative to project root) to a Cookie: header dump like
    # "cf_clearance=…; _fz_uniq=…; …" — injected before navigation. Used to
    # ride a real browser session through Cloudflare on funda.
    COOKIES_FILE: Optional[str] = None
    COOKIES_DOMAIN: Optional[str] = None
    LISTING_LINK_REGEX: Optional[str] = None
    LISTING_CONTAINER_SELECTOR: Optional[str] = None
    ADDRESS_SELECTOR: Optional[str] = None
    PRICE_SELECTOR: Optional[str] = None
    TITLE_SELECTOR: Optional[str] = None

    def fetch(self) -> str:
        if self.USE_PLAYWRIGHT:
            return _fetch_playwright(
                self.START_URL,
                wait_for=self.WAIT_FOR_SELECTOR,
                cookie_accept_selectors=self.COOKIE_ACCEPT_SELECTORS,
                use_stealth=self.USE_STEALTH,
                cookies_file=self.COOKIES_FILE,
                cookies_domain=self.COOKIES_DOMAIN,
            )
        return _fetch_requests(self.START_URL)

    def parse(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        if self.LISTING_CONTAINER_SELECTOR:
            return self._parse_via_container(soup)
        if self.LISTING_LINK_REGEX:
            return self._parse_via_links(soup)
        logger.warning("%s: no selectors configured, returning []", self.SOURCE_NAME)
        return []

    def run(self) -> list[Listing]:
        html = self.fetch()
        listings = self.parse(html)
        logger.info("%s: parsed %d listings", self.SOURCE_NAME, len(listings))
        return listings

    # --- helpers ---

    def _parse_via_container(self, soup: BeautifulSoup) -> list[Listing]:
        out: list[Listing] = []
        for card in soup.select(self.LISTING_CONTAINER_SELECTOR or ""):
            link_el = card.find("a", href=True)
            if not link_el:
                continue
            href = urljoin(self.START_URL, link_el["href"])

            address = ""
            if self.ADDRESS_SELECTOR:
                el = card.select_one(self.ADDRESS_SELECTOR)
                if el:
                    address = el.get_text(" ", strip=True)
            if not address:
                # Fallback: link text or first heading inside the card
                heading = card.find(["h2", "h3", "h4"])
                address = (
                    heading.get_text(" ", strip=True)
                    if heading
                    else link_el.get_text(" ", strip=True)
                )

            price_text = None
            if self.PRICE_SELECTOR:
                p = card.select_one(self.PRICE_SELECTOR)
                if p:
                    price_text = p.get_text(" ", strip=True)
            if not price_text:
                # Find first € sign in card text
                m = re.search(r"€\s*[\d.,\s]+", card.get_text(" ", strip=True))
                if m:
                    price_text = m.group(0)

            title = None
            if self.TITLE_SELECTOR:
                t = card.select_one(self.TITLE_SELECTOR)
                if t:
                    title = t.get_text(" ", strip=True)

            if address:
                out.append(
                    Listing(
                        source_url=href,
                        address_raw=address,
                        city=self.CITY_HINT,
                        price_cents=parse_price_to_cents(price_text or ""),
                        raw_title=title or address,
                    )
                )
        return out

    def _parse_via_links(self, soup: BeautifulSoup) -> list[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        link_re = re.compile(self.LISTING_LINK_REGEX or "")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not link_re.search(href):
                continue
            full = urljoin(self.START_URL, href)
            if full in seen_urls:
                continue
            seen_urls.add(full)
            text = a.get_text(" ", strip=True)
            if not text:
                # Walk up to find a card with text
                parent = a.find_parent(["article", "div", "li"])
                text = parent.get_text(" ", strip=True) if parent else ""
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            address = text[:200]
            price_match = re.search(r"€\s*[\d.,\s]+", text)
            out.append(
                Listing(
                    source_url=full,
                    address_raw=address,
                    city=self.CITY_HINT,
                    price_cents=parse_price_to_cents(price_match.group(0)) if price_match else None,
                    raw_title=address,
                )
            )
        return out


# --- fetch backends ---

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _fetch_requests(url: str) -> str:
    import requests

    r = requests.get(
        url,
        headers={"User-Agent": _DEFAULT_UA, "Accept-Language": "nl-NL,nl;q=0.9"},
        timeout=settings.scrape_timeout,
    )
    r.raise_for_status()
    return r.text


def _fetch_playwright(
    url: str,
    wait_for: Optional[str] = None,
    cookie_accept_selectors: Optional[list[str]] = None,
    use_stealth: bool = False,
    cookies_file: Optional[str] = None,
    cookies_domain: Optional[str] = None,
) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.headless)
        try:
            ctx = browser.new_context(
                user_agent=_DEFAULT_UA,
                locale="nl-NL",
                viewport={"width": 1366, "height": 900},
            )

            if cookies_file and cookies_domain:
                injected = _load_cookies(cookies_file, cookies_domain)
                if injected:
                    ctx.add_cookies(injected)
                    logger.info(
                        "Injected %d cookie(s) for %s from %s",
                        len(injected),
                        cookies_domain,
                        cookies_file,
                    )

            page = ctx.new_page()

            if use_stealth:
                _apply_stealth(page)

            page.goto(url, wait_until="domcontentloaded", timeout=settings.scrape_timeout * 1000)

            # Dismiss cookie banner if any of the configured selectors match.
            # Short per-selector timeout — banner is either there or not.
            if cookie_accept_selectors:
                for sel in cookie_accept_selectors:
                    try:
                        page.locator(sel).first.click(timeout=2500)
                        logger.debug("Clicked cookie consent: %s", sel)
                        page.wait_for_timeout(500)
                        break
                    except Exception:
                        continue

            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=settings.scrape_timeout * 1000)
                except Exception:
                    logger.warning(
                        "Selector %s never appeared on %s — page title=%r",
                        wait_for,
                        url,
                        page.title(),
                    )
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            return page.content()
        finally:
            browser.close()


def _apply_stealth(page) -> None:
    """Apply stealth tweaks. Supports both old (`stealth_sync`) and new
    (`Stealth().apply_stealth_sync`) API styles so we work with either
    `playwright-stealth` or `tf-playwright-stealth`."""
    # Newer Stealth-class API (tf-playwright-stealth >= 1.2)
    try:
        from playwright_stealth import Stealth  # type: ignore

        Stealth().apply_stealth_sync(page)
        logger.debug("Applied stealth via Stealth().apply_stealth_sync")
        return
    except ImportError:
        pass
    except AttributeError:
        # Older module exposes stealth_sync directly, not Stealth class
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Stealth().apply_stealth_sync failed")
        return

    # Legacy stealth_sync API
    try:
        from playwright_stealth import stealth_sync  # type: ignore

        stealth_sync(page)
        logger.debug("Applied stealth via stealth_sync")
        return
    except ImportError as e:
        logger.warning(
            "playwright-stealth not importable (%s) — try: "
            "pip install --upgrade tf-playwright-stealth",
            e,
        )
    except Exception:  # noqa: BLE001
        logger.exception("stealth_sync failed to apply")


def _load_cookies(path: str, domain: str) -> list[dict]:
    """Read a Cookie: header dump from a file and convert to Playwright cookies.

    File format: a single line like
        cf_clearance=AbCdEf...; _fz_uniq=12345; consents=accepted
    (exactly what you'd copy from devtools → Network → request → Cookie header).
    """
    import os

    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        logger.exception("Could not read cookies file %s", path)
        return []
    if not raw:
        return []

    cookies: list[dict] = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax",
            }
        )
    return cookies
