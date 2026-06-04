"""Retailer adapter interface and shared types.

Each retailer adapter takes its slice of config plus a shared requests.Session
and returns a list of StockResult objects when polled. Adapters do availability
lookups ONLY — they never attempt to purchase or to bypass bot protection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import requests

log = logging.getLogger(__name__)

# Default cooldown (seconds) to pause a retailer after it returns HTTP 429.
RATE_LIMIT_COOLDOWN = 600


def normalize_zip(value) -> str:
    """Normalize a ZIP from config to a 5-digit string.

    YAML parses an unquoted leading-zero ZIP (e.g. `07030`) as an integer, which
    stringifies without the leading zero. Zero-pad short all-digit values so a
    ZIP entered either way still works.
    """
    z = str(value or "").strip()
    if z.isdigit() and len(z) < 5:
        return z.zfill(5)
    return z


@dataclass
class StockResult:
    """The availability of a single product at a single retailer."""

    retailer: str          # "bestbuy" | "target" | "walmart" | ...
    product_id: str        # SKU / TCIN / item id, as a string
    name: str              # human-readable product name (best effort)
    in_stock: bool
    price: str | None      # display price if known, else None
    url: str               # link a human can click to buy
    # How the item is available. "online" = ship to me, "pickup" = in-store
    # pickup, "preorder" = orderable at MSRP before release. Tracked separately
    # so online vs pickup vs preorder for the same product alert independently.
    availability_type: str = "online"
    store: str | None = None   # store name/id when availability_type == "pickup"

    @property
    def key(self) -> str:
        suffix = f":{self.store}" if self.store else ""
        return f"{self.retailer}:{self.product_id}:{self.availability_type}{suffix}"

    @property
    def label(self) -> str:
        """Short human label for the availability state."""
        if self.availability_type == "pickup":
            where = f" @ {self.store}" if self.store else ""
            return f"PICKUP{where}"
        if self.availability_type == "preorder":
            return "PREORDER"
        return "IN STOCK"


class Retailer:
    """Base class for retailer adapters."""

    name: str = "base"

    def __init__(self, cfg: dict, session: requests.Session):
        self.cfg = cfg
        self.session = session
        # When > now(), this adapter is in rate-limit cooldown and is skipped.
        self.paused_until = 0.0

    @property
    def paused(self) -> bool:
        return time.time() < self.paused_until

    def check(self) -> list[StockResult]:
        """Return current availability for every watched product.

        Implementations should catch their own per-product errors and skip,
        rather than letting one failure abort the whole cycle.
        """
        raise NotImplementedError

    # Small helper so adapters share consistent, polite request behaviour.
    def _get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 15)
        resp = self.session.get(url, **kwargs)
        # If we got rate-limited, pause this retailer for a cooldown window so we
        # back off instead of hammering. Honor Retry-After when present.
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            cooldown = RATE_LIMIT_COOLDOWN
            if retry_after:
                if retry_after.strip().isdigit():
                    cooldown = max(cooldown, int(retry_after))
                else:
                    # Retry-After may also be an HTTP-date.
                    try:
                        delta = parsedate_to_datetime(retry_after).timestamp() - time.time()
                        if delta > 0:
                            cooldown = max(cooldown, int(delta))
                    except (TypeError, ValueError):
                        pass
            self.paused_until = time.time() + cooldown
            log.warning("[%s] rate-limited (429); pausing %ds", self.name, cooldown)
        resp.raise_for_status()
        return resp
