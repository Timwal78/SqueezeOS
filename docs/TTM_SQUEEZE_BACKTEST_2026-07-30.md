# TTM Squeeze Engine — Backtest Verdict (2026-07-30)

**Verdict: NOT profitable as-configured. Do not wire to any scanner or `IAM_PRIMARY_SYSTEM`.**

## Why this was built

Operator asked for a "sure fire" Keltner/Bollinger squeeze buy setup. Real
TTM Squeeze (Bollinger-inside-Keltner) logic already existed in
`squeeze_analyzer.py`'s `_compression_score()` — but only as one 15-point
component buried inside an 8-module composite score, never isolated as its
own standalone signal and never independently backtested. `ttm_squeeze_engine.py`
extracts that exact same BB(20,2)/KC(20,1.5×ATR) math into a standalone
walk-forward engine (squeeze ON when BB sits entirely inside KC; squeeze
FIRES the bar it expands back out; direction from TTM's real published
momentum histogram — `linreg(close - avg(donchian_mid_20, sma_20), 20)`, not
an invented proxy) and backtests it honestly before making any claim.

No "sure fire" claim is or was ever going to be made without real evidence —
same discipline as every other engine in this codebase (see AETHER, DRUCK,
RSI-ML, Gamma Ramp, CVD Regime sections of `CLAUDE.md`, all of which shipped
with real backtests before any live-arming decision).

## Method

`tests/backtest_ttm_squeeze.py` drives `ttm_squeeze_engine.compute_series()`
(the full position state machine — 1.5× ATR stop, 3× ATR target, both long
and short) over real daily bars, 2022-01-03 through 2026-07-29, pulled via
Robinhood MCP `get_equity_historicals` (same real-data channel used for every
other backtest in this codebase — DRUCK/CIE/Breakout/MM-Intel/CVD Regime).
7 symbols: SPY, QQQ, IWM, NVDA, TSLA, AMC, GME — 1,146 real daily bars each,
zero interpolated bars (checked). No lookahead: entries fill at the fire
bar's own close (Bollinger/Keltner values at that bar are fully known at
that bar's close, unlike an intraday breakout), exits checked on each
subsequent bar's close only.

## Results

| Symbol | Bars | Fires | Trades | Win% | Avg Trade | PF | Strategy Return | Buy & Hold |
|---|---|---|---|---|---|---|---|---|
| SPY  | 1146 | 24 | 15 | 53.3% | +1.667% | 2.39 | **+26.45%** | +52.70% |
| QQQ  | 1146 | 19 | 15 | 20.0% | -1.462% | 0.45 | -20.77% | +64.74% |
| IWM  | 1146 | 27 | 20 | 30.0% | -0.580% | 0.76 | -12.77% | +28.07% |
| NVDA | 1146 | 22 | 17 | 23.5% | -4.892% | 0.36 | **-60.95%** | **+530.82%** |
| TSLA | 1146 | 25 | 22 | 40.9% | +2.198% | 1.37 | +25.41% | -25.41% |
| AMC  | 1146 | 31 | 23 | 34.8% | -0.065% | 0.99 | -42.06% | -98.37% |
| GME  | 1146 | 31 | 22 | 36.4% | -1.484% | 0.83 | -49.68% | -42.84% |

**Aggregate: 134 trades, 34.3% win rate, PF 0.901, net losing.**

Params used (real published TTM Squeeze defaults, not tuned): BB(20, 2.0σ),
KC(20, 1.5× ATR), momentum lookback 20, 1.5× ATR stop / 3× ATR target
(~1:2 R:R, same stop-multiplier convention already used elsewhere in this
codebase — `robinhood_executor_sml.py`'s `ATR_STOP_MULTIPLIER`).

## The finding that actually matters

Only 2 of 7 symbols (SPY, TSLA) were net profitable. The rest lose money
outright — and on the two names with the biggest real trending moves in this
window, the strategy didn't just fail to capture the trend, it actively lost
money fighting it: **NVDA -60.95% strategy vs +530.82% buy-and-hold; QQQ
-20.77% strategy vs +64.74% buy-and-hold.** A squeeze-fire signal firing 19-31
times over 4.5 years on a strongly trending name and losing money on the
round trips is a real, measured finding, not a parameter-tuning problem —
the signal is trading noise around a trend it isn't actually predicting.

## Honest context for why this doesn't match "scanners catching 200-600% moves"

Real Bollinger/Keltner squeeze logic (the same math many retail scanner
tools market) does not, on this honest test, reliably front-run big moves.
Content showing scanners "catching" huge moves over and over is near-certain
survivorship bias — scanning thousands of tickers and posting the rare
outlier hit, never the much larger number of false fires. This backtest is
the opposite of that: every fire on every symbol over the full window is
counted, wins and losses alike.

## What this does NOT do

- Does not get wired to any scanner (`*_scanner.py`) or to `iam_executor.py`.
- Does not get added to `IAM_PRIMARY_SYSTEM`.
- Is not represented as validated or "coming soon" anywhere in product copy.
- `squeeze_analyzer.py`'s existing 8-module composite score is untouched —
  this finding is about the SQUEEZE COMPONENT in isolation, not a claim that
  the full composite score (which also weighs volume, momentum, RSI, money
  flow, structure, trend, Z-score) is equally weak. That composite has its
  own separate, already-live role in `squeeze_fuel_engine.py`'s Ignition
  score — not re-litigated here.

## If this is revisited

- No scanner/live-wiring without a materially different result on a fresh
  test — do not re-run the same params expecting a different answer.
- Worth trying if pursued further: an out-of-sample train/valid split (same
  methodology as `tests/optimize_cvd_regime.py`) before concluding any
  parameter change actually helps rather than just fitting this specific
  window's noise.
- Squeeze duration / tightness filtering (only fire after a longer squeeze,
  not any squeeze) was not tested — a real, testable next lever, not done
  here.
