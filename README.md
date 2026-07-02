<h1 align="center">
  <img src="https://github.com/user-attachments/assets/0cc687fb-89c4-43fa-a056-d89c307215ad" alt="Kuest" height="96" /><br/>
  Kuest Python Market Maker Example
</h1>

## What It Does

- Finds active, tradable markets from the fork site and records newly seen
  market ids in `state/seen-markets.json`.
- Can scope trading to one event by slug, resolving that event's markets from
  the configured site API.
- Computes configurable buy/sell quotes per selected outcome token. It defaults
  to buy-only because sell orders require existing outcome-token inventory.
- Posts GTC limit orders only when `--live` is set. Dry-run is the default.

The quoting strategy is intentionally simple: estimate fair value from the book
midpoint, then maintain configured quote-size bands around that fair value. The
bot cancels orders outside the active band, trims excess size above the band
maximum, and only tops up when open size falls below the band minimum.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e vendor/py-clob-client
python -m pip install -e ".[dev]"
```

The customized Python CLOB SDK must be vendored at `vendor/py-clob-client`.
Move the whole SDK project root there, not only the `py_clob_client/` package
folder. The directory should look like this:

```text
vendor/py-clob-client/
  py_clob_client/
  setup.py
  .sdk/
```

## Dry Run

```bash
python -m py_market_maker
```

or, after installation:

```bash
py-market-maker
```

To trade only one event, pass the event slug:

```bash
python -m py_market_maker --event-slug nba-finals-2026
```

Event mode reads `.sdk/site-config.json`, uses the configured Kuest site API,
and fetches only the CLOB markets listed under that event. It does not update
`state/seen-markets.json`.

## Live Trading

Start live mode with:

```bash
python -m py_market_maker --live
```

Live mode requires `KUEST_PRIVATE_KEY`, `KUEST_DEPOSIT_WALLET`, and
`KUEST_CHAIN_ID`. You can also pass them as `--private-key`,
`--deposit-wallet`, and `--chain-id`. Use chain id `137` for Polygon or `80002`
for Amoy.

Live mode runs a preflight risk audit on the selected market scope before
quoting. It fetches current books, balances, and open orders; skips the cycle
if those inputs cannot be fetched, are stale, or already breach configured risk
caps. Before posting live orders, the bot blocks quotes whose simulated fill
would exceed the configured market loss cap. By default, live mode also
requires a two-sided book with acceptable spread and top-of-book depth before
quoting. After cancel requests, live mode refreshes open orders before posting
replacements; after post responses, it only counts accepted orders as pending
local exposure. Authenticated trade history is persisted in `state/fills.json`
and used to value existing outcome-token balances at realized cost basis. If
the persisted fill ledger cannot explain the live token balance within the
configured position tolerance, live mode skips quoting that market for the
cycle. Buy-side sizing is inventory-aware: token balances, live open buys, and
pending buys are counted before adding more long exposure to an outcome or
market. When current state already breaches inventory or market-loss caps, the
bot skips new quotes and can optionally cancel resting buy orders. It can also
write a pause file so later cycles or restarts stop before discovery.

By default live mode only posts buy orders.

Use sell-side quoting only when the deposit wallet already owns outcome tokens
for the market:

```bash
MARKET_MAKER_QUOTE_SIDES=both python -m py_market_maker --live
```

If a sell order returns `position balance 0 below required 5000000`, the wallet
has zero balance for that outcome token and the order size is 5 shares
(`5 * 10^6` base units).

To cancel all open orders in the currently configured market scope and exit:

```bash
python -m py_market_maker --live --cancel-all
```

To cancel scoped open orders when the process is interrupted, for example by
Ctrl-C or SIGTERM:

```bash
python -m py_market_maker --live --cancel-all-on-exit --cycles 1000
```

Both cancel modes are live-only. With `--event-slug`, `--cancel-all` discovers
the selected event's markets at startup, cancels their open orders, and exits.
Without `--event-slug`, it targets the normal discovery selection.
`--cancel-all-on-exit` uses the latest non-empty market scope managed while the
bot was running, so a transient empty discovery cycle does not clear the
emergency cancel target.

## CLI args / env vars

```md
  --clob-host / KUEST_CLOB_HOST
  Default: https://clob.kuest.com

  --live / MARKET_MAKER_LIVE
  Default: false

  --private-key / KUEST_PRIVATE_KEY
  Required only with --live.

  --deposit-wallet / KUEST_DEPOSIT_WALLET
  Required only with --live.

  --chain-id / KUEST_CHAIN_ID
  Required only with --live.
  Allowed: 137 Polygon, 80002 Amoy.

  --discovery / MARKET_MAKER_DISCOVERY
  Default: auto. Values: auto, sampling, site.

  --event-slug / MARKET_MAKER_EVENT_SLUG
  Optional. When set, trade only markets under this event slug from
  .sdk/site-config.json.

  --max-markets / MARKET_MAKER_MAX_MARKETS
  Default: 3.

  --max-pages / MARKET_MAKER_MAX_PAGES
  Default: 5.

  --order-size / MARKET_MAKER_ORDER_SIZE
  Default: 5.

  --edge-ticks / MARKET_MAKER_EDGE_TICKS
  Default: 1.

  --min-spread-ticks / MARKET_MAKER_MIN_SPREAD_TICKS
  Default: 2.

  --band-min-margin-ticks / MARKET_MAKER_BAND_MIN_MARGIN_TICKS
  Optional. Default: --edge-ticks.
  Inner band edge, in ticks away from fair. Existing orders closer than this
  are canceled because they no longer have enough edge.

  --band-avg-margin-ticks / MARKET_MAKER_BAND_AVG_MARGIN_TICKS
  Optional. Default: band min margin.
  Price level used for new top-up orders inside the band.

  --band-max-margin-ticks / MARKET_MAKER_BAND_MAX_MARGIN_TICKS
  Optional. Default: band min margin plus --min-spread-ticks.
  Outer band edge, in ticks away from fair. Existing orders beyond this are
  canceled because they are no longer part of the intended quote band.

  --band-min-size / MARKET_MAKER_BAND_MIN_SIZE
  Optional. Default: --order-size.
  Minimum total open size allowed inside the active side band before topping up.

  --band-avg-size / MARKET_MAKER_BAND_AVG_SIZE
  Optional. Default: max(--order-size, band min size).
  Target total open size after a top-up or excess cancellation pass.

  --band-max-size / MARKET_MAKER_BAND_MAX_SIZE
  Optional. Default: max(band avg size, band min size).
  Maximum total open size allowed inside the active side band before trimming.

  --max-loss-per-market / MARKET_MAKER_MAX_LOSS_PER_MARKET
  Default: 25.
  Maximum simulated worst-case market loss allowed after existing balances,
  open orders, and the proposed new order are counted. Existing balances are
  valued at realized cost basis from the persisted fill ledger; live quoting is
  skipped when the ledger and live balance do not reconcile.

  --max-inventory-per-token / MARKET_MAKER_MAX_INVENTORY_PER_TOKEN
  Default: 25.
  Maximum long outcome-token inventory allowed after balances, live open buys,
  pending buys, and staged buys are counted.

  --max-inventory-per-market / MARKET_MAKER_MAX_INVENTORY_PER_MARKET
  Default: 50.
  Maximum total long inventory across a market's outcome tokens.

  --max-book-spread-ticks / MARKET_MAKER_MAX_BOOK_SPREAD_TICKS
  Default: 20.
  In live mode, when --require-two-sided-live is enabled, skip tokens when
  best ask minus best bid is wider than this many ticks.

  --max-pre-post-move-ticks / MARKET_MAKER_MAX_PRE_POST_MOVE_TICKS
  Default: 2.
  Live-mode posting guard. Immediately before posting new orders, refresh the
  token book and skip the post if fair value moved by more than this many ticks
  from the planned fair value.

  --min-top-depth / MARKET_MAKER_MIN_TOP_DEPTH
  Default: 5.
  In live mode, when --require-two-sided-live is enabled, skip tokens unless
  both best bid and best ask have at least this much size at the top level.

  --require-two-sided-live / MARKET_MAKER_REQUIRE_TWO_SIDED_LIVE
  Default: true.
  In live mode, require a valid two-sided book before quoting.

  --max-data-age-secs / MARKET_MAKER_MAX_DATA_AGE_SECS
  Default: 10.
  Live-mode freshness limit for order books, token balances, and open orders.

  --quote-sides / MARKET_MAKER_QUOTE_SIDES
  Default: buy. Values: buy, sell, both.

  --allow-single-sided / MARKET_MAKER_ALLOW_SINGLE_SIDED
  Default: true.

  --respect-reward-min-size / MARKET_MAKER_RESPECT_REWARD_MIN_SIZE
  Default: false.

  --cancel-before-quote / MARKET_MAKER_CANCEL_BEFORE_QUOTE
  Default: true.

  --cancel-all / MARKET_MAKER_CANCEL_ALL
  Default: false.
  In live mode, cancel open orders in the currently configured market scope and
  exit.

  --cancel-all-on-exit / MARKET_MAKER_CANCEL_ALL_ON_EXIT
  Default: false.
  In live mode, cancel open orders in the latest non-empty managed market scope
  when the process is interrupted.

  --cancel-on-risk-breach / MARKET_MAKER_CANCEL_ON_RISK_BREACH
  Default: false.
  Live-only circuit-breaker action. When current state already breaches
  inventory or market-loss caps, skip new quotes and cancel resting buy orders
  for the breached token.

  --pause-on-risk-breach / MARKET_MAKER_PAUSE_ON_RISK_BREACH
  Default: false.
  Live-only circuit-breaker action. When current state already breaches a risk
  cap, write the pause file and stop quoting further markets. Necessary when a
  breached run should stay stopped across later cycles or process restarts.

  --clear-pause / MARKET_MAKER_CLEAR_PAUSE
  Default: false.
  One-shot command. Removes the pause file and exits without connecting to the
  CLOB API. Necessary after a manual risk review decides the bot may resume.

  --pause-path / MARKET_MAKER_PAUSE_PATH
  Default: state/paused.json.
  Path to the persisted pause file checked before each cycle and after live
  quote attempts.

  --post-only / MARKET_MAKER_POST_ONLY
  Default: true.

  --discover-only / MARKET_MAKER_DISCOVER_ONLY
  Default: false.

  --cycles / MARKET_MAKER_CYCLES
  Default: 1.

  --refresh-secs / MARKET_MAKER_REFRESH_SECS
  Default: 30.

  --state-path / MARKET_MAKER_STATE_PATH
  Default: state/seen-markets.json.

  --fill-state-path / MARKET_MAKER_FILL_STATE_PATH
  Default: state/fills.json.
  Persisted authenticated trade ledger used to compute realized cost basis for
  live outcome-token balances.

  --fill-max-records / MARKET_MAKER_FILL_MAX_RECORDS
  Default: 10000.
  Maximum fill records retained in the persisted ledger. The oldest records are
  pruned after each live state refresh to keep cycle latency bounded.

  --position-reconcile-tolerance / MARKET_MAKER_POSITION_RECONCILE_TOLERANCE
  Default: 0.000001.
  Maximum allowed difference between live token balance and fill-ledger
  position. Larger mismatches skip live quoting because cost basis is uncertain.
```
