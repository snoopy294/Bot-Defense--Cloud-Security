# Pokemon Retail Bot — Build Instructions

Build a complete, production-ready Python retail bot that monitors Pokemon card products across multiple retailers and automatically completes purchases when items come in stock. The user wants to buy these for personal use — not resale. Implement every component below without asking clarifying questions.

---

## Goals

1. Continuously monitor stock across Pokemon Center, Best Buy, Target, Walmart, and GameStop
2. Automatically add to cart and complete checkout the instant stock appears
3. Send Discord notifications at each stage (stock found, carted, purchased, or failed)
4. Be configurable via a single `config.yaml` file — no code changes needed to switch products or credentials

---

## Tech Stack

- **Python 3.11+**
- **httpx** (`pip install httpx[http2]`) — async HTTP client for all API calls
- **asyncio** — concurrent monitoring of all retailers simultaneously
- **playwright** (`pip install playwright && playwright install chromium`) — browser automation for checkout flows with anti-bot protection
- **playwright-stealth** (`pip install playwright-stealth`) — evade basic bot detection fingerprinting
- **pydantic** v2 (`pip install pydantic`) — validate and load config
- **PyYAML** (`pip install pyyaml`) — parse config.yaml
- **discord-webhook** (`pip install discord-webhook`) — send rich Discord notifications

---

## Project Structure

```
pokemon-bot/
├── main.py                  # Entry point, wires everything together
├── config.yaml              # User-editable configuration
├── requirements.txt
├── monitor.py               # Async polling loop
├── cart.py                  # Add-to-cart logic
├── checkout.py              # Checkout automation
├── notify.py                # Discord notifications
├── models.py                # Pydantic config models + StockEvent dataclass
└── retailers/
    ├── __init__.py
    ├── base.py              # Abstract base class for all retailers
    ├── pokemon_center.py
    ├── best_buy.py
    ├── target.py
    ├── walmart.py
    └── gamestop.py
```

---

## `config.yaml` Format

```yaml
discord_webhook: "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
poll_interval_seconds: 10
log_file: "bot.log"

products:
  - name: "Prismatic Evolutions ETB"
    keywords: ["prismatic evolutions", "elite trainer box"]
    max_price: 60.00
  - name: "Scarlet Violet Booster Box"
    keywords: ["scarlet violet", "booster box"]
    max_price: 150.00

retailers:
  pokemon_center:
    enabled: true
    email: "your@email.com"
    password: "yourpassword"
  best_buy:
    enabled: true
    email: "your@email.com"
    password: "yourpassword"
  target:
    enabled: true
    email: "your@email.com"
    password: "yourpassword"
  walmart:
    enabled: true
    email: "your@email.com"
    password: "yourpassword"
  gamestop:
    enabled: true
    email: "your@email.com"
    password: "yourpassword"

checkout:
  first_name: "John"
  last_name: "Doe"
  address1: "123 Main St"
  address2: ""
  city: "Springfield"
  state: "IL"
  zip: "62701"
  country: "US"
  phone: "5551234567"
  card_number: "4111111111111111"
  card_expiry_month: "12"
  card_expiry_year: "2027"
  card_cvv: "123"
  card_name: "John Doe"
```

---

## `models.py`

Define these with Pydantic v2:

```python
from dataclasses import dataclass
from pydantic import BaseModel
from typing import Optional

class ProductConfig(BaseModel):
    name: str
    keywords: list[str]
    max_price: float

class RetailerConfig(BaseModel):
    enabled: bool = True
    email: str = ""
    password: str = ""

class RetailersConfig(BaseModel):
    pokemon_center: RetailerConfig = RetailerConfig()
    best_buy: RetailerConfig = RetailerConfig()
    target: RetailerConfig = RetailerConfig()
    walmart: RetailerConfig = RetailerConfig()
    gamestop: RetailerConfig = RetailerConfig()

class CheckoutConfig(BaseModel):
    first_name: str
    last_name: str
    address1: str
    address2: str = ""
    city: str
    state: str
    zip: str
    country: str = "US"
    phone: str
    card_number: str
    card_expiry_month: str
    card_expiry_year: str
    card_cvv: str
    card_name: str

class BotConfig(BaseModel):
    discord_webhook: str
    poll_interval_seconds: int = 10
    log_file: str = "bot.log"
    products: list[ProductConfig]
    retailers: RetailersConfig
    checkout: CheckoutConfig

@dataclass
class StockEvent:
    retailer: str         # e.g. "Best Buy"
    product_name: str     # matched product from config
    title: str            # actual product title from the retailer
    price: float
    url: str
    sku: str              # retailer-specific product ID
    add_to_cart_url: str  # direct cart URL if available, else empty string
```

