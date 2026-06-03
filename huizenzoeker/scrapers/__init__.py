from .base import BaseScraper, Listing
from .directwonen import DirectwonenOss, DirectwonenBerghem
from .krabben import Krabben
from .funda import FundaOss, FundaBerghem, FundaDigimakelaars
from .rncwonen import RncWonen
from .easyleasewonen import EasyLeaseWonen
from .gapph import Gapph
from .deleygraaf import DeLeygraaf


ALL_SCRAPERS: list[type[BaseScraper]] = [
    DirectwonenOss,
    DirectwonenBerghem,
    Krabben,
    FundaOss,
    FundaBerghem,
    FundaDigimakelaars,
    RncWonen,
    EasyLeaseWonen,
    Gapph,
    DeLeygraaf,
]


__all__ = ["BaseScraper", "Listing", "ALL_SCRAPERS"]
