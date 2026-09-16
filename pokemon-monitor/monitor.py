"""Pokemon stock-notification monitor.

Polls configured retailers for product availability and alerts you (ntfy push,
Discord, email) when an item flips from unavailable to available — online,
in-store pickup, or preorder. It then leaves you to go buy it yourself. It does
NOT add to cart, check out, or evade bot protection.

Usage:
    python monitor.py                 # uses ./config.yaml
    python monitor.py my.yaml         # custom config path
    python monitor.py --once          # run a single cycle and exit (testing)
    python monitor.py --test-notify   # send a dummy alert to all channels
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import random
import sys
import time
from dataclasses import dataclass

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import state
from notify import Notifier
from pricefilter import PriceFilter
from retailers import ADAPTERS
from retailers.base import StockResult

log = logging.getLogger("monitor")


@dataclass
class Renotify:
    """Re-notify policy: re-alert still-available items in these lanes."""

    interval_seconds: float
    types: set  # availability types eligible for reminders (e.g. preorder/pickup)


def setup_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        # Rotating file handler keeps 24/7 logs from growing without bound.
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    # Centralized retry: transient network blips and 5xx/429 get retried with
    # exponential backoff, honoring Retry-After. Benefits every adapter.
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def make_transport(cfg: dict, session: requests.Session):
    """Return the HTTP transport adapters should use.

    Default is the plain `requests` session. If `browser.enabled` is set, return
    a persistent-Chromium transport instead — it has Chrome's real TLS
    fingerprint and runs JS challenges, so it gets past Cloudflare/Akamai bot
    checks that 403 a plain client. Notifications always stay on `requests`.
    """
    bcfg = cfg.get("browser") or {}
    if not bcfg.get("enabled"):
        return session
    from retailers.transport import BrowserTransport

    return BrowserTransport(
        user_data_dir=bcfg.get("user_data_dir", "browser_data"),
        headless=bool(bcfg.get("headless", True)),
        user_agent=cfg.get("user_agent") if bcfg.get("use_config_user_agent") else None,
    )


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Required config keys per enabled retailer / notification channel.
_RETAILER_REQUIRED = {
    "bestbuy": ["api_key", "skus"],
    "target": ["tcins"],
    "walmart": ["item_ids"],
    "pokemoncenter": ["urls"],
    "costco": ["urls"],
    "gamestop": ["urls"],
}
_NOTIFY_REQUIRED = {
    "email": ["smtp_host", "from_addr", "to_addrs"],
    "discord": ["webhook_url"],
    "ntfy": ["topic"],
}


def validate_config(cfg) -> list[str]:
    """Return a list of human-readable config problems (empty list == valid)."""
    problems: list[str] = []

    if not isinstance(cfg, dict) or not cfg:
        return ["config is empty or not a mapping (copy config.example.yaml)"]

    # Numeric settings must be int-coercible.
    for field, default in (("poll_interval_seconds", 90), ("jitter_seconds", 30),
                           ("heartbeat_minutes", 0)):
        try:
            int(cfg.get(field, default))
        except (TypeError, ValueError):
            problems.append(f"{field} must be a number, got {cfg.get(field)!r}")

    # Re-notify interval, when present, must be int-coercible too.
    rn = cfg.get("renotify")
    if isinstance(rn, dict) and "interval_minutes" in rn:
        try:
            int(rn["interval_minutes"])
        except (TypeError, ValueError):
            problems.append(
                f"renotify.interval_minutes must be a number, got {rn['interval_minutes']!r}"
            )

    # At least one enabled retailer, each with its required keys present.
    retailers = cfg.get("retailers") or {}
    enabled = {k: v for k, v in retailers.items() if isinstance(v, dict) and v.get("enabled")}
    if not enabled:
        problems.append("no enabled retailers in config")
    for key, rcfg in enabled.items():
        if key not in ADAPTERS:
            problems.append(f"unknown retailer: {key}")
            continue
        for req in _RETAILER_REQUIRED.get(key, []):
            if not rcfg.get(req):
                problems.append(f"retailer '{key}' is enabled but missing '{req}'")

    # Enabled notification channels must carry their required keys.
    notifications = cfg.get("notifications") or {}
    for chan, ccfg in notifications.items():
        if not (isinstance(ccfg, dict) and ccfg.get("enabled")):
            continue
        for req in _NOTIFY_REQUIRED.get(chan, []):
            if not ccfg.get(req):
                problems.append(f"notification '{chan}' is enabled but missing '{req}'")
        if chan == "email" and ccfg.get("username") and not ccfg.get("password"):
            problems.append("notification 'email' has a username but no password")

    return problems


def build_adapters(cfg: dict, session: requests.Session) -> list:
    adapters = []
    for key, rcfg in (cfg.get("retailers") or {}).items():
        if not rcfg or not rcfg.get("enabled"):
            continue
        cls = ADAPTERS.get(key)
        if not cls:
            log.warning("unknown retailer in config: %s", key)
            continue
        adapters.append(cls(rcfg, session))
    return adapters


def run_cycle(adapters: list, notifier: Notifier, seen: dict, alerted: dict,
              alert_types: set | None = None,
              price_filter: PriceFilter | None = None,
              renotify: Renotify | None = None,
              deliveries: dict | None = None) -> None:
    if deliveries is None:
        deliveries = {}
    now = time.time()
    for adapter in adapters:
        if adapter.paused:
            remaining = int(adapter.paused_until - time.time())
            log.info("%-12s (cooling down %ds, skipped)", adapter.name, remaining)
            continue
        for r in adapter.check():
            status = r.label if r.in_stock else "out"
            log.info("%-12s %-18s %s", r.retailer, status, r.name)
            # Alert on the unavailable -> available transition so you're not
            # spammed every cycle. An optional alert_types filter focuses on the
            # winnable lanes (preorder/pickup); the price filter drops
            # scalper-priced listings (fails open on unknown/unparseable prices).
            # Re-notify then re-pings a still-available preorder/pickup once the
            # interval has elapsed, so a missed first alert doesn't cost the drop.
            wanted = alert_types is None or r.availability_type in alert_types
            priced_ok = price_filter is None or price_filter.allows(r)
            if r.in_stock and wanted and priced_ok:
                first_time = r.key not in alerted
                due = (
                    renotify is not None
                    and r.availability_type in renotify.types
                    and (now - alerted.get(r.key, 0.0)) >= renotify.interval_seconds
                )
                if first_time or due or r.key in deliveries:
                    outcomes = notifier.send(r, skip_channels=deliveries.get(r.key, []))
                    if outcomes and all(outcomes.values()):
                        alerted[r.key] = now
                        deliveries.pop(r.key, None)
                    else:
                        deliveries[r.key] = [channel for channel, ok in outcomes.items() if ok]
            if not r.in_stock:
                # Reset the alert clock so the NEXT restock alerts immediately.
                alerted.pop(r.key, None)
                deliveries.pop(r.key, None)
            seen[r.key] = r.in_stock


def main() -> int:
    parser = argparse.ArgumentParser(description="Pokemon stock-notification monitor")
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument(
        "--test-notify", action="store_true",
        help="send a dummy alert to all enabled channels and exit",
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        logging.basicConfig(level=logging.INFO)
        log.error("config not found: %s (copy config.example.yaml to config.yaml)", args.config)
        return 1
    except yaml.YAMLError as e:
        logging.basicConfig(level=logging.INFO)
        log.error("config %s is not valid YAML: %s", args.config, e)
        return 1

    problems = validate_config(cfg)
    if problems:
        logging.basicConfig(level=logging.INFO)
        log.error("config %s has %d problem(s):", args.config, len(problems))
        for p in problems:
            log.error("  - %s", p)
        return 1

    setup_logging(cfg.get("log_file"))

    session = make_session(cfg.get("user_agent", "pokemon-stock-monitor/1.0"))
    notifier = Notifier(cfg.get("notifications", {}), session)  # always plain requests

    if args.test_notify:
        log.info("sending one test notification per availability type...")
        for atype, note in (
            ("preorder", "Preorder test — should be LOUD (max priority)"),
            ("pickup", "Pickup test — should be LOUD (max priority)"),
            ("online", "Online test — your monitor notifications work!"),
        ):
            notifier.send(
                StockResult(
                    retailer="test",
                    product_id="0",
                    name=note,
                    in_stock=True,
                    price="$0.00",
                    url="https://example.com/test",
                    availability_type=atype,
                    store="Target Plano West" if atype == "pickup" else None,
                )
            )
        return 0

    transport = make_transport(cfg, session)
    adapters = build_adapters(cfg, transport)
    if not adapters:
        log.error("no enabled retailers in config; nothing to do")
        return 1

    state_file = cfg.get("state_file", "monitor_state.json")
    st = state.load(state_file)
    seen, alerted, deliveries = st["seen"], st["alerted"], st["deliveries"]

    interval = int(cfg.get("poll_interval_seconds", 90))
    jitter = int(cfg.get("jitter_seconds", 30))
    heartbeat_minutes = int(cfg.get("heartbeat_minutes", 0))
    next_heartbeat = time.time() + heartbeat_minutes * 60 if heartbeat_minutes else None

    # Optional focus: only alert for these availability types (empty/absent = all).
    alert_types = set(cfg.get("alert_types") or []) or None

    # Optional price-gouging filter: only alert when price is close to MSRP.
    pf_cfg = cfg.get("price_filter") or {}
    price_filter = PriceFilter(
        enabled=bool(pf_cfg.get("enabled")),
        max_over_msrp=pf_cfg.get("max_over_msrp", 1.25),
        msrp_map=pf_cfg.get("msrp") or {},
    )

    # Optional re-notify reminders: re-alert a still-available item in the
    # winnable lanes every interval_minutes (online is excluded to avoid spam).
    rn_cfg = cfg.get("renotify") or {}
    renotify = None
    if rn_cfg.get("enabled"):
        rn_types = set(rn_cfg.get("types") or ["preorder", "pickup"])
        renotify = Renotify(
            interval_seconds=int(rn_cfg.get("interval_minutes", 10)) * 60,
            types=rn_types,
        )

    log.info(
        "watching %d retailer(s); polling ~every %ds; alerting on %s",
        len(adapters), interval, ", ".join(sorted(alert_types)) if alert_types else "all types",
    )
    if price_filter.enabled:
        log.info(
            "price filter on: alerting only up to %.0f%% of MSRP for %d priced item(s)",
            price_filter.max_over_msrp * 100, len(price_filter.msrp_map),
        )
    if renotify:
        log.info(
            "re-notify on: re-alerting %s every %d min while still available",
            ", ".join(sorted(renotify.types)), renotify.interval_seconds // 60,
        )

    try:
        while True:
            try:
                run_cycle(adapters, notifier, seen, alerted, alert_types,
                          price_filter, renotify, deliveries)
                state.save(state_file, {"seen": seen, "alerted": alerted, "deliveries": deliveries})
            except Exception as e:  # noqa: BLE001 - keep the loop alive 24/7
                log.exception("cycle error: %s", e)

            if next_heartbeat and time.time() >= next_heartbeat:
                notifier.heartbeat(len(seen))
                next_heartbeat = time.time() + heartbeat_minutes * 60

            if args.once:
                return 0

            time.sleep(interval + random.uniform(0, jitter))
    finally:
        # Tear down the browser if we started one (no-op for the requests session).
        if hasattr(transport, "close"):
            transport.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped.")