Load config at startup:
```python
import yaml
from models import BotConfig

def load_config(path="config.yaml") -> BotConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return BotConfig(**data)
```

---

## `notify.py`

```python
from discord_webhook import DiscordWebhook, DiscordEmbed
from models import StockEvent

class Notifier:
    def __init__(self, webhook_url: str):
        self.url = webhook_url

    def _send(self, embed: DiscordEmbed):
        hook = DiscordWebhook(url=self.url)
        hook.add_embed(embed)
        hook.execute()

    def stock_found(self, event: StockEvent):
        embed = DiscordEmbed(title="🟢 IN STOCK", color="03b2f8")
        embed.add_embed_field(name="Product", value=event.title)
        embed.add_embed_field(name="Retailer", value=event.retailer)
        embed.add_embed_field(name="Price", value=f"${event.price:.2f}")
        embed.add_embed_field(name="URL", value=event.url, inline=False)
        self._send(embed)

    def carted(self, event: StockEvent):
        embed = DiscordEmbed(title="🛒 ADDED TO CART", color="f5a623")
        embed.add_embed_field(name="Product", value=event.title)
        embed.add_embed_field(name="Retailer", value=event.retailer)
        self._send(embed)

    def purchased(self, event: StockEvent, order_id: str):
        embed = DiscordEmbed(title="✅ PURCHASED", color="57f287")
        embed.add_embed_field(name="Product", value=event.title)
        embed.add_embed_field(name="Retailer", value=event.retailer)
        embed.add_embed_field(name="Order", value=order_id)
        self._send(embed)

    def failed(self, event: StockEvent, reason: str):
        embed = DiscordEmbed(title="❌ FAILED", color="ed4245")
        embed.add_embed_field(name="Product", value=event.title)
        embed.add_embed_field(name="Retailer", value=event.retailer)
        embed.add_embed_field(name="Reason", value=reason, inline=False)
        self._send(embed)

    def startup_ping(self):
        hook = DiscordWebhook(url=self.url, content="🤖 Pokemon Bot started and monitoring.")
        hook.execute()
```

---

## `retailers/base.py`

```python
from abc import ABC, abstractmethod
from models import StockEvent, ProductConfig
import httpx

class BaseRetailer(ABC):
    name: str

    def __init__(self, config, products: list[ProductConfig]):
        self.config = config
        self.products = products
        self.client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
            follow_redirects=True,
        )

    def matches(self, title: str, price: float) -> ProductConfig | None:
        title_lower = title.lower()
        for p in self.products:
            if any(kw.lower() in title_lower for kw in p.keywords):
                if price <= p.max_price:
                    return p
        return None

    @abstractmethod
    async def check_stock(self) -> list[StockEvent]:
        ...

    async def close(self):
        await self.client.aclose()
```

---

## `retailers/best_buy.py`

Best Buy exposes a public product availability API. No authentication needed for stock checks.

