# DRUCK-LB v7 BeastMode Backtest — 2026-07-22

Independent real-data backtest of the operator-supplied "DRUCK-LB v7
BeastMode - Full Portfolio (IWM Added)" Pine strategy
(`indicators/SML_DRUCK_LB_v7_BeastMode.pine`) — a different, simpler script
from the existing `SML_Druckenmiller_Liquidity_Breakout_v6.pine` /
`druck_engine.py` (no regime/percentrank/mean-reversion mode, no
pyramiding). The operator reported this v7 script "was only good for AMC
and GME, but different timeframes — it sucked on the other tickers," so
this test is scoped to AMC and GME only, across 1h/2h/4h.

**Verdict: as literally coded, this script cannot generate a single trade on
real AMC or GME data at 1h, 2h, or 4h.** The HTF confirmation filter blocks
every entry it's supposed to confirm — see Finding 1. With that filter
isolated out to see what's left, the core ADX+breakout+trend logic does
trade, but is not profitable on the real windows tested (mixed to negative
across both symbols and all three timeframes). This does not match the
operator-supplied screenshot's TradingView Strategy Tester result for AMC
4h (+4.12% total, 61.19% win rate, PF 1.623) — see "Why the numbers don't
match" below for what is and isn't explained.

## Method

- Port: `druck_lb_v7_engine.py` (signal math — DMI/ADX/EMA/breakout, ported
  line-for-line from the Pine script) + `tests/backtest_druck_lb_v7.py`
  (position simulation: fixed ATR stop/target at entry + ratcheting ATR
  trail, net-position reversal on an opposite signal, no lookahead — entries
  fill at next bar's open)
- Data: real OHLCV bars pulled live via the Robinhood MCP
  (`get_equity_historicals`), regular session, split-adjusted, at the native
  `hour` and `4hour` intervals; `2h` bars aggregated client-side from the
  real `1h` bars (simple bucket OHLCV rollup, no interpolation). Rows the
  provider itself flagged `interpolated: true` (synthetic gap-fill, not real
  prints) were dropped before use.
- **Real (non-interpolated) history depth was capped at the same window for
  every symbol tested — 2025-11-03 to 2026-07-22 (~8.5 months) at `1h`/`4h`,
  2025-12-22 to 2026-07-22 (~7 months) at native `1h`-derived `2h`** — a
  provider-side retention limit on intraday bars, not something specific to
  AMC/GME. This is a real but short window; treat results as directional
  evidence for this regime, not a multi-cycle proof.
- Default params (matching the Pine script exactly): `ADX_len=22
  ADX_trend=22 breakout_len=15 EMA=8/21 ATR_stop_mult=1.5 trail_mult=2.5
  RR=2.5 HTF=2h(120m) vol_mult=1.8`, commission 0.04%/side.

## Finding 1 (headline): the HTF filter structurally blocks nearly every entry

`trendUp = fastEMA > slowEMA and (not useHTF or htfEMA > fastEMA)` — the 2H
`htfEMA` must already be above the chart's own `fastEMA` for a long (below
it for a short). `htfEMA` only updates once its own 2H bucket has fully
closed (`lookahead_off`), so it necessarily lags the chart's own fast EMA
during the sharp move that produces a breakout. Traced every real breakout
event across AMC and GME at 1h and 4h (17 breakout bars total in the traced
sample): **100% of long breakouts coincided with `htfEMA < fastEMA`
(blocking), and 100% of short breakouts coincided with `htfEMA > fastEMA`
(blocking)** — the filter is on the wrong side exactly when it matters, not
occasionally but every single time observed. Net effect: **0 combined
long/short signals across all 6 symbol × timeframe combinations tested**
with the HTF gate active as coded.

With `useHTF` disabled (isolating ADX + breakout + trend), signals resume
firing normally:

| Symbol/TF | BUY signals | SELL signals |
|-----------|------------:|-------------:|
| AMC 1h    | 4           | 4             |
| AMC 2h    | 7           | 2             |
| AMC 4h    | 3           | 4             |
| GME 1h    | 4           | 3             |
| GME 2h    | 2           | 1             |
| GME 4h    | 2           | 2             |

## Finding 1 result: performance with the HTF gate removed (real bars)

