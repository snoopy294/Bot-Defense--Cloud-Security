"""Pokémon Center adapter — reads official product-page availability.

Best-effort: we read the public product page's schema.org JSON-LD to determine
whether an item is in stock or available for preorder. Pokémon Center sits behind
bot protection; if a request is blocked or the page omits JSON-LD, we log and
skip rather than attempting to evade anything.

Config: list of product page URLs to watch.
"""

from __future__ import annotations

import logging

from . import jsonld
from .base import Retailer, StockResult

log = logging.getLogger(__name__)


class PokemonCenter(Retailer):
    name = "pokemoncenter"

    def check(self) -> list[StockResult]:
        results: list[StockResult] = []
        for url in self.cfg.get("urls", []):
            try:
                html = self._get(url, headers={"Accept": "text/html"}).text
                name, price, token = jsonld.parse(html)
                if token is None:
                    log.debug("[pokemoncenter] no availability data at %s", url)
                    continue
                pid = url.rstrip("/").rsplit("/", 1)[-1]
                name = name or f"Pokémon Center {pid}"
                if token in jsonld.PREORDER_TOKENS:
                    results.append(StockResult(
                        self.name, pid, name, True, price, url, availability_type="preorder",
                    ))
                else:
                    results.append(StockResult(
                        self.name, pid, name, token in jsonld.IN_STOCK_TOKENS,
                        price, url, availability_type="online",
                    ))
            except Exception as e:  # noqa: BLE001 - bot-hostile; degrade gracefully
                log.warning("[pokemoncenter] %s failed: %s", url, e)
        return results