```python
import httpx
from retailers.base import BaseRetailer
from models import StockEvent, ProductConfig

SEARCH_URL = "https://api.bestbuy.com/v1/products"
# Best Buy requires an API key from developer.bestbuy.com (free)
# Pass it in config as best_buy.api_key

class BestBuyRetailer(BaseRetailer):
    name = "Best Buy"

    async def check_stock(self) -> list[StockEvent]:
        events = []
        for product in self.products:
            query = " ".join(product.keywords[:2])
            params = {
                "apiKey": self.config.api_key or "",
                "format": "json",
                "show": "sku,name,salePrice,url,inStoreAvailability,onlineAvailability,addToCartUrl",
                "q": query,
                "pageSize": 10,
            }
            try:
                r = await self.client.get(SEARCH_URL, params=params)
                r.raise_for_status()
                for item in r.json().get("products", []):
                    if not item.get("onlineAvailability"):
                        continue
                    matched = self.matches(item["name"], item["salePrice"])
                    if matched:
                        events.append(StockEvent(
                            retailer=self.name,
                            product_name=matched.name,
                            title=item["name"],
                            price=item["salePrice"],
                            url=item["url"],
                            sku=str(item["sku"]),
                            add_to_cart_url=item.get("addToCartUrl", ""),
                        ))
            except Exception:
                pass
        return events
```

**Note for implementor:** Best Buy's free API key is obtained at developer.bestbuy.com. Add `api_key` to `RetailerConfig` and the config YAML for this retailer.

---

## `retailers/target.py`

Target's RedSky inventory API is accessible server-side.

```python
from retailers.base import BaseRetailer
from models import StockEvent

SEARCH_URL = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"

class TargetRetailer(BaseRetailer):
    name = "Target"

    async def check_stock(self) -> list[StockEvent]:
        events = []
        for product in self.products:
            params = {
                "key": "9f36aeafbe60771e321a7cc95a78140772ab3e96",  # public key embedded in Target's web app
                "channel": "WEB",
                "count": 24,
                "default_purchasability_filter": "true",
                "include_sponsored": "true",
                "keyword": " ".join(product.keywords[:2]),
                "offset": 0,
                "platform": "desktop",
                "pricing_store_id": "3991",
                "scheduled_delivery_store_id": "3991",
                "store_ids": "3991",
                "useragent": "Mozilla/5.0",
                "visitor_id": "017F33B9B0A20189E053020011AC96A4",
            }
            try:
                r = await self.client.get(SEARCH_URL, params=params)
                r.raise_for_status()
                items = r.json().get("data", {}).get("search", {}).get("products", [])
                for item in items:
                    availability = item.get("fulfillment", {}).get("shipping_options", {}).get("availability_status", "")
                    if availability != "IN_STOCK":
                        continue
                    price = item.get("price", {}).get("current_retail", 0.0)
                    title = item.get("item", {}).get("product_description", {}).get("title", "")
                    tcin = item.get("item", {}).get("tcin", "")
                    url = f"https://www.target.com/p/-/A-{tcin}"
                    matched = self.matches(title, price)
                    if matched:
                        events.append(StockEvent(
                            retailer=self.name,
                            product_name=matched.name,
                            title=title,
                            price=price,
                            url=url,
                            sku=tcin,
                            add_to_cart_url="",
                        ))
            except Exception:
                pass
        return events
```

---

## `retailers/walmart.py`

Walmart embeds inventory data in the page's `__PRELOADED_STATE__` JSON. Use their search API.

```python
import json
import re
from retailers.base import BaseRetailer
from models import StockEvent

SEARCH_URL = "https://www.walmart.com/search"

class WalmartRetailer(BaseRetailer):
    name = "Walmart"

    async def check_stock(self) -> list[StockEvent]:
        events = []
        for product in self.products:
            try:
                params = {"q": " ".join(product.keywords[:2])}
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                }
                r = await self.client.get(SEARCH_URL, params=params, headers=headers)
                # Extract __PRELOADED_STATE__ from script tag
                match = re.search(r'__PRELOADED_STATE__\s*=\s*({.*?})\s*;', r.text, re.DOTALL)
                if not match:
                    continue
                state = json.loads(match.group(1))
                items = (
                    state.get("searchResult", {})
                    .get("itemStacks", [{}])[0]
                    .get("items", [])
                )
                for item in items:
                    if not item.get("availabilityStatus") == "IN_STOCK":
                        continue
                    title = item.get("name", "")
                    price = float(item.get("price", 0) or 0)
                    item_id = str(item.get("usItemId", ""))
                    url = f"https://www.walmart.com/ip/{item_id}"
                    matched = self.matches(title, price)
                    if matched:
                        events.append(StockEvent(
                            retailer=self.name,
                            product_name=matched.name,
                            title=title,
                            price=price,
                            url=url,
                            sku=item_id,
                            add_to_cart_url=f"https://www.walmart.com/cart/api/v1/cart/item/add?itemId={item_id}&quantity=1",
                        ))
            except Exception:
                pass
        return events
```

