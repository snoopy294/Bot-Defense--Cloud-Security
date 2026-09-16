"""Notification sinks: ntfy push, Discord webhook, and email (SMTP).

A Notifier fans a single StockResult out to whichever channels are enabled.
Failures in one channel are logged and never abort the others.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import requests

from retailers.base import StockResult

log = logging.getLogger(__name__)


# Per-availability-type presentation. Preorder and in-store pickup are the lanes
# a regular buyer can realistically win (no millisecond restock race), so they're
# forced to ntfy "max" priority — the loudest, DND-overriding alert — and given
# distinct emoji/headline/color so they stand out from online restocks at a glance.
_ALERT_STYLE = {
    "preorder": {
        "emoji": "📅", "headline": "PREORDER OPEN",
        "ntfy_priority": "max", "ntfy_tags": "calendar,rotating_light",
        "discord_color": 0x5865F2,  # blurple
    },
    "pickup": {
        "emoji": "🏬", "headline": "IN-STORE PICKUP",
        "ntfy_priority": "max", "ntfy_tags": "round_pushpin,rotating_light",
        "discord_color": 0xE67E22,  # orange
    },
    "online": {
        "emoji": "🛒", "headline": "IN STOCK ONLINE",
        "ntfy_priority": None,  # use the configured ntfy priority (default urgent)
        "ntfy_tags": "shopping_cart",
        "discord_color": 0x57F287,  # green
    },
}


def _style(r: StockResult) -> dict:
    return _ALERT_STYLE.get(r.availability_type, _ALERT_STYLE["online"])


class Notifier:
    def __init__(self, cfg: dict, session: requests.Session):
        self.cfg = cfg or {}
        self.session = session

    def send(self, r: StockResult, *, skip_channels=()) -> dict[str, bool]:
        """Return delivery outcomes; retries can skip already delivered channels."""
        outcomes = {}
        ntfy = self.cfg.get("ntfy", {})
        if ntfy.get("enabled") and ntfy.get("topic"):
            outcomes["ntfy"] = "ntfy" in skip_channels
            try:
                if not outcomes["ntfy"]:
                    self._ntfy(ntfy, r)
                    outcomes["ntfy"] = True
            except Exception as e:  # noqa: BLE001
                log.warning("ntfy notify failed: %s", e)

        disc = self.cfg.get("discord", {})
        if disc.get("enabled") and disc.get("webhook_url"):
            outcomes["discord"] = "discord" in skip_channels
            try:
                if not outcomes["discord"]:
                    self._discord(disc["webhook_url"], r)
                    outcomes["discord"] = True
            except Exception as e:  # noqa: BLE001
                log.warning("discord notify failed: %s", e)

        email = self.cfg.get("email", {})
        if email.get("enabled"):
            outcomes["email"] = "email" in skip_channels
            try:
                if not outcomes["email"]:
                    self._email(email, r)
                    outcomes["email"] = True
            except Exception as e:  # noqa: BLE001
                log.warning("email notify failed: %s", e)
        return outcomes

    def heartbeat(self, watching: int) -> None:
        """Send a low-priority 'still alive' ping via ntfy, if enabled."""
        ntfy = self.cfg.get("ntfy", {})
        if not (ntfy.get("enabled") and ntfy.get("topic")):
            return
        try:
            server = ntfy.get("server", "https://ntfy.sh").rstrip("/")
            self.session.post(
                f"{server}/{ntfy['topic']}",
                data=f"monitor alive — watching {watching} item(s)".encode("utf-8"),
                headers={"Title": "Pokemon monitor heartbeat", "Priority": "min", "Tags": "heartbeat"},
                timeout=15,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("heartbeat ping failed: %s", e)

    def _line(self, r: StockResult) -> str:
        price = f" — {r.price}" if r.price else ""
        return f"{r.label}: {r.name}{price} [{r.retailer}]\n{r.url}"

    def _headline(self, r: StockResult, style: dict) -> str:
        """Headline text, with the store appended for in-store pickup."""
        head = style["headline"]
        if r.availability_type == "pickup" and r.store:
            head = f"{head} @ {r.store}"
        return head

    def _ntfy(self, cfg: dict, r: StockResult) -> None:
        server = cfg.get("server", "https://ntfy.sh").rstrip("/")
        style = _style(r)
        price = f" — {r.price}" if r.price else ""
        # Preorder/pickup force "max"; online uses the configured priority.
        # urgent/max override silent mode on the phone.
        priority = style["ntfy_priority"] or cfg.get("priority", "urgent")
        headers = {
            "Title": f"{style['emoji']} {self._headline(r, style)} · {r.retailer}",
            "Priority": str(priority),
            "Tags": style["ntfy_tags"],
            "Click": r.url,           # tapping the notification opens the buy link
        }
        body = f"{r.name}{price}\n{r.url}"
        resp = self.session.post(
            f"{server}/{cfg['topic']}",
            data=body.encode("utf-8"),
            headers={k: v.encode("utf-8") if isinstance(v, str) else v for k, v in headers.items()},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("ntfy alert sent for %s (priority=%s)", r.key, priority)

    def _discord(self, webhook_url: str, r: StockResult) -> None:
        style = _style(r)
        price = f" — {r.price}" if r.price else ""
        # Color-coded embed so preorder (blue) / pickup (orange) / online (green)
        # are distinguishable at a glance in the channel.
        embed = {
            "title": f"{style['emoji']} {self._headline(r, style)} — {r.retailer}",
            "description": f"**{r.name}**{price}",
            "url": r.url,
            "color": style["discord_color"],
        }
        resp = self.session.post(webhook_url, json={"embeds": [embed]}, timeout=15)
        resp.raise_for_status()
        log.info("discord alert sent for %s", r.key)

    def _email(self, cfg: dict, r: StockResult) -> None:
        from_addr = cfg.get("from_addr")
        to_addrs = cfg.get("to_addrs")
        smtp_host = cfg.get("smtp_host")
        missing = [
            name for name, val in
            (("smtp_host", smtp_host), ("from_addr", from_addr), ("to_addrs", to_addrs))
            if not val
        ]
        if missing:
            raise ValueError("email misconfigured: missing " + ", ".join(missing))

        msg = EmailMessage()
        msg["Subject"] = f"{self._headline(r, _style(r))}: {r.name} ({r.retailer})"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(self._line(r))

        with smtplib.SMTP(smtp_host, int(cfg.get("smtp_port", 587)), timeout=20) as s:
            if cfg.get("use_tls", True):
                s.starttls()
            if cfg.get("username"):
                s.login(cfg["username"], cfg.get("password", ""))
            s.send_message(msg)
        log.info("email alert sent for %s", r.key)
