"""GameStop adapter — reads gamestop.com product-page availability.

Best-effort: reads the public product page's schema.org JSON-LD, with emphasis
on catching the moment a product opens for **preorder** (GameStop is one of the
better places to lock in Pokémon product at MSRP). GameStop sits behind
Cloudflare, so requests may be blocked — in that case we log and skip. We make no
attempt to evade those defenses.

Config: list of product page URLs to watch.
"""

from __future__ import annotations

import logging

from . import jsonld
from .base import Retailer, StockResult

log = logging.getLogger(__name__)


class GameStop(Retailer):
    name = "gamestop"

    def check(self) -> list[StockResult]:
        results: list[StockResult] = []
        for url in self.cfg.get("urls", []):
            try:
                html = self._get(url, headers={"Accept": "text/html"}).text
                name, price, token = jsonld.parse(html)
                if token is None:
                    log.debug("[gamestop] no availability data at %s (blocked or no JSON-LD)", url)
                    continue
                pid = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
                name = name or f"GameStop {pid}"
                if token in jsonld.PREORDER_TOKENS:
                    results.append(StockResult(
                        self.name, pid, name, True, price, url, availability_type="preorder",
                    ))
                else:
                    results.append(StockResult(
                        self.name, pid, name, token in jsonld.IN_STOCK_TOKENS,
                        price, url, availability_type="online",
                    ))
            except Exception as e:  # noqa: BLE001 - Cloudflare may block; degrade gracefully
                log.warning("[gamestop] %s failed: %s", url, e)
        return results