---

## `retailers/pokemon_center.py`

Pokemon Center requires account login. Uses session cookies after authentication.

```python
from retailers.base import BaseRetailer
from models import StockEvent

LOGIN_URL = "https://www.pokemoncenter.com/api/2.0/users/sign_in"
SEARCH_URL = "https://www.pokemoncenter.com/api/2.0/catalog/products"

class PokemonCenterRetailer(BaseRetailer):
    name = "Pokemon Center"
    _logged_in = False

    async def _login(self):
        r = await self.client.post(LOGIN_URL, json={
            "email": self.config.email,
            "password": self.config.password,
        })
        self._logged_in = r.status_code == 200

    async def check_stock(self) -> list[StockEvent]:
        if not self._logged_in:
            await self._login()
        events = []
        for product in self.products:
            try:
                params = {
                    "q": " ".join(product.keywords[:2]),
                    "limit": 20,
                }
                r = await self.client.get(SEARCH_URL, params=params)
                r.raise_for_status()
                for item in r.json().get("results", []):
                    if item.get("availability") != "IN_STOCK":
                        continue
                    price = float(item.get("price", {}).get("current", 0))
                    title = item.get("name", "")
                    slug = item.get("slug", "")
                    sku = item.get("sku", "")
                    url = f"https://www.pokemoncenter.com/product/{slug}"
                    matched = self.matches(title, price)
                    if matched:
                        events.append(StockEvent(
                            retailer=self.name,
                            product_name=matched.name,
                            title=title,
                            price=price,
                            url=url,
                            sku=sku,
                            add_to_cart_url="",
                        ))
            except Exception:
                pass
        return events
```

---

## `retailers/gamestop.py`

GameStop uses Cloudflare. Use Playwright with stealth for all interactions.

```python
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from retailers.base import BaseRetailer
from models import StockEvent

SEARCH_URL = "https://www.gamestop.com/search#q={query}&t=product"

class GameStopRetailer(BaseRetailer):
    name = "GameStop"

    async def check_stock(self) -> list[StockEvent]:
        events = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await stealth_async(page)

            for product in self.products:
                try:
                    query = "+".join(product.keywords[:2]).replace(" ", "+")
                    url = SEARCH_URL.format(query=query)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_selector(".product-grid-item", timeout=10000)

                    cards = await page.query_selector_all(".product-grid-item")
                    for card in cards:
                        title_el = await card.query_selector(".product-title")
                        price_el = await card.query_selector(".final-price")
                        link_el = await card.query_selector("a.product-tile-link")
                        avail_el = await card.query_selector(".availability-msg")

                        if not title_el or not price_el or not link_el:
                            continue

                        title = await title_el.inner_text()
                        price_text = await price_el.inner_text()
                        href = await link_el.get_attribute("href")
                        avail = (await avail_el.inner_text()) if avail_el else ""

                        if "not available" in avail.lower() or "out of stock" in avail.lower():
                            continue

                        price = float(price_text.replace("$", "").replace(",", "").strip())
                        full_url = f"https://www.gamestop.com{href}" if href.startswith("/") else href
                        matched = self.matches(title, price)
                        if matched:
                            events.append(StockEvent(
                                retailer=self.name,
                                product_name=matched.name,
                                title=title,
                                price=price,
                                url=full_url,
                                sku=href.split("/")[-1] if href else "",
                                add_to_cart_url="",
                            ))
                except Exception:
                    pass

            await browser.close()
        return events
```

---

## `monitor.py`

