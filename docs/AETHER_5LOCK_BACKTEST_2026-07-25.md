# AETHER 5-LOCK Backtest — 2026-07-25

First real backtest of `indicators/AETHER_5LOCK_PROTOCOL_v8.pine` (committed
2026-07-15, never previously backtested — v8 hardened the script for live
trading but no Python engine or backtest existed until now).

**Verdict: not ready for live trading.** Catastrophic on AMC/GME (-70% to
-77%), and on its two best symbols (SPY, IWM) it's marginally profitable but
badly underperforms simple buy-and-hold. Do not wire this to `iam_executor`
or add `AETHER_5LOCK` to `IAM_PRIMARY_SYSTEM` based on current evidence.

## Method

- Engine: `aether_engine.py` (new — Python port of the Pine script's EMA
  lock-count + persistence + volume-gate logic, single source of truth)
- Harness: `tests/backtest_aether.py` (long-only: enter next-bar-open on
  tier2/tier3 signal, exit next-bar-open on lock-drop-below-2 OR a 3% hard
  stop — same IAM_STOP_LOSS_PCT-equivalent every other engine here gets
  live, since the Pine script's own ATR lines are cosmetic only, not a real
  exit trigger)
- Data: same real daily bars as `docs/BREAKOUT_BACKTEST_2026-07-25.md` —
  AMC/GME/IWM/SPY, 2022-01-03 to 2026-07-23 (~4.5 years, 1,142 real bars/symbol,
  Robinhood-MCP-sourced, reused from that earlier pull)

## Results

| Symbol | Tier | Trades | Win% | PF | Stops | Strat% | B&H% | MaxDD% |
|--------|------|-------:|-----:|-----:|------:|-------:|-------:|-------:|
| AMC | tier2 | 21 | 4.8  | 0.04 | 20 | **-69.7** | -98.6 | 69.7 |
| AMC | tier3 | 5  | 0.0  | 0.00 | 5  | -30.7 | -98.6 | 30.7 |
| GME | tier2 | 29 | 6.9  | 0.04 | 27 | **-76.2** | -44.1 | 76.2 |
| GME | tier3 | 25 | 8.0  | 0.04 | 23 | -77.1 | -44.1 | 77.1 |
| IWM | tier2 | 15 | 46.7 | 1.40 | 6  | +8.6  | +29.6 | 12.1 |
| IWM | tier3 | 13 | 30.8 | 0.71 | 7  | -8.5  | +29.6 | 17.2 |
| SPY | tier2 | 12 | 50.0 | 2.34 | 6  | +24.4 | +54.5 | 8.7  |
| SPY | tier3 | 6  | 66.7 | 5.76 | 2  | +30.7 | +54.5 | 3.0  |

## Reading it honestly

- **AMC/GME are near-total capital destruction** (win rates 5-8%, PF ~0.04,
  20-27 of the trades hitting the hard stop). A trend-lock EMA system
  whipsaws badly on stocks this volatile/choppy — same failure mode ORB and
  DRUCK showed on meme names elsewhere in this repo.
- **SPY/IWM don't lose money but badly trail buy-and-hold.** SPY tier3's PF
  5.76 looks strong but is 6 trades over 4.5 years (+30.7% vs +54.5% simply
  holding) — the lock-persistence + volume gate filters out most setups,
  leaving too few trades to beat a strong bull-trending benchmark. IWM
  tier2's +8.6% vs +29.6% B&H is the same story with a thinner margin.
- **This is one 4.5-year window in one broad bull regime, no parameter
  tuning attempted** — same disclosure standard as every other verdict in
  this file. Real evidence against live trading as-configured, not proof it
  can never work.

## What this does NOT change

- The Pine script itself is untouched and still chart-usable for discretionary
  trading — this verdict is about *autonomous* live execution specifically.
- No env vars changed. `AETHER_5LOCK` was never added to `IAM_PRIMARY_SYSTEM`
  and there is no scanner wiring it to `iam_executor` at all (the only path
  it could ever reach live execution is a manually-configured TradingView
  alert hitting the webhook bridge — nothing autonomous exists for it).
