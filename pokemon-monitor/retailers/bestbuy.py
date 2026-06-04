"""Best Buy adapter — uses the official, free Best Buy Products API.

API docs: https://developer.bestbuy.com/
We query each SKU's online availability, preorder status, and (optionally)
in-store pickup availability near a ZIP. This is the sanctioned, documented way
to read Best Buy data; respect the published rate limits.
"""

from __future__ import annotations

import logging

from .base import Retailer, StockResult, normalize_zip

log = logging.getLogger(__name__)

API = "https://api.bestbuy.com/v1/products/{sku}.json"
# Combined products+stores query for in-store pickup availability near an area.
STORES_API = "https://api.bestbuy.com/v1/products(sku={sku})+stores(area({zip},{radius})).json"
# Only request the fields we actually use.
SHOW = "sku,name,salePrice,onlineAvailability,orderable,url"


class BestBuy(Retailer):
    name = "bestbuy"

    def check(self) -> list[StockResult]:
        api_key = self.cfg.get("api_key")
        if not api_key:
            log.warning("[bestbuy] no api_key configured; skipping")
            return []

        check_stores = bool(self.cfg.get("check_stores"))
        zip_code = normalize_zip(self.cfg.get("zip", ""))
        radius = int(self.cfg.get("radius", 25))

        results: list[StockResult] = []
        for sku in self.cfg.get("skus", []):
            try:
                data = self._get(
                    API.format(sku=sku),
                    params={"apiKey": api_key, "show": SHOW, "format": "json"},
                ).json()
                results.extend(self._online_results(sku, data))

                if check_stores and zip_code:
                    results.extend(
                        self._pickup_results(sku, data, api_key, zip_code, radius)
                    )
            except Exception as e:  # noqa: BLE001 - skip one bad SKU, keep going
                log.warning("[bestbuy] SKU %s failed: %s", sku, e)
        return results

    def _online_results(self, sku, data: dict) -> list[StockResult]:
        price = data.get("salePrice")
        name = data.get("name") or f"Best Buy SKU {sku}"
        url = data.get("url") or f"https://www.bestbuy.com/site/{sku}.p"
        price_str = f"${price}" if price is not None else None
        orderable = (data.get("orderable") or "").lower()

        out = [
            StockResult(
                retailer=self.name,
                product_id=str(sku),
                name=name,
                in_stock=bool(data.get("onlineAvailability")),
                price=price_str,
                url=url,
                availability_type="online",
            )
        ]
        # Best Buy exposes preorder state via the `orderable` field.
        if orderable == "preorder":
            out.append(
                StockResult(
                    retailer=self.name,
                    product_id=str(sku),
                    name=name,
                    in_stock=True,
                    price=price_str,
                    url=url,
                    availability_type="preorder",
                )
            )
        return out

    def _pickup_results(self, sku, data: dict, api_key, zip_code, radius) -> list[StockResult]:
        name = data.get("name") or f"Best Buy SKU {sku}"
        url = data.get("url") or f"https://www.bestbuy.com/site/{sku}.p"
        resp = self._get(
            STORES_API.format(sku=sku, zip=zip_code, radius=radius),
            params={"apiKey": api_key, "format": "json", "show": "storeId,name,city"},
        ).json()
        out = []
        for store in resp.get("stores", []) or []:
            store_name = store.get("name") or store.get("city") or str(store.get("storeId"))
            out.append(
                StockResult(
                    retailer=self.name,
                    product_id=str(sku),
                    name=name,
                    in_stock=True,  # presence in the stores list means available there
                    price=None,
                    url=url,
                    availability_type="pickup",
                    store=f"Best Buy {store_name}",
                )
            )
        return out
