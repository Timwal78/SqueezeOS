# SML-IMO Intraday Backtest — 2026-07-25

Follow-up to `docs/ENGINE_SCOREBOARD_2026-07-17.md`, which explicitly caveated
its IMO numbers: "measured on **daily** bars; it is designed for intraday
(4h/65m). Daily results are a floor, not a verdict." This is that intraday
measurement — real code (`imo_engine.py`, `tests/backtest_imo.py`, both
unmodified), real data, run against the actual designed timeframe.

**Verdict: inconclusive, and notably weaker than the daily proxy suggested —
not a confirmation.** The daily-bar scoreboard's best result (IWM, +40.8% vs
+27.7% buy-and-hold) **flips to a loser on real intraday data** (-3.0% vs
+18.9% B&H). Do not treat the earlier daily-bar numbers as validated by this
run, and do not treat this run as a clean win either — see "Why this isn't
decisive" below.

## Method

- Harness: `tests/backtest_imo.py` (real, unmodified — long-only, next-bar-open
  execution, hard stop at entry×(1-stop%), one position at a time)
- Engine: `imo_engine.py` (single source of truth for IMO math, unmodified)
- Data: real 4-hour bars pulled via the Robinhood MCP (`get_equity_historicals`,
  `interval=4hour`, split-adjusted) for the same 10 symbols as the daily
  scoreboard (SPY/IWM/QQQ/PLTR/HOOD/NVDA/MSTR/TSLA/GME/AMC)
- **Real coverage window: 2025-11-03 to 2026-07-24 (~9 months), 264 real bars
  per symbol.** An initial pull requested 2023-01-01 onward and came back 78%
  synthetic/interpolated gap-fill bars (924 of 1,188) — Robinhood's real
  4-hour history for these symbols only goes back to Nov 2025. Every
  interpolated bar was dropped before running the backtest; only real bars
  were used. This is a real, structural data-availability limit, not a
  choice — no aggregation-from-finer-bars workaround got more real history
  either (a 5-minute pull's ~5,000-bar cap covers roughly 3 months, less
  than the 9 months of real native 4-hour bars already available).

## Results

| Symbol | Trades | Win% | PF | Strat% | B&H% | MaxDD% |
|--------|-------:|-----:|-----:|-------:|-------:|-------:|
| SPY    | 2      | 50.0 | 2.91 | +5.5   | +8.1   | 3.0    |
| QQQ    | 2      | 50.0 | 4.15 | **+9.1** | +8.2 | 3.0    |
| IWM    | 1      | 0.0  | 0.00 | **-3.0** | **+18.9** | 3.0 |
| NVDA   | 2      | 50.0 | 2.11 | +3.1   | -0.6   | 3.0    |
| PLTR   | 5      | 20.0 | 0.23 | -17.0  | -40.4  | 21.2   |
| HOOD   | 5      | 0.0  | 0.00 | -22.4  | -35.5  | 22.4   |
| MSTR   | 3      | 0.0  | 0.00 | -11.0  | -65.6  | 11.0   |
| TSLA   | 2      | 0.0  | 0.00 | -6.8   | -33.3  | 6.8    |
| GME    | 2      | 0.0  | 0.00 | -5.9   | -4.4   | 5.9    |
| AMC    | 1      | 0.0  | 0.00 | -3.0   | -12.4  | 3.0    |

## Why this isn't decisive

- **Trade counts are far too low to trust (1-5 per symbol).** A ~9-month
  window on a 4-hour timeframe with IMO's regime filter simply doesn't
  produce enough real setups to distinguish skill from noise. QQQ's PF 4.15
  is built on 2 trades — one good trade away from a completely different
  number.
- **IWM's reversal is the single most important data point here.** IWM was
  the daily-bar scoreboard's best, most-cited result, explicitly called out
  as "matches SqueezeOS's IWM focus." On real intraday data it's a loser (1
  trade, stopped out, -3.0% vs an environment that was +18.9% B&H) — the
  daily-bar "floor, not a verdict" caveat turned out to matter.
- SPY/QQQ/NVDA are the only symbols with a real edge over this window (2
  wins on 2-4 trades each) — directionally consistent with "IMO does better
  on liquid index/megacap names," same as the daily scoreboard, but on a
  sample too small to call it proven.
- This is one ~9-month window in one regime, bounded by Robinhood's real
  intraday history depth — not a multi-year, multi-regime test the way the
  daily scoreboard was.

## What this does NOT change

- No env vars changed. IMO stays exactly as configured — paper-mode wiring
  via `imo_scanner.py` → `iam_executor` is unaffected.
- **Do not set `IAM_PRIMARY_SYSTEM` to include `SML_IMO` based on this
  result.** The evidence is genuinely mixed, not a green light — same bar
  applied to ORB's and DRUCK's negative verdicts elsewhere in this file:
  real code, real trade logs, real disclosure, not a promoted recommendation
  on a thin sample.
- If IMO's real-money 4h/65m signals accumulate a longer live-paper history
  in production, re-run this backtest with more real bars once Robinhood's
  (or another provider's) history window has grown, rather than trusting
  this 9-month read as final.
