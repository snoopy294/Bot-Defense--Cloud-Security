"""Retailer adapters. Read-only availability checks; no purchasing."""

from .base import Retailer, StockResult
from .bestbuy import BestBuy
from .costco import Costco
from .gamestop import GameStop
from .pokemoncenter import PokemonCenter
from .target import Target
from .walmart import Walmart

# Maps the config key -> adapter class.
ADAPTERS = {
    "bestbuy": BestBuy,
    "target": Target,
    "walmart": Walmart,
    "pokemoncenter": PokemonCenter,
    "costco": Costco,
    "gamestop": GameStop,
}

__all__ = ["Retailer", "StockResult", "ADAPTERS"]
