"""Costco adapter — reads costco.com product-page availability.

Best-effort: reads the public product page's schema.org JSON-LD. Costco runs
Akamai bot defenses, so requests may be blocked outright — in that case we log
and skip. We make no attempt to evade those defenses.

Config: list of product page URLs to watch.
"""

from __future__ import annotations

import logging

from . import jsonld
from .base import Retailer, StockResult

log = logging.getLogger(__name__)


class Costco(Retailer):
    name = "costco"

    def check(self) -> list[StockResult]:
        results: list[StockResult] = []
        for url in self.cfg.get("urls", []):
            try:
                html = self._get(url, headers={"Accept": "text/html"}).text
                name, price, token = jsonld.parse(html)
                if token is None:
                    log.debug("[costco] no availability data at %s (blocked or no JSON-LD)", url)
                    continue
                pid = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
                results.append(StockResult(
                    retailer=self.name,
                    product_id=pid,
                    name=name or f"Costco {pid}",
                    in_stock=token in jsonld.IN_STOCK_TOKENS,
                    price=price,
                    url=url,
                    availability_type="online",
                ))
            except Exception as e:  # noqa: BLE001 - Akamai may block; degrade gracefully
                log.warning("[costco] %s failed: %s", url, e)
        return results
