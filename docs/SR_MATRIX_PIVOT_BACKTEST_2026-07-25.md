# SML Support/Resistance Matrix — Pivot Backtest — 2026-07-25

Backtest of `indicators/SML_Support_Resistance_Matrix.pine`'s pivot cross
signals (the red/green `+` markers at the bottom of the chart:
`plot(PivotHigh, style=cross, color=red, offset=-Bars)` /
`plot(PivotLow, style=cross, color=green, offset=-Bars)`). This script has
no other defined trading signal — its zones and candle-pattern labels are
informational only, no entry/exit logic. Rule tested (operator-specified
2026-07-25): **long-only** — buy when a pivot low confirms, sell (close)
when a pivot high confirms. No naked shorts, matching this account's
no-shorts policy everywhere else.

No lookahead: Pine's `ta.pivotlow(Bars, Bars)`/`ta.pivothigh(Bars, Bars)`
only confirm a pivot `Bars` bars *after* it occurred (needs bars on both
sides to know it was a local extreme) — modeled here as tradeable starting
the bar after confirmation, at that bar's open, never at the pivot bar
itself.

## Method

- Standalone Python port of the pivot-detection logic (5-line function,
  matches `ta.pivothigh`/`ta.pivotlow` semantics exactly — strict extreme
  with no ties in the window)
- `Bars = 10` (script default)
- Data: same real daily bars as every other backtest tonight —
  AMC/GME/IWM/SPY, 2022-01-03 to 2026-07-23

## Results

| Symbol | Trades | Win% | PF | Strat% | B&H% | MaxDD% |
|--------|-------:|-----:|-----:|-------:|-------:|-------:|
| AMC | 30 | 23.3 | 0.35 | -90.0 | -98.6 | 90.2 |
| GME | 30 | 40.0 | 1.30 | **-3.9** | -44.1 | 41.0 |
| IWM | 30 | 53.3 | 1.46 | +16.9 | +29.6 | 22.9 |
| SPY | 22 | 54.5 | 1.86 | +32.4 | +54.5 | 17.7 |

## Reading it honestly

- **Best all-around result of the four new scripts tested tonight** (vs.
  AETHER's clean losses, RSI-ML's likely-wrong-timeframe losses, and Trade
  Desk's thin 3-13-trade sample). Positive PF on 3 of 4 symbols, with real
  trade counts (22-30, not a handful) — actually statistically meaningful
  by this session's own standard.
- Same pattern every strategy tonight showed on GME/AMC: doesn't avoid
  losses outright, but loses far less than simply holding (GME -3.9% vs
  -44.1% B&H; AMC -90.0% vs -98.6% B&H) — the "correctly avoiding the
  disaster" signature CASCADE also showed on AMC in the engine scoreboard.
- **Still trails buy-and-hold on the trending winners (IWM, SPY)** — same
  ceiling every reactive/exit-bearing strategy hit tonight against a
  strongly bull-trending 4.5-year window. Beating simple buy-and-hold on a
  raging bull market is a genuinely high bar for any strategy that ever
  exits a position.
- One 4.5-year window, one regime, zero parameter tuning (`Bars=10`
  untouched) — real evidence, not a guarantee across other regimes.

## What this does NOT change

- Nothing wired to anything. No Python engine exists for this script in
  the repo, no scanner, no `iam_executor` connection. This is a fresh
  backtest of a rule the operator specified for an existing chart-only
  indicator (`indicators/SML_Support_Resistance_Matrix.pine`, committed
  2026-07-11) — not a build decision.
- If this is worth carrying further (a real `sr_matrix_engine.py` +
  scanner, matching the ORB/DRUCK/Breakout pattern), that's a separate,
  explicit next step, not implied by this backtest alone.
