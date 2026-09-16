"""Delivery failures and price transitions must not silently suppress alerts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import state
from monitor import run_cycle
from notify import Notifier
from pricefilter import PriceFilter
from retailers.base import StockResult


class Adapter:
    paused = False

    def __init__(self, price="$49.99"):
        self.result = StockResult(retailer="test", product_id="123", name="ETB",
                                  in_stock=True, price=price, url="https://example.com",
                                  availability_type="online")

    def check(self):
        return [self.result]


def test_partial_delivery_retries_only_failed_channel_after_restart(tmp_path, monkeypatch):
    notifier = Notifier({"ntfy": {"enabled": True, "topic": "test"},
                         "discord": {"enabled": True, "webhook_url": "unused"}}, requests.Session())
    calls = []
    monkeypatch.setattr(notifier, "_ntfy", lambda *args: calls.append("ntfy"))

    def fail(*args):
        calls.append("discord-fail")
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(notifier, "_discord", fail)
    adapter = Adapter()
    st = {"seen": {}, "alerted": {}, "deliveries": {}}
    run_cycle([adapter], notifier, **st)
    assert st["alerted"] == {}
    assert st["deliveries"][adapter.result.key] == ["ntfy"]
    path = str(tmp_path / "state.json")
    state.save(path, st)
    st = state.load(path)
    monkeypatch.setattr(notifier, "_discord", lambda *args: calls.append("discord-ok"))
    run_cycle([adapter], notifier, **st)
    run_cycle([adapter], notifier, **st)
    assert calls == ["ntfy", "discord-fail", "discord-ok"]
    assert adapter.result.key in st["alerted"]
    assert st["deliveries"] == {}


def test_price_becomes_affordable_without_stock_transition(monkeypatch):
    notifier = Notifier({"ntfy": {"enabled": True, "topic": "test"}}, requests.Session())
    calls = []
    monkeypatch.setattr(notifier, "_ntfy", lambda *args: calls.append("sent"))
    adapter = Adapter("$129.99")
    seen, alerted = {}, {}
    price_filter = PriceFilter(enabled=True, max_over_msrp=1.25, msrp_map={"123": 49.99})
    run_cycle([adapter], notifier, seen, alerted, price_filter=price_filter)
    assert not calls
    adapter.result = Adapter("$49.99").result
    run_cycle([adapter], notifier, seen, alerted, price_filter=price_filter)
    run_cycle([adapter], notifier, seen, alerted, price_filter=price_filter)
    assert calls == ["sent"]


def test_misconfigured_email_is_not_success():
    notifier = Notifier({"email": {"enabled": True}}, requests.Session())
    assert notifier.send(Adapter().result) == {"email": False}
