"""Refresh cookies/funda.txt from the user's local browser.

Default flow:
  1. Open the funda Oss search in the default browser (forces Chrome/Edge to
     hit Akamai and refresh bm_* tokens).
  2. Wait `--wait` seconds for the page to settle.
  3. Read funda.nl cookies from the browser's local cookie store via
     browser-cookie3 (handles Windows DPAPI; copies the locked DB).
  4. Write `name=value; name2=value2; ...` to cookies/funda.txt.

Primary path (default, no admin / no external Chrome needed):
  Launch Playwright's own Chromium with a persistent profile, navigate to
  funda, let Akamai set bm_* tokens, accept the cookie banner, and read the
  cookies straight from the browser context — plaintext, so Chrome 127+
  app-bound encryption is irrelevant.

Usage:
  python scripts/refresh_funda_cookies.py                    # Playwright session (visible window)
  python scripts/refresh_funda_cookies.py --headless         # Playwright session, no window
  python scripts/refresh_funda_cookies.py --wait=45          # longer settle time
  python scripts/refresh_funda_cookies.py --use-system-browser   # legacy: read from your real browser
  python scripts/refresh_funda_cookies.py --use-system-browser --no-browser  # legacy, read-only
  python scripts/refresh_funda_cookies.py --browser=edge     # legacy: prefer Edge's cookie store
"""
from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from pathlib import Path


FUNDA_REFRESH_URL = 'https://www.funda.nl/zoeken/huur/?selected_area=["oss"]'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIES_FILE = PROJECT_ROOT / "cookies" / "funda.txt"
# Dedicated Playwright profile — persists bm_*/consent cookies across refreshes
# so Akamai trusts the session more over time.
PW_PROFILE_DIR = PROJECT_ROOT / "cookies" / "pw_profile"

# Keep the project root importable so we can reuse the scraper's UA + stealth
# (same fingerprint => cookies stay valid when injected back into the scraper).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_COOKIE_ACCEPT_SELECTORS = [
    "#didomi-notice-agree-button",
    "button[aria-label='Akkoord']",
    "button:has-text('Akkoord')",
    "button:has-text('Accept')",
]


