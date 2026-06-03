import re
import unicodedata
from typing import Optional


_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]")


def normalize_address(raw: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop non-alphanumeric.

    Used as the dedup key — same physical address from different scrapers
    should normalize to the same string.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


_PRICE_NUM_RE = re.compile(r"\d[\d.,\s]*")


def parse_price_to_cents(text: Optional[str]) -> Optional[int]:
    """Parse Dutch/EU price strings like '€ 1.500,-' '€1500' '1500 EUR' '1.250 p/m'."""
    if not text:
        return None
    cleaned = text.replace(" ", " ")
    cleaned = re.sub(
        r"[€$£]|p/m|per\s+maand|excl\.?|incl\.?|EUR|euro|,-",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    m = _PRICE_NUM_RE.search(cleaned)
    if not m:
        return None
    num = m.group(0).strip()

    if "," in num and "." in num:
        # Dutch (1.500,00) vs US (1,500.00) — last separator is decimal
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        parts = num.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            # 1,500 → thousands separator
            num = num.replace(",", "")
        else:
            num = num.replace(",", ".")
    elif "." in num:
        parts = num.split(".")
        # 1.500 (Dutch thousands) → strip; 1500.50 (decimal) → keep
        if len(parts) >= 2 and all(len(p) == 3 for p in parts[1:]):
            num = num.replace(".", "")
    num = num.replace(" ", "")
    try:
        return int(round(float(num) * 100))
    except ValueError:
        return None


def cents_to_eur_str(cents: Optional[int]) -> str:
    if cents is None:
        return "?"
    return f"€{cents / 100:,.0f}".replace(",", ".")
