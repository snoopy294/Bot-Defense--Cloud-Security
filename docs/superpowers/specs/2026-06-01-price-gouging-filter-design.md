# Price-Gouging Filter — Design

**Date:** 2026-06-01
**Status:** Approved

## Problem

The monitor alerts on any unavailable→available transition. For listings that
can carry inflated, scalper-style prices (marketplace sellers, third-party
listings), the user gets pinged for items priced far above MSRP that they would
never actually buy. We want to alert only when the price is "reasonable" —
close to MSRP.

## Goal

Suppress a restock alert when the item's price is well above its MSRP, while
never silently dropping a real restock we can't price-judge.

## Approach (chosen)

Per-product MSRP plus a tolerance multiplier, implemented as a **monitor-level
policy**. Retailer adapters stay pure availability lookups (per `base.py`'s
stated contract) and are **not modified**.

MSRP lives in a new top-level `price_filter` config block as an `id → MSRP`
map, keyed by the same id/URL the user already lists under each retailer. This
avoids changing the bare-list config format that all six adapters consume, so
no adapter code changes and no working adapter is put at risk.

### Config (all optional; absent = current behavior)

```yaml
price_filter:
  enabled: true
  max_over_msrp: 1.25        # alert only if price <= MSRP * 1.25
  msrp:                      # keyed by the id/URL listed under the retailer
    "1011206804": 49.99      # Prismatic Evolutions ETB
    "93954446": 26.99
    # items not listed here always alert (fail open)
```

## Components

### `pricefilter.py` (new, isolated unit)

- `parse_price(price: str | None) -> float | None`
  Parse a display price like `"$1,234.50"` to a float. Returns `None` for
  `None`, empty, or unparseable input.
- `PriceFilter(enabled, max_over_msrp, msrp_map)`
  - `.cap_for(product_id) -> float | None` — `MSRP * max_over_msrp`, or `None`
    if no MSRP is known for that id.
  - `.allows(StockResult) -> bool` — the alert decision.

### `monitor.py` (wiring only)

- `run_cycle(...)` gains a `price_filter` parameter; the alert guard becomes
  `r.in_stock and not was and wanted and price_filter.allows(r)`.
- `main()` builds the `PriceFilter` from `cfg["price_filter"]` and passes it in.

## Decision logic (fail-open)

`allows(r)` returns **True** (alert) when:
1. filter disabled, OR
2. product has no MSRP entry, OR
3. price is `None` / unparseable.

Otherwise alert only if `price <= MSRP * max_over_msrp`; else suppress and log
`price filter: skipping <key> — price $X over cap $Y`.

The rule applies uniformly to online/pickup/preorder. First-party retailers
(Target, Pokémon Center) sell at MSRP, so the filter mainly bites on
inflated marketplace-style listings — harmless elsewhere.

## Testing

`tests/test_pricefilter.py` (plain `assert`, runnable with `python`):
- `parse_price`: `$49.99`, `$1,234.50`, `49.99`, `None`, `""`, junk.
- `PriceFilter.allows`: disabled → allow; unknown MSRP → allow; `None` price →
  allow; price under/at/over cap boundaries.

## Out of scope

- Per-category caps and single global hard cap (alternatives not chosen).
- Inline per-item MSRP nested in retailer lists (would require changing all
  six adapters).
