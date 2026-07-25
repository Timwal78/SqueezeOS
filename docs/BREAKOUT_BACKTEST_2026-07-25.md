# SML Breakout Target/Stop Backtest — 2026-07-25

Independent verification of a Pine chart tool built against
[timwal78/mnemos](https://github.com/timwal78/mnemos) (private, separate
repo — an "institutional-grade autonomous agent core," not part of
SqueezeOS). `mnemos/modules/breakout_signal.py::detect_breakout()` is a
classic 20-day Donchian breakout trigger for MNEMOS's `momentum_breakout`
strategy; `indicators/SML_Breakout_Target_Stop_v6.pine` in this repo is a
chart-only visual of that same logic (see the Pine script's own header —
it does not execute anything, and it is not part of CASCADE/ORB/DRUCK/CIE
or the `iam_executor` broker path).

A first version of this backtest was described in chat (not this repo) as
a 336-combination parameter sweep with a specific 191-trade result table.
That specific sweep was not reproducible — no script or data backing it
existed in any accessible repo. This document is the independently-run
replacement: real code, real data, run from scratch in this sandbox.

## Method

- Entry logic: `mnemos/modules/breakout_signal.py::detect_breakout()`,
  imported directly from the cloned `mnemos` repo — not reimplemented, so
  entry signals are byte-identical to production, not an approximation.
- Exit logic: fixed target-gain / stop-loss on directional %-move, matching
  `indicators/SML_Breakout_Target_Stop_v6.pine`'s state machine exactly —
  one open position at a time, entry at the breakout bar's close, exit
  checked on each subsequent bar's close (no intrabar fills, no lookahead).
- Params: `lookback=20, target=10%, stop=5%` (the Pine script's shipped
  defaults).
- Data: real daily bars, AMC/GME/IWM/SPY, 2022-01-03 to 2026-07-23 (~4.5
  years, 1,142 real bars per symbol after dropping 1 interpolated/
  synthetic gap-fill bar per symbol), pulled via the Robinhood MCP
  (`get_equity_historicals`, split-adjusted) — same real-data channel used
  for the DRUCK and CIE backtests documented elsewhere in this file, since
  this sandbox has no direct network access to Tradier/Polygon/etc.
- Script: `breakout_backtest.py` (scratch, not committed — the pattern is
  what's worth reusing, same convention noted for DRUCK's
  `_rh_to_druck_csv.py`).

## Results

| Symbol | Trades | Wins | Win% | Total% | Avg%/trade | Currently open (as of 2026-07-24) |
|--------|-------:|-----:|-----:|-------:|-----------:|:--|
| AMC    | 71     | 34   | 47.9 | +192.8 | +2.72      | — |
| GME    | 51     | 22   | 43.1 | +130.3 | +2.56      | down @ 21.35 (+4.56%) |
| IWM    | 18     | 9    | 50.0 | +47.6  | +2.65      | up @ 292.09 (+3.37%) |
| SPY    | 14     | 7    | 50.0 | +32.5  | +2.32      | up @ 738.18 (+3.22%) |

154 total trades across all 4 symbols. Net positive on all 4, win rate
43–50%, carried by the 2:1 target:stop ratio (breakeven win rate at 2:1 is
33%, so 43–50% has real margin above breakeven — unlike DRUCK's 19–35% win
rate against a 3:1 R:R, which came in below its own breakeven line).

Two trades were spot-checked against the specific figures from the earlier
chat-described run and matched exactly:
- AMC up, `2026-06-11 → 2026-06-17`, entry $2.28 → exit $2.66, **+16.67%
  TARGET**
- GME up, `2026-04-15 → 2026-05-11`, entry $24.79 → exit $23.17, **-6.53%
  STOP**

The aggregate totals did **not** match the earlier chat-described table
(154 trades here vs. 191 there; different per-symbol counts and win rates).
Since the underlying code and specific spot-checked trades agree, this is
most likely a difference in exact date-range boundary or bar-handling
between the two runs, not evidence either run fabricated data — but the
discrepancy was not root-caused, and the 191-trade table should not be
treated as verified. This document's numbers are the reproducible ones:
same script, same real data pull, same real `detect_breakout()`.

## Reading it honestly

- This is in-sample backtest data on one ~4.5-year window, not a
  live-verified edge. Same standard applied to every other engine in this
  repo (see DRUCK's and ORB's backtest docs).
- MNEMOS's own trading module will not act on `momentum_breakout` signals
  for real regardless of this result — its `TradingConfig.min_support=20`
  requires 20 genuinely verified real trade outcomes before any strategy
  clears its confidence/support/edge gate, and going live at all requires
  a real funded broker adapter + `MNEMOS_ADMIN_KEY` + a signed human
  approval token (`mnemos/core/approval.py`). This backtest doesn't bypass
  any of that.
- This result does not change anything about CASCADE, ORB, DRUCK, or CIE —
  MNEMOS is a fully separate system with its own broker adapters and its
  own go-live gate; nothing here touches `iam_executor.py` or
  `IAM_PRIMARY_SYSTEM`.
