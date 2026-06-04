"""Target adapter — reads the public RedSky product/fulfillment API.

RedSky is the same backend Target.com's own pages call. We use it read-only to
check fulfillment availability — ship-to-me, in-store pickup at nearby stores,
and preorder status — for a TCIN.

Note: the RedSky web API key is a public client key embedded in Target's site.
If Target changes it, update `redsky_key` here or in config. This is best-effort
and may break if Target restructures their API.
"""

from __future__ import annotations

import logging

from .base import Retailer, StockResult, normalize_zip

log = logging.getLogger(__name__)

# Public web client key used by Target.com's own front end.
DEFAULT_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
PDP = "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
FULFILL = "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"


class Target(Retailer):
    name = "target"

    def check(self) -> list[StockResult]:
        key = self.cfg.get("redsky_key") or DEFAULT_KEY
        # No store_id => skip the in-store pickup check (don't fall back to some
        # arbitrary store the user never asked about). Online/preorder still run.
        store_id = str(self.cfg.get("store_id", "") or "")
        zip_code = normalize_zip(self.cfg.get("zip", ""))
        radius = int(self.cfg.get("radius", 25))
        # When watching many TCINs, the extra PDP call per item doubles request
        # volume and gets the IP throttled by Akamai. Off by default: we skip the
        # name/price lookup and take price from the fulfillment payload instead.
        pdp_lookup = bool(self.cfg.get("pdp_lookup", False))

        results: list[StockResult] = []
        for tcin in self.cfg.get("tcins", []):
            tcin = str(tcin)
            try:
                results.extend(
                    self._check_one(tcin, key, store_id, zip_code, radius, pdp_lookup)
                )
            except Exception as e:  # noqa: BLE001
                log.warning("[target] TCIN %s failed: %s", tcin, e)
        return results

    def _check_one(self, tcin, key, store_id, zip_code, radius, pdp_lookup) -> list[StockResult]:
        url = f"https://www.target.com/p/-/A-{tcin}"

        params = {
            "key": key,
            "tcin": tcin,
            "has_size_context": "true",
        }
        if store_id:
            params["store_id"] = store_id
            params["pricing_store_id"] = store_id
            params["has_pickup_store"] = "true"
        if zip_code:
            params["zip"] = zip_code
            params["state"] = ""  # RedSky tolerates empty; zip drives location
        if radius:
            params["radius"] = radius

        product = (
            self._get(FULFILL, params=params).json().get("data", {}).get("product", {})
        )
        fulfillment = product.get("fulfillment", {}) or {}

        # Name/price: optional PDP call (off by default to keep request volume
        # low). Without it, fall back to a TCIN label and any price the
        # fulfillment payload happens to carry.
        if pdp_lookup:
            name, price = self._pdp(tcin, key, store_id)
        else:
            name = f"Target TCIN {tcin}"
            cur = (product.get("price", {}) or {}).get("current_retail")
            price = f"${cur}" if cur is not None else None

        out: list[StockResult] = []

        # Ship-to-me (online) + preorder.
        shipping = (fulfillment.get("shipping_options", {}) or {}).get("availability_status", "")
        out.append(
            StockResult(
                retailer=self.name, product_id=tcin, name=name,
                in_stock=shipping == "IN_STOCK", price=price, url=url,
                availability_type="online",
            )
        )
        if shipping in ("PRE_ORDER_SELLABLE", "PRE_ORDER_UNSELLABLE"):
            out.append(
                StockResult(
                    retailer=self.name, product_id=tcin, name=name,
                    in_stock=shipping == "PRE_ORDER_SELLABLE", price=price, url=url,
                    availability_type="preorder",
                )
            )

        # In-store pickup at nearby stores (only when a store_id is configured).
        for loc in (fulfillment.get("store_options", []) or []) if store_id else []:
            pickup = (loc.get("order_pickup", {}) or {}).get("availability_status")
            ship_to_store = (loc.get("ship_to_store", {}) or {}).get("availability_status")
            if pickup == "IN_STOCK" or ship_to_store == "IN_STOCK":
                store_name = loc.get("location_name") or loc.get("location_id") or "store"
                out.append(
                    StockResult(
                        retailer=self.name, product_id=tcin, name=name,
                        in_stock=True, price=price, url=url,
                        availability_type="pickup", store=f"Target {store_name}",
                    )
                )
        return out

    def _pdp(self, tcin, key, store_id) -> tuple[str, str | None]:
        """Best-effort product name + price; never fatal."""
        name = f"Target TCIN {tcin}"
        price = None
        try:
            item = (
                self._get(PDP, params={"key": key, "tcin": tcin, "pricing_store_id": store_id})
                .json()
                .get("data", {})
                .get("product", {})
            )
            name = (
                item.get("item", {}).get("product_description", {}).get("title") or name
            )
            cur = item.get("price", {}).get("current_retail")
            if cur is not None:
                price = f"${cur}"
        except Exception as e:  # noqa: BLE001
            log.debug("[target] pdp lookup for %s failed: %s", tcin, e)
        return name, price