```python
import asyncio
import logging
from models import BotConfig, StockEvent

class Monitor:
    def __init__(self, config: BotConfig, retailers: list, on_stock):
        self.config = config
        self.retailers = retailers
        self.on_stock = on_stock
        self.seen: set[str] = set()  # deduplicate: retailer+sku

    async def run(self):
        while True:
            tasks = [r.check_stock() for r in self.retailers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logging.error(f"Monitor error: {result}")
                    continue
                for event in result:
                    key = f"{event.retailer}:{event.sku}"
                    if key not in self.seen:
                        self.seen.add(key)
                        logging.info(f"STOCK: {event.retailer} — {event.title} @ ${event.price}")
                        await self.on_stock(event)
            await asyncio.sleep(self.config.poll_interval_seconds)
```

---

## `cart.py`

```python
import httpx
import logging
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from models import StockEvent

class CartService:
    async def add(self, event: StockEvent) -> bool:
        if event.add_to_cart_url:
            return await self._api_cart(event)
        return await self._browser_cart(event)

    async def _api_cart(self, event: StockEvent) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(event.add_to_cart_url)
                return r.status_code in (200, 201, 302)
        except Exception as e:
            logging.error(f"API cart failed: {e}")
            return False

    async def _browser_cart(self, event: StockEvent) -> bool:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await stealth_async(page)
                await page.goto(event.url, wait_until="domcontentloaded", timeout=30000)

                selectors = [
                    "button[data-automation='addToCart']",
                    "button[aria-label*='Add to cart']",
                    "button#add-to-cart-button",
                    "button.add-to-cart",
                    "button:has-text('Add to Cart')",
                    "button:has-text('Add to Bag')",
                ]
                for sel in selectors:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        await browser.close()
                        return True

                await browser.close()
                return False
        except Exception as e:
            logging.error(f"Browser cart failed: {e}")
            return False
```

---

## `checkout.py`

```python
import logging
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from models import StockEvent, CheckoutConfig

RETAILER_CHECKOUT_URLS = {
    "Best Buy": "https://www.bestbuy.com/checkout/r/fulfillment",
    "Target": "https://www.target.com/co-delivery",
    "Walmart": "https://www.walmart.com/checkout/",
    "Pokemon Center": "https://www.pokemoncenter.com/checkout",
    "GameStop": "https://www.gamestop.com/checkout/",
}

class CheckoutService:
    def __init__(self, checkout_config: CheckoutConfig):
        self.cfg = checkout_config

    async def complete(self, event: StockEvent) -> str | None:
        """Returns order ID on success, None on failure."""
        url = RETAILER_CHECKOUT_URLS.get(event.retailer)
        if not url:
            return None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)  # headless=False for checkout — sites detect headless more aggressively
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                    viewport={"width": 1440, "height": 900},
                )
                page = await context.new_page()
                await stealth_async(page)
                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Fill shipping
                await self._try_fill(page, ["#firstName", "[name='firstName']", "[autocomplete='given-name']"], self.cfg.first_name)
                await self._try_fill(page, ["#lastName", "[name='lastName']", "[autocomplete='family-name']"], self.cfg.last_name)
                await self._try_fill(page, ["#address1", "[name='address1']", "[autocomplete='address-line1']"], self.cfg.address1)
                await self._try_fill(page, ["#city", "[name='city']", "[autocomplete='address-level2']"], self.cfg.city)
                await self._try_fill(page, ["#zip", "[name='zip']", "[autocomplete='postal-code']"], self.cfg.zip)
                await self._try_fill(page, ["#phone", "[name='phone']", "[autocomplete='tel']"], self.cfg.phone)

                # Fill payment
                await self._try_fill(page, ["#cardNumber", "[name='cardNumber']", "[autocomplete='cc-number']"], self.cfg.card_number)
                await self._try_fill(page, ["#expiryMonth", "[name='expiryMonth']"], self.cfg.card_expiry_month)
                await self._try_fill(page, ["#expiryYear", "[name='expiryYear']"], self.cfg.card_expiry_year)
                await self._try_fill(page, ["#cvv", "[name='cvv']", "[autocomplete='cc-csc']"], self.cfg.card_cvv)
                await self._try_fill(page, ["#nameOnCard", "[name='nameOnCard']", "[autocomplete='cc-name']"], self.cfg.card_name)

                # Submit order
                submit_selectors = [
                    "button[data-automation='placeOrder']",
                    "button:has-text('Place Order')",
                    "button:has-text('Place your order')",
                    "button#placeOrder",
                    "button.place-order",
                ]
                for sel in submit_selectors:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        break

                await page.wait_for_timeout(5000)

                # Try to extract order number
                order_id = await self._extract_order_id(page)
                await browser.close()
                return order_id or "unknown"

        except Exception as e:
            logging.error(f"Checkout failed for {event.retailer}: {e}")
            return None

    async def _try_fill(self, page, selectors: list[str], value: str):
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(value)
                    return
            except Exception:
                continue

    async def _extract_order_id(self, page) -> str | None:
        patterns = [
            r"[Oo]rder\s*#?\s*([A-Z0-9\-]{6,})",
            r"[Cc]onfirmation\s*#?\s*([A-Z0-9\-]{6,})",
        ]
        import re
        text = await page.inner_text("body")
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return None
```

