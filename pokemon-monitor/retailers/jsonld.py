"""Shared helper: read product availability from schema.org JSON-LD.

Most retail product pages embed a <script type="application/ld+json"> Product
object with an `offers.availability` field (e.g. schema.org/InStock,
/OutOfStock, /PreOrder). Reading that standard, public metadata is a robust,
honest way to check availability without scraping fragile markup or evading
anything. If a page omits JSON-LD or blocks us, the caller degrades gracefully.
"""

from __future__ import annotations

import json
import re

# Grab every JSON-LD block on the page.
_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _iter_products(node):
    """Yield every dict that looks like a schema.org Product, recursively."""
    if isinstance(node, dict):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any(str(x).lower() == "product" for x in types):
            yield node
        for v in node.values():
            yield from _iter_products(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_products(v)


def parse(html: str) -> tuple[str | None, str | None, str | None]:
    """Return (name, price, availability_token) from a page's JSON-LD.

    availability_token is the lowercased final path segment of the schema.org
    availability URL, e.g. "instock", "outofstock", "preorder", or None.
    """
    for block in _LD_RE.findall(html):
        try:
            data = json.loads(block)
        except Exception:  # noqa: BLE001 - skip malformed block, try the next
            continue
        for product in _iter_products(data):
            name = product.get("name")
            offers = product.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            offers = offers or {}
            price = offers.get("price")
            avail = offers.get("availability") or ""
            token = str(avail).rstrip("/").rsplit("/", 1)[-1].lower() or None
            price_str = f"${price}" if price not in (None, "") else None
            return name, price_str, token
    return None, None, None


# schema.org availability tokens that mean "you can order it right now".
IN_STOCK_TOKENS = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
PREORDER_TOKENS = {"preorder", "presale"}
