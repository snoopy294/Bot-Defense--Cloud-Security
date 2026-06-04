"""Optional real-browser transport for retailer adapters.

Some retailers sit behind bot-mitigation CDNs (Cloudflare, Akamai) that
fingerprint the TLS handshake and require a JavaScript challenge to be solved
before any request is answered. A plain `requests` client fails those checks and
gets a 403. A *real* Chromium browser passes them naturally: it has Chrome's
genuine TLS fingerprint, runs the challenge JavaScript, and keeps the resulting
clearance cookies in a persistent profile.

This module wraps a persistent Playwright Chromium context behind the *same*
`.get()` interface the adapters already use against `requests.Session`, so it
drops in with no adapter changes. It is OFF by default and entirely opt-in via
the `browser:` block in config.

How a request is actually issued: we first land the browser on the retailer's
own site (so Akamai/Cloudflare JS runs and sets clearance cookies), then issue
the request as an *in-page* `fetch()`. That matters because retailer JSON APIs
(e.g. Target's redsky) reject a bare top-level navigation that carries no
Origin/Referer — they only answer a same-site XHR, which is how the retailer's
own front end calls them. `fetch()` returns the body for HTML pages too, so the
same path serves both API and page-scraping adapters.

Scope note: this beats fingerprint/JS checks on a single IP. It does NOT rotate
IPs, does NOT solve CAPTCHAs, and does NOT auto-purchase — it is a politeness-
respecting availability checker that simply looks like a real browser.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode, urlsplit

import requests
from requests.structures import CaseInsensitiveDict

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 15_000
# Pause after first landing on a site, to let bot-protection JS set its cookies.
_WARMUP_PAUSE_MS = 2_500

# In-page fetch run inside the real Chrome page: same TLS, cookies, Origin and
# Referer as the retailer's own site. Returns status + body + readable headers.
_FETCH_JS = """
async ({url, headers, timeoutMs}) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {headers, credentials: "include", signal: ctrl.signal});
    const body = await r.text();
    const hdrs = {};
    r.headers.forEach((v, k) => { hdrs[k] = v; });
    return {status: r.status, body, headers: hdrs};
  } catch (e) {
    return {status: 0, body: String(e), headers: {}};
  } finally {
    clearTimeout(timer);
  }
}
"""


class BrowserResponse:
    """Adapts an in-page fetch result to the slice of the `requests.Response`
    API the adapters and base `_get()` rely on: `.status_code`, `.headers`
    (case-insensitive `.get`), `.json()`, `.text`, `.raise_for_status()`.
    """

    def __init__(self, status: int, body: str, headers: dict, url: str):
        self.url = url
        self.status_code = status
        self._body = body
        self.headers = CaseInsensitiveDict(headers or {})

    def json(self):
        return json.loads(self._body)

    @property
    def text(self) -> str:
        return self._body

    def raise_for_status(self) -> None:
        # status 0 == the in-page fetch threw (network error / abort / timeout).
        if self.status_code == 0:
            raise requests.ConnectionError(f"browser fetch failed for {self.url}: {self._body[:200]}")
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: {self.url}")


class BrowserTransport:
    """A persistent Chromium context that quacks like `requests.Session.get`.

    One browser is launched for the life of the process and reused for every
    request — launching per-check would be slow and defeat cookie persistence.
    """

    def __init__(self, user_data_dir: str = "browser_data", headless: bool = True,
                 user_agent: str | None = None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover - import-time guard
            raise RuntimeError(
                "browser mode requires Playwright. Install it with:\n"
                "    pip install playwright\n"
                "    playwright install chromium"
            ) from e

        self._pw = sync_playwright().start()
        launch_kwargs = {"headless": headless}
        if user_agent:
            launch_kwargs["user_agent"] = user_agent
        # Persistent context => cookies / clearance tokens survive restarts.
        self._ctx = self._pw.chromium.launch_persistent_context(user_data_dir, **launch_kwargs)
        self._ctx.set_default_navigation_timeout(30_000)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._warmed: set[str] = set()  # sites we've already landed on this run
        log.info("[browser] persistent Chromium started (headless=%s)", headless)

    @staticmethod
    def _site(url: str) -> str:
        """Registrable site for a URL (last two host labels). redsky.target.com
        and www.target.com both map to 'target.com'."""
        host = urlsplit(url).hostname or ""
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    def _ensure_warm(self, url: str) -> None:
        """Make sure the page is parked on the retailer's site so an in-page
        fetch is same-site and the protection JS has run at least once."""
        site = self._site(url)
        if not site:
            return
        current = self._site(self._page.url) if self._page.url else ""
        if site in self._warmed and current == site:
            return
        try:
            self._page.goto(f"https://www.{site}/", wait_until="domcontentloaded", timeout=30_000)
            self._page.wait_for_timeout(_WARMUP_PAUSE_MS)
        except Exception as e:  # noqa: BLE001 - warm-up is best effort
            log.debug("[browser] warm-up for %s failed: %s", site, e)
        self._warmed.add(site)

    def get(self, url: str, params=None, timeout=None, headers=None, **_ignored):
        """Mirror `requests.Session.get(url, params=, timeout=, headers=)`.
        `timeout` is seconds (requests-style); converted to ms for the browser.
        """
        if params:
            query = urlencode({k: "" if v is None else str(v) for k, v in params.items()})
            url = f"{url}?{query}" if query else url
        self._ensure_warm(url)
        timeout_ms = int((timeout or 15) * 1000) or _DEFAULT_TIMEOUT_MS
        res = self._page.evaluate(
            _FETCH_JS,
            {"url": url, "headers": {k: str(v) for k, v in (headers or {}).items()},
             "timeoutMs": timeout_ms},
        )
        return BrowserResponse(res["status"], res["body"], res["headers"], url)

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()
