"""Price-gouging filter — suppress alerts priced well above MSRP.

A monitor-level policy that keeps retailer adapters pure (they still do
availability lookups only). Given a per-product MSRP map and a tolerance
multiplier, it decides whether a restock is worth alerting on or is a
scalper-priced listing to ignore.

Fail-open by design: if the filter is disabled, the product has no known MSRP,
or the price can't be parsed, the alert is ALLOWED. A real restock must never be
silently dropped just because we lack price data.
"""

from __future__ import annotations

import logging
import re

from retailers.base import StockResult

log = logging.getLogger(__name__)

# Default tolerance if a price_filter is enabled without max_over_msrp set:
# allow up to 25% over MSRP before treating a price as gouging.
DEFAULT_MAX_OVER_MSRP = 1.25

# First number in a string, with optional thousands separators and decimals.
_PRICE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_price(price: str | None) -> float | None:
    """Parse a display price like "$1,234.50" into a float, or None.

    Returns None for None, empty, or anything without a parseable number, so
    callers can fail open rather than guess.
    """
    if not price:
        return None
    m = _PRICE_RE.search(str(price))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


class PriceFilter:
    """Decide whether a StockResult's price is close enough to MSRP to alert."""

    def __init__(self, enabled: bool, max_over_msrp: float, msrp_map: dict):
        self.enabled = bool(enabled)
        try:
            mom = float(max_over_msrp)
        except (TypeError, ValueError):
            mom = DEFAULT_MAX_OVER_MSRP
        # A multiplier <= 0 would block everything with a known MSRP; treat it
        # as the default so a misconfig can't silence every alert.
        self.max_over_msrp = mom if mom > 0 else DEFAULT_MAX_OVER_MSRP
        # Normalize keys to strings so a YAML int or string id both match the
        # StockResult.product_id (which is always a string).
        self.msrp_map: dict[str, float] = {}
        for k, v in (msrp_map or {}).items():
            try:
                self.msrp_map[str(k)] = float(v)
            except (TypeError, ValueError):
                log.warning("price filter: ignoring non-numeric MSRP for %r: %r", k, v)

    def cap_for(self, product_id: str) -> float | None:
        """The max acceptable price for a product, or None if MSRP is unknown."""
        msrp = self.msrp_map.get(str(product_id))
        return msrp * self.max_over_msrp if msrp is not None else None

    def allows(self, r: StockResult) -> bool:
        """True if this result should alert; False to suppress as overpriced."""
        if not self.enabled:
            return True
        cap = self.cap_for(r.product_id)
        if cap is None:
            return True  # no known MSRP -> can't judge -> fail open
        price = parse_price(r.price)
        if price is None:
            return True  # no parseable price -> fail open
        if price <= cap:
            return True
        log.info(
            "price filter: skipping %s — price $%.2f over cap $%.2f (max %.0f%% of MSRP)",
            r.key, price, cap, self.max_over_msrp * 100,
        )
        return False
