# Pokémon Stock-Notification Monitor

Watches Best Buy, Target, Walmart, Pokémon Center, Costco, and GameStop for
Pokémon card stock — online, **in-store pickup**, and **preorders** — and pushes
an instant alert to your phone (ntfy), Discord, and email when something becomes
available. You then go buy it yourself, like a normal customer.

### What it does NOT do
- ❌ No auto-add-to-cart
- ❌ No auto-checkout / auto-purchase
- ❌ No CAPTCHA / Cloudflare / bot-detection evasion
- ❌ No browser stealth or fake browser fingerprints

It's a polite, read-only availability checker. The point is to *notify* you fast,
not to out-buy other shoppers automatically.

### The honest reality
For a true millisecond-sellout hype drop, no notify-only tool beats a checkout
bot. Your real wins come from: (1) the many restocks that sit for minutes — where
a fast phone alert + quick manual checkout absolutely works; (2) **in-store
pickup**, which bots can't grab; and (3) **MSRP preorders**, the sane way to get
product without racing. This tool is built around those three.

## Setup

```powershell
cd pokemon-monitor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

Then edit `config.yaml`:

1. **ntfy (phone push)** — install the ntfy app (iOS/Android), pick a **long
   random topic name**, set it in config, and subscribe to that same topic in the
   app. Public `ntfy.sh` topics are world-readable, so the random name *is* your
   privacy. (Or self-host ntfy and set `server`.)
2. **Best Buy** — free API key from <https://developer.bestbuy.com/>; add the
   **SKU**s you want. Set `check_stores: true` + your `zip`/`radius` for pickup.
3. **Target** — add each product's **TCIN** (from `/p/-/A-89542109`), plus a
   `store_id`, `zip`, and `radius` for nearby pickup.
4. **Walmart** — add the **item id** from the product URL (`/ip/.../12345678`).
5. **Pokémon Center / Costco / GameStop** — add product page **URLs**. These are
   best-effort (see caveat below).
6. **Discord / Email** — optional; webhook URL and/or Gmail
   [App Password](https://myaccount.google.com/apppasswords).

## Run

```powershell
python monitor.py --test-notify   # fire a dummy alert to verify all channels
python monitor.py --once          # one pass, to verify config/SKUs
python monitor.py                 # run continuously
```

You're alerted only when an item flips from unavailable → available (tracked
separately for online / pickup / preorder), so you won't be spammed every cycle.

## Run it 24/7 (Windows)

Install a scheduled task that auto-starts at logon and auto-restarts on crash:

```powershell
.\install-task.ps1                 # install
Start-ScheduledTask -TaskName PokemonStockMonitor
Get-ScheduledTask -TaskName PokemonStockMonitor | Get-ScheduledTaskInfo  # status
.\install-task.ps1 -Uninstall      # remove
```

Want it to run even before you log in? Install [NSSM](https://nssm.cc/) and:
`nssm install PokemonMonitor <path>\.venv\Scripts\pythonw.exe <path>\monitor.py`.

## Fast manual checkout checklist (your legit speed edge)

When the alert fires, every second counts. Set this up *ahead of time*:
- Be **logged in** to each retailer account in your phone browser/app.
- **Save your payment method + shipping/billing address** in each account.
- Keep the ntfy app allowed to send **urgent** notifications (overrides silent).
- Tapping the ntfy alert opens the product link directly — go straight to "Add to
  cart" → checkout. Pre-saved details turn that into a few taps.
- For pickup alerts, choose your store and reserve; for preorders, just order at
  MSRP — no race.

## Be a good citizen
- Keep `poll_interval_seconds` reasonable (60s+). Hammering endpoints gets your IP
  rate-limited or blocked — and that's the fair outcome. The monitor auto-backs-off
  for 10 min if a retailer returns HTTP 429.
- These sites' Terms of Service prohibit automated *purchasing*. This tool stays
  on the right side of that line by only reading availability and notifying you.

### Best-effort sources caveat
Pokémon Center, Costco, and GameStop have no public API here, so we read the
standard `schema.org` availability metadata embedded in their public product
pages. They run bot protection (Akamai/Cloudflare); when a request is blocked or a
page omits that metadata, the monitor **logs and skips** — it never tries to evade
protection. Best Buy (official API) and Target (RedSky) are the reliable sources.

## Layout
```
monitor.py            # main loop: retries, persistent state, heartbeat, alerts
notify.py             # ntfy + Discord + email senders
state.py              # persistent dedupe (survives restarts)
config.example.yaml   # copy to config.yaml
run.ps1               # venv-aware launcher (used by the scheduled task)
install-task.ps1      # install/remove the 24/7 Windows scheduled task
retailers/
  base.py             # adapter interface, StockResult, 429 cooldown
  jsonld.py           # shared schema.org availability parser
  bestbuy.py          # official Best Buy API (online + pickup + preorder)
  target.py           # public RedSky API (online + nearby pickup + preorder)
  walmart.py          # public product-page JSON (fragile)
  pokemoncenter.py    # best-effort product-page JSON-LD
  costco.py           # best-effort product-page JSON-LD
  gamestop.py         # best-effort product-page JSON-LD (preorders)
```
