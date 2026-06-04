"""Tests for re-notify reminders in run_cycle.

While a preorder/pickup item stays available, the monitor should re-alert every
`interval_seconds` so a missed first ping doesn't cost the drop. Online stays
once-only. Re-notify still respects the alert_types and price_filter gates.

Plain asserts so this runs without pytest:  python tests/test_renotify.py
(also works under pytest if it's installed).
"""

from __future__ import annotations

import os
import sys
import time as _real_time

# Allow running both as `python tests/test_renotify.py` and via pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import monitor
from monitor import Renotify, run_cycle
from pricefilter import PriceFilter
from retailers.base import StockResult


class _Clock:
    """A controllable stand-in for the time module's time()."""

    def __init__(self, t=1000.0):
        self.t = t

    def time(self):
        return self.t


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, r):
        self.sent.append(r)


class _FakeAdapter:
    name = "fake"
    paused = False
    paused_until = 0.0

    def __init__(self, results):
        self.results = results

    def check(self):
        return list(self.results)


def _result(in_stock=True, atype="preorder", price="$49.99", pid="123", store=None):
    return StockResult(
        retailer="target", product_id=pid, name="ETB",
        in_stock=in_stock, price=price, url="https://example.com",
        availability_type=atype, store=store,
    )


def _run(adapter, notifier, seen, alerted, clock, **kw):
    """run_cycle with monitor's clock swapped for our controllable one."""
    monitor.time = clock
    try:
        run_cycle([adapter], notifier, seen, alerted, **kw)
    finally:
        monitor.time = _real_time


WINNABLE = {"preorder", "pickup"}


def test_preorder_renotifies_after_interval():
    clock = _Clock(1000.0)
    adapter, notifier = _FakeAdapter([_result(atype="preorder")]), _FakeNotifier()
    seen, alerted = {}, {}
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 1            # first sight alerts once

    clock.t += 300                            # still in stock, before interval
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 1            # no re-ping yet

    clock.t += 400                            # 700s elapsed > 600s interval
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 2            # re-notify fires


def test_pickup_renotifies_after_interval():
    clock = _Clock(1000.0)
    adapter = _FakeAdapter([_result(atype="pickup", store="Target Plano West")])
    notifier, seen, alerted = _FakeNotifier(), {}, {}
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    clock.t += 601
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 2


def test_online_never_renotifies():
    clock = _Clock(1000.0)
    adapter, notifier = _FakeAdapter([_result(atype="online")]), _FakeNotifier()
    seen, alerted = {}, {}
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    clock.t += 100_000                        # online is excluded no matter how long
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 1


def test_out_of_stock_then_back_realerts_immediately():
    clock = _Clock(1000.0)
    adapter, notifier = _FakeAdapter([_result(atype="preorder")]), _FakeNotifier()
    seen, alerted = {}, {}
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 1

    adapter.results = [_result(atype="preorder", in_stock=False)]
    clock.t += 60
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 1            # going out of stock is silent

    adapter.results = [_result(atype="preorder", in_stock=True)]
    clock.t += 60                             # back in stock well within interval
    _run(adapter, notifier, seen, alerted, clock, renotify=rn)
    assert len(notifier.sent) == 2            # fresh transition alerts immediately


def test_renotify_respects_alert_types():
    clock = _Clock(1000.0)
    adapter, notifier = _FakeAdapter([_result(atype="preorder")]), _FakeNotifier()
    seen, alerted = {}, {}
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    # alert_types allows only pickup -> a preorder never alerts (or re-notifies).
    _run(adapter, notifier, seen, alerted, clock, alert_types={"pickup"}, renotify=rn)
    clock.t += 700
    _run(adapter, notifier, seen, alerted, clock, alert_types={"pickup"}, renotify=rn)
    assert len(notifier.sent) == 0


def test_renotify_respects_price_filter():
    clock = _Clock(1000.0)
    adapter = _FakeAdapter([_result(atype="preorder", price="$129.99")])
    notifier, seen, alerted = _FakeNotifier(), {}, {}
    pf = PriceFilter(enabled=True, max_over_msrp=1.25, msrp_map={"123": 49.99})
    rn = Renotify(interval_seconds=600, types=WINNABLE)

    _run(adapter, notifier, seen, alerted, clock, price_filter=pf, renotify=rn)
    clock.t += 700
    _run(adapter, notifier, seen, alerted, clock, price_filter=pf, renotify=rn)
    assert len(notifier.sent) == 0            # over-MSRP never alerts, even on re-notify


def test_no_renotify_is_once_only():
    clock = _Clock(1000.0)
    adapter, notifier = _FakeAdapter([_result(atype="preorder")]), _FakeNotifier()
    seen, alerted = {}, {}

    # renotify=None preserves the original single-shot behavior.
    _run(adapter, notifier, seen, alerted, clock, renotify=None)
    clock.t += 100_000
    _run(adapter, notifier, seen, alerted, clock, renotify=None)
    assert len(notifier.sent) == 1


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
