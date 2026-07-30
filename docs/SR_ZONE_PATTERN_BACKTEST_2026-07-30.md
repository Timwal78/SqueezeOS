# S/R Zone + Candlestick Pattern Engine — Bug Fix + Backtest Verdict (2026-07-30)

**Verdict: essentially NO real signal on 7 real symbols over 4.5 years. NOT wired to any scanner or `IAM_PRIMARY_SYSTEM`.**

## Why this was built

Operator pasted a second Pine v6 script ("Best S&R Indicator With Candlestick
Patterns") with the framing "this one buy at bottom sell at top easy." Unlike
the first script pasted the same day (structurally identical to the already-live
`sr_matrix_engine.py`), this one has a genuinely different, more selective
mechanic: a resistance/support zone only forms once `NoOfPivots` (default 2)
consecutive pivots cluster at a similar price level (two-touch confirmation,
not a single pivot), AND a qualifying candlestick reversal pattern (Morning
Star / Tweezer Bottom / Inside Bar for bullish; Evening Star / Tweezer Top /
Inside Bar for bearish) must occur specifically inside an active zone. The
original script has no defined buy/sell `alertcondition()` at all — only
zone-formation/proximity alerts — so "buy at bottom, sell at top" (the
operator's own framing) was implemented directly in `sr_zone_pattern_engine.py`.

## Bug found and fixed before trusting any result

The zone-creation blocks re-evaluated the clustering condition on every bar
without checking whether it had already fired for the same pivot cluster.
Once a cluster became true, nothing about `recent`/`ref` changed until a
genuinely new pivot arrived, so the same zone was re-appended as a duplicate
on every subsequent bar. Confirmed via a debug run on synthetic data
(seed=3, 300 bars): ~104 duplicate zone-creates from only ~1-9 real distinct
pivot clusters. Fixed by tracking the bar index of the most recent pivot
that triggered each zone type (`last_res_zone_pivot_idx`/
`last_sup_zone_pivot_idx`) and only creating a new zone when the newest
pivot in the current cluster is one that hasn't already triggered a zone.
Regression test: `tests/test_sr_zone_pattern_engine_smoke.py`.

## Method

`tests/backtest_sr_zone_pattern.py` drives `compute_series()` (full position
state machine, default `exit_mode="opposite_zone"`) over the same real daily
bars already local to this repo from the TTM Squeeze backtest — SPY, QQQ,
IWM, NVDA, TSLA, AMC, GME, 2022-01-03 through 2026-07-29, 1,146 real daily
bars each (Robinhood MCP `get_equity_historicals`, zero interpolated).

## Results

| Symbol | Bars | Entries | Trades | Buy & Hold |
|---|---|---|---|---|
| SPY  | 1146 | 0 | 0 | +52.70% |
| QQQ  | 1146 | 0 | 0 | +64.74% |
| IWM  | 1146 | 0 | 0 | +28.07% |
| NVDA | 1146 | 0 | 0 | +530.82% |
| TSLA | 1146 | 0 | 0 | -25.41% |
| AMC  | 1146 | 1 | 0 | -98.37% |
| GME  | 1146 | 0 | 0 | -42.84% |

**Aggregate: 1 entry (AMC), 0 completed trades, across 8,022 real trading
days of coverage.** The single AMC entry never closed within the tested
window under `exit_mode="opposite_zone"` (a bearish pattern at an active
resistance zone never occurred afterward).

## The finding that actually matters

This is not a losing strategy — it is a **near-silent** one. Requiring BOTH
a two-touch zone (already a real filter on its own — `sr_matrix_engine.py`'s
single-pivot version generated 22-30 trades/symbol on the same data) AND a
specific candlestick reversal pattern occurring inside that zone's exact
price range is an AND of two independently rare conditions. The operator's
framing ("buy at bottom sell at top easy") does not hold up under an honest
test — the confluence this script requires almost never happens in real
data, not because the logic is wrong, but because two-touch-zone AND
pattern-match together is a much stricter filter than either alone.

## What this does NOT do

- Does not get wired to any scanner (`*_scanner.py`) or to `iam_executor.py`.
- Does not get added to `IAM_PRIMARY_SYSTEM`.
- Is not represented as validated or "coming soon" anywhere in product copy.
- Does not claim the underlying candlestick-pattern or zone-clustering logic
  is buggy — the bug found and fixed was purely a duplicate-bookkeeping
  issue in zone creation, not in the pattern-detection or clustering math
  itself (both ported byte-for-byte from the Pine source, unchanged).

## If this is revisited

- Loosening `no_of_pivots` to accept a wider price tolerance, or trying
  `exit_mode="atr_target"` instead of `opposite_zone` (so a trade can exit
  even if the opposite zone/pattern confluence never recurs), are the two
  concrete levers — neither has been tried. Both would need a fresh honest
  backtest before any live-wiring claim, same discipline as every other
  engine in this codebase.