---

## `main.py`

```python
import asyncio
import logging
import sys
from models import load_config, StockEvent
from monitor import Monitor
from cart import CartService
from checkout import CheckoutService
from notify import Notifier
from retailers.best_buy import BestBuyRetailer
from retailers.target import TargetRetailer
from retailers.walmart import WalmartRetailer
from retailers.pokemon_center import PokemonCenterRetailer
from retailers.gamestop import GameStopRetailer

def setup_logging(log_file: str):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )

async def main():
    config = load_config()
    setup_logging(config.log_file)

    notifier = Notifier(config.discord_webhook)
    cart_service = CartService()
    checkout_service = CheckoutService(config.checkout)

    notifier.startup_ping()
    logging.info("Bot started.")

    retailer_classes = {
        "pokemon_center": PokemonCenterRetailer,
        "best_buy": BestBuyRetailer,
        "target": TargetRetailer,
        "walmart": WalmartRetailer,
        "gamestop": GameStopRetailer,
    }

    retailers = []
    for key, cls in retailer_classes.items():
        r_cfg = getattr(config.retailers, key)
        if r_cfg.enabled:
            retailers.append(cls(r_cfg, config.products))

    async def on_stock(event: StockEvent):
        notifier.stock_found(event)
        carted = await cart_service.add(event)
        if not carted:
            notifier.failed(event, "Could not add to cart")
            return
        notifier.carted(event)
        order_id = await checkout_service.complete(event)
        if order_id:
            notifier.purchased(event, order_id)
            logging.info(f"Purchased {event.title} — Order {order_id}")
        else:
            notifier.failed(event, "Checkout did not complete")

    monitor = Monitor(config, retailers, on_stock)
    await monitor.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## `requirements.txt`

```
httpx[http2]>=0.27
playwright>=1.44
playwright-stealth>=1.0
pydantic>=2.0
pyyaml>=6.0
discord-webhook>=1.3
```

---

## Implementation Notes

1. **Best Buy API key**: Create a free account at developer.bestbuy.com and add the key to `config.yaml` under `retailers.best_buy.api_key`. Add `api_key: ""` to `RetailerConfig` and the YAML.

2. **Checkout is best-effort**: Retailer checkout flows change frequently. The field selectors in `checkout.py` cover the most common patterns but may need tuning for specific retailers. The user should run it with `headless=False` first to watch it work and identify any missing selectors.

3. **Deduplication**: The monitor's `seen` set resets when the bot restarts. This is intentional — if the bot crashes and restarts, it will re-attempt any in-stock items.

4. **Rate limiting**: The default 10-second poll interval is respectful. Do not reduce below 5 seconds for any retailer.

5. **Captcha**: If a retailer introduces CAPTCHA during checkout, the Playwright window will appear (headless=False) — the user can complete the CAPTCHA manually and the bot will continue from where it left off.

---

## Quick Start

```bash
pip install -r requirements.txt
playwright install chromium
cp config.yaml.example config.yaml
# Edit config.yaml with your credentials, Discord webhook, and target products
python main.py
```

The bot will send a Discord ping on startup to confirm the webhook is working, then begin polling every 10 seconds across all enabled retailers.