| Symbol/TF | Trades | Win% | Avg%/trade | PF | Avg bars held | Total return% |
|-----------|-------:|-----:|-----------:|----:|--------------:|---------------:|
| AMC 1h    | 7      | 57.1 | 0.249      | 1.07 | 13.9          | -0.91          |
| AMC 2h    | 7      | 28.6 | -1.312     | 0.75 | 6.1           | **-12.84**     |
| AMC 4h    | 5      | 0.0  | -7.680     | 0.00 | 5.6           | **-33.63**     |
| GME 1h    | 7      | 14.3 | -1.193     | 0.25 | 3.7           | -8.17          |
| GME 2h    | 3      | 0.0  | -1.883     | 0.00 | 1.7           | -5.55          |
| GME 4h    | 4      | 25.0 | -0.704     | 0.65 | 6.0           | -3.03          |

Only AMC 1h comes out roughly breakeven (PF 1.07, essentially flat); every
other combination is a real loser on this window, including AMC 4h — the
exact symbol/timeframe pair the operator's screenshot showed as profitable.

## Finding 2: `strategy.exit()`'s stop/limit are recalculated every bar, not fixed at entry

Both `strategy.exit(...)` calls in the Pine script run unconditionally on
every bar, passing `stop=close*(1-atrStopMult*atrVal/close)` and
`limit=close*(1+rrRatio*atrStopMult*atrVal/close)` — values computed from
*that bar's* close and ATR. TradingView updates a pending order's levels in
place when `strategy.exit()` is called again for the same id, so the actual
stop/target track the current bar, not the entry price, for as long as a
position stays open. This is very likely an unintended side effect of not
gating the call to fire once at entry, not a deliberate "moving bracket"
design (the input names — "ATR Stop Mult", "Risk:Reward" — clearly intend a
fixed bracket).

This backtest's harness deliberately does **not** reproduce that behavior —
it implements the economically-intended fixed-at-entry stop/target plus a
ratcheting ATR trail (same convention as `druck_engine.py`/
`tests/backtest_druck.py` for the existing v6 script). That is a real,
disclosed limitation of this comparison, covered next.

## Why the numbers don't match the screenshot, and what that does and doesn't mean

The operator's screenshot shows TradingView's own Strategy Tester producing
real trades and a positive result for AMC on the 4h chart. This backtest,
using a faithful port of the same entry-gate math, produces **zero** trades
for AMC 4h with the HTF filter on as coded. Two things can be true at once:

1. **The entry-gate math (Finding 1) is verified correct against real
   data** — the HTF condition really is on the wrong side at every observed
   breakout, in this port, on this data. That part of the discrepancy is
   explained: if that mechanism holds on TradingView's live data too, the
   screenshot's live trades could not have come from the script exactly as
   pasted with `useHTF=true`, unless TradingView's `request.security` with a
   deep, long-since-converged HTF EMA history (this port's HTF EMA has only
   the same ~8 months of warmup as the base data, not years) or a genuine
   session/timezone difference in bucket alignment behaves differently
   at the margin than the bucket-resample model used here. A younger,
   less-converged EMA reacts *faster* to price than a fully warmed-up one,
   so if anything this port's HTF filter should block *less* often than a
   long-history live version would — which would make the real discrepancy
   larger, not smaller. This is flagged as an open question, not resolved.
2. **Finding 2 (every-bar-recalculated stop/limit) means this backtest and
   the screenshot are not testing the same exit mechanics even where entries
   do fire** — a real, disclosed difference, not an attempt to reproduce
   that exact screenshot number.

**Bottom line: this backtest cannot confirm the screenshot's specific
+4.12%/61.19%/PF-1.623 result, and independently finds the script's own HTF
gate structurally blocks trading as coded on both AMC and GME across every
timeframe tested.** With that gate removed, the surviving core strategy is
not profitable on the real, available window for either symbol at any
timeframe tested except a roughly-breakeven AMC/1h. Do not treat the
screenshot as confirmed evidence of a working strategy until the HTF
condition is either fixed or the discrepancy above is otherwise resolved
against a live TradingView run on the same symbol/timeframe/date range.

## Reproduce

```bash
python tests/backtest_druck_lb_v7.py amc_1h.csv amc_2h.csv amc_4h.csv gme_1h.csv gme_2h.csv gme_4h.csv
DRUCKV7_USE_HTF=false python tests/backtest_druck_lb_v7.py amc_1h.csv amc_2h.csv amc_4h.csv gme_1h.csv gme_2h.csv gme_4h.csv
```

CSV columns: `date,open,high,low,close,volume` (ISO-8601 date). The CSVs used
for this run were pulled via Robinhood MCP `get_equity_historicals` and are
not committed to this repo (same "pull your own real data" pattern as
`docs/DRUCK_BACKTEST_2026-07-21.md`) — regenerate by requesting real
`hour`/`4hour` bars for AMC/GME and dropping any bar with
`interpolated: true` before use.
