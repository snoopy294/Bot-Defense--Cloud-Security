"""Tests for the price-gouging filter.

Plain asserts so this runs without pytest:  python tests/test_pricefilter.py
(also works under pytest if it's installed).
"""

from __future__ import annotations

import os
import sys

# Allow running both as `python tests/test_pricefilter.py` and via pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pricefilter import DEFAULT_MAX_OVER_MSRP, PriceFilter, parse_price
from retailers.base import StockResult


def _result(price, product_id="123"):
    return StockResult(
        retailer="target", product_id=product_id, name="ETB",
        in_stock=True, price=price, url="https://example.com",
    )


def test_parse_price():
    assert parse_price("$49.99") == 49.99
    assert parse_price("$1,234.50") == 1234.50
    assert parse_price("49.99") == 49.99
    assert parse_price("USD 161.64") == 161.64
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("call for price") is None


def test_disabled_allows_everything():
    pf = PriceFilter(enabled=False, max_over_msrp=1.0, msrp_map={"123": 10.0})
    # Even a wildly overpriced item passes when the filter is off.
    assert pf.allows(_result("$9999.00")) is True


def test_unknown_msrp_fails_open():
    pf = PriceFilter(enabled=True, max_over_msrp=1.25, msrp_map={"999": 10.0})
    assert pf.allows(_result("$9999.00", product_id="123")) is True


def test_unparseable_price_fails_open():
    pf = PriceFilter(enabled=True, max_over_msrp=1.25, msrp_map={"123": 10.0})
    assert pf.allows(_result(None)) is True
    assert pf.allows(_result("see cart")) is True


def test_cap_boundary():
    pf = PriceFilter(enabled=True, max_over_msrp=1.20, msrp_map={"123": 50.0})
    # cap = 50 * 1.20 = 60.00
    assert pf.allows(_result("$59.99")) is True   # under cap
    assert pf.allows(_result("$60.00")) is True   # exactly at cap
    assert pf.allows(_result("$60.01")) is False  # just over cap
    assert pf.allows(_result("$120.00")) is False  # scalper price


def test_int_msrp_key_matches_string_product_id():
    # YAML may parse a numeric-looking key as int; product_id is a str.
    pf = PriceFilter(enabled=True, max_over_msrp=1.0, msrp_map={123: 50.0})
    assert pf.allows(_result("$50.00", product_id="123")) is True
    assert pf.allows(_result("$50.01", product_id="123")) is False


def test_bad_multiplier_uses_default():
    pf = PriceFilter(enabled=True, max_over_msrp=0, msrp_map={"123": 10.0})
    assert pf.max_over_msrp == DEFAULT_MAX_OVER_MSRP
    pf2 = PriceFilter(enabled=True, max_over_msrp="oops", msrp_map={"123": 10.0})
    assert pf2.max_over_msrp == DEFAULT_MAX_OVER_MSRP


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
