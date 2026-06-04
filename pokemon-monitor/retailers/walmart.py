"""Walmart adapter — reads availability from the public product page.

Walmart's old public affiliate API is deprecated, so we read the server-rendered
JSON that the product page already ships to browsers (the __NEXT_DATA__ blob).

This is the most fragile source in the project: Walmart changes page structure
often and is aggressive about bot traffic. We send an honest User-Agent, poll
slowly, and simply skip (log a warning) when parsing fails — we do NOT try to
defeat any bot protection. If this breaks, treat it as expected.
"""

from __future__ import annotations

import json
import logging
import re

from .base import Retailer, StockResult

log = logging.getLogger(__name__)

PAGE = "https://www.walmart.com/ip/{item_id}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class Walmart(Retailer):
    name = "walmart"

    def check(self) -> list[StockResult]:
        results: list[StockResult] = []
        for item_id in self.cfg.get("item_ids", []):
            item_id = str(item_id)
            try:
                results.append(self._check_one(item_id))
            except Exception as e:  # noqa: BLE001
                log.warning("[walmart] item %s failed: %s", item_id, e)
        return results

    def _check_one(self, item_id: str) -> StockResult:
        html = self._get(
            PAGE.format(item_id=item_id),
            headers={"Accept": "text/html"},
        ).text

        m = NEXT_DATA_RE.search(html)
        if not m:
            raise ValueError("could not find __NEXT_DATA__ on page")
        data = json.loads(m.group(1))

        product = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("data", {})
            .get("product", {})
        )
        if not product:
            raise ValueError("product node missing from page data")

        name = product.get("name") or f"Walmart item {item_id}"
        status = (product.get("availabilityStatus") or "").upper()
        in_stock = status == "IN_STOCK"

        price = None
        price_info = product.get("priceInfo", {}).get("currentPrice", {})
        if price_info.get("price") is not None:
            price = price_info.get("priceString") or f"${price_info['price']}"

        return StockResult(
            retailer=self.name,
            product_id=item_id,
            name=name,
            in_stock=in_stock,
            price=price,
            url=PAGE.format(item_id=item_id),
        )