def _read_via_playwright_session(
    domain: str,
    funda_url: str,
    wait_seconds: int,
    headless: bool,
) -> list[tuple[str, str]]:
    """Launch Playwright's bundled Chromium with a persistent profile, navigate
    to funda, accept the cookie banner, let Akamai settle, then read cookies
    directly from the context. No DPAPI/app-bound decryption, no admin, no
    externally-launched Chrome — the most reliable path on Windows + Chrome 127+.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  pw-session: playwright not installed", file=sys.stderr)
        return []

    # Reuse the scraper's UA + stealth so the cookies match the fingerprint they
    # get injected into later; fall back to a sane UA if the import path breaks.
    user_agent = _FALLBACK_UA
    apply_stealth = None
    try:
        from huizenzoeker.scrapers.base import _DEFAULT_UA, _apply_stealth

        user_agent = _DEFAULT_UA
        apply_stealth = _apply_stealth
    except Exception:  # noqa: BLE001
        pass

    PW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PW_PROFILE_DIR),
                headless=headless,
                user_agent=user_agent,
                locale="nl-NL",
                viewport={"width": 1366, "height": 900},
            )
        except Exception as e:  # noqa: BLE001
            print(f"  pw-session: launch failed ({e})", file=sys.stderr)
            return []

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if apply_stealth is not None:
                try:
                    apply_stealth(page)
                except Exception:  # noqa: BLE001
                    pass

            try:
                page.goto(funda_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:  # noqa: BLE001
                print(f"  pw-session: navigation failed ({e})", file=sys.stderr)

            # Accept the cookie banner so consent cookies get written.
            for sel in _COOKIE_ACCEPT_SELECTORS:
                try:
                    page.locator(sel).first.click(timeout=2500)
                    page.wait_for_timeout(500)
                    break
                except Exception:
                    continue

            time.sleep(wait_seconds)

            seen: set[str] = set()
            out: list[tuple[str, str]] = []
            for c in ctx.cookies():
                if domain not in (c.get("domain") or ""):
                    continue
                if not c.get("value") or c["name"] in seen:
                    continue
                seen.add(c["name"])
                out.append((c["name"], c["value"]))

            if out:
                print(f"  pw-session: {len(out)} cookies")
            else:
                print(
                    f"  pw-session: no {domain} cookies after refresh "
                    "(Akamai may have blocked — try without --headless)",
                    file=sys.stderr,
                )
            return out
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _read_via_cdp(
    domain: str,
    funda_url: str,
    wait_seconds: int,
    port: int = 9222,
) -> list[tuple[str, str]]:
    """Connect to a running Chrome (started with --remote-debugging-port=<port>)
    and pull cookies via the DevTools Protocol — bypasses Chrome 127+ app-bound
    encryption entirely because cookies come back in plaintext over CDP.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    pw = None
    try:
        pw = sync_playwright().start()
    except Exception as e:  # noqa: BLE001
        print(f"  cdp: playwright start failed ({e})", file=sys.stderr)
        return []

    try:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
        except Exception:
            print(
                f"  cdp/:{port}: no Chrome listening "
                f"(launch Chrome with --remote-debugging-port={port})",
                file=sys.stderr,
            )
            return []

        def _collect(b) -> list[tuple[str, str]]:
            seen: set[str] = set()
            out: list[tuple[str, str]] = []
            for ctx in b.contexts:
                for c in ctx.cookies():
                    if domain not in (c.get("domain") or ""):
                        continue
                    if not c.get("value") or c["name"] in seen:
                        continue
                    seen.add(c["name"])
                    out.append((c["name"], c["value"]))
            return out

        pairs = _collect(browser)
        if not pairs:
            # No funda cookies in any existing context — open a tab to populate them
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(funda_url, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(wait_seconds)
                pairs = _collect(browser)
            finally:
                try:
                    page.close()
                except Exception:
                    pass

        if pairs:
            print(f"  cdp/:{port}: {len(pairs)} cookies")
        else:
            print(f"  cdp/:{port}: no {domain} cookies after refresh", file=sys.stderr)
        return pairs
    finally:
        try:
            pw.stop()
        except Exception:
            pass


def _read_via_rookiepy(domain: str, candidates: list[str]) -> list[tuple[str, str]]:
    """Rust-backed extractor; handles Chrome 127+ app-bound encryption without admin."""
    try:
        import rookiepy  # type: ignore
    except ImportError:
        return []

    for name in candidates:
        loader = getattr(rookiepy, name, None)
        if loader is None:
            continue
        try:
            cookies = loader([domain])
        except Exception as e:  # noqa: BLE001
            print(f"  rookiepy/{name}: skipped ({e})", file=sys.stderr)
            continue
        pairs = [
            (c["name"], c["value"])
            for c in cookies
            if c.get("value") and domain in (c.get("domain") or "")
        ]
        if pairs:
            print(f"  rookiepy/{name}: {len(pairs)} cookies")
            return pairs
        print(f"  rookiepy/{name}: no {domain} cookies", file=sys.stderr)
    return []


def _read_via_browser_cookie3(domain: str, candidates: list[str]) -> list[tuple[str, str]]:
    """Pure-Python fallback. Fails on Chrome 127+ without admin (app-bound encryption)."""
    try:
        import browser_cookie3
    except ImportError:
        return []

    for name in candidates:
        loader = getattr(browser_cookie3, name, None)
        if loader is None:
            continue
        try:
            jar = loader(domain_name=domain)
        except Exception as e:  # noqa: BLE001
            print(f"  bc3/{name}: skipped ({e})", file=sys.stderr)
            continue
        pairs = [
            (c.name, c.value)
            for c in jar
            if c.value and domain in (c.domain or "")
        ]
        if pairs:
            print(f"  bc3/{name}: {len(pairs)} cookies")
            return pairs
        print(f"  bc3/{name}: no {domain} cookies", file=sys.stderr)
    return []


def _read_cookies(
    browser_name: str | None,
    funda_url: str,
    wait_seconds: int,
    cdp_port: int,
    headless: bool,
    use_system_browser: bool,
) -> list[tuple[str, str]]:
    """Default: self-contained Playwright session. With --use-system-browser,
    fall back to reading the user's real browser via CDP -> rookiepy -> bc3."""
    if not use_system_browser:
        pairs = _read_via_playwright_session(
            "funda.nl", funda_url, wait_seconds, headless
        )
        if pairs:
            return pairs

    candidates = ["chrome", "edge", "firefox", "brave", "opera"]
    if browser_name:
        candidates = [browser_name] + [c for c in candidates if c != browser_name]

    pairs = _read_via_cdp("funda.nl", funda_url, wait_seconds, cdp_port)
    if pairs:
        return pairs
    pairs = _read_via_rookiepy("funda.nl", candidates)
    if pairs:
        return pairs
    return _read_via_browser_cookie3("funda.nl", candidates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--use-system-browser",
        action="store_true",
        help="Legacy: open funda in your real browser and read its cookie store "
        "(CDP/rookiepy/bc3) instead of using a self-contained Playwright session.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the Playwright session without a visible window "
        "(less reliable against Akamai; default is a visible window).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="With --use-system-browser: skip opening funda, just read existing cookies.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=25,
        help="Seconds to wait after opening the browser (default: 25).",
    )
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge", "firefox", "brave", "opera"],
        default=None,
        help="Preferred browser to read cookies from. Falls back to others.",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=9222,
        help="Chrome remote-debugging port to connect to via CDP (default 9222).",
    )
    args = parser.parse_args()

    # The Playwright session navigates funda itself, so we only pop the *system*
    # browser in legacy --use-system-browser mode.
    if args.use_system_browser and not args.no_browser:
        print(f"Opening {FUNDA_REFRESH_URL} in default browser...")
        webbrowser.open(FUNDA_REFRESH_URL, new=2)
        print(f"Waiting {args.wait}s for Akamai tokens to settle...")
        time.sleep(args.wait)

    print("Reading cookies:")
    pairs = _read_cookies(
        args.browser,
        FUNDA_REFRESH_URL,
        args.wait,
        args.cdp_port,
        headless=args.headless,
        use_system_browser=args.use_system_browser,
    )
    if not pairs:
        print(
            "\nERROR: no funda.nl cookies extracted.\n"
            "The default Playwright session should work without admin. If it\n"
            "returned nothing, Akamai likely blocked the visit — try again, or\n"
            "run without --headless so the window is visible.\n"
            "Legacy --use-system-browser fixes (Chrome 127+ app-bound encryption):\n"
            "  - Launch Chrome with `--remote-debugging-port=9222` and rerun with\n"
            "    --use-system-browser (reads via CDP, no decryption needed).\n"
            "  - pip install rookiepy (needs Python <=3.12 for prebuilt wheels)\n"
            "  - Run as Administrator (UAC every time).",
            file=sys.stderr,
        )
        return 2

    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_FILE.write_text(
        "; ".join(f"{n}={v}" for n, v in pairs), encoding="utf-8"
    )
    print(f"Wrote {len(pairs)} cookies to {COOKIES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
