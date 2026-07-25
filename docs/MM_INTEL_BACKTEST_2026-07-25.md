# SML Market Maker Intelligence v4 — Backtest, 2026-07-25

**Verdict: PROMISING but not proven.** Positive profit factor on 4 of 5 tested
symbols with real trade counts (81-92 trades each, not a thin sample) — the
best all-around result of the newer Pine scripts backtested this week,
alongside SR-Matrix. This is one window with zero parameter tuning, and it
carries one caveat that matters more than any of the others: **this script
is explicitly labeled a "0DTE" tool, and this backtest did not model options
at all.**

## Method

- Engine: `mm_intel_engine.py` (Python port of `indicators/SML_Market_Maker_Intelligence_v4.pine`), all Pine defaults, no tuning.
- Harness: `tests/backtest_mm_intel.py` — trades on the engine's own entry (`BUY`/`SELL`) and exit (`EXIT_STOP`/`EXIT_RESOLVED`) events from `compute_series()`'s invalidation state machine, one position at a time, directional %-move on the underlying (no options premium/theta/leverage modeled — see caveats).
- Data: real 5-minute bars, SPY/QQQ/IWM/NVDA/TSLA, 2026-06-01 to 2026-07-24, regular session, via Robinhood MCP `get_equity_historicals` (same real-data channel used for the DRUCK/CIE/Breakout backtests — this sandbox has no direct market-data network access, Robinhood MCP is a separate, working channel). ~2,964 bars per symbol, no synthetic/interpolated bars used.
- A bug was found and fixed while porting the Pine script to Python (invalidation state machine self-resolved every entry on the same bar it opened) — see `mm_intel_engine.py`'s module docstring for detail. The Pine script itself was left as-submitted; the Python engine carries the fix and is the source of truth for this backtest.

## Results

| Symbol | Trades | Win % | Profit Factor | Return | Buy & Hold | Exits (resolved / stopped) |
|--------|-------:|------:|---------------:|-------:|-----------:|:---------------------------|
| SPY    | 81 | 45.7% | 1.15 | **+1.54%**  | -2.23%  | 55 / 26 |
| QQQ    | 86 | 43.0% | 1.50 | **+9.03%**  | -7.29%  | 56 / 30 |
| IWM    | 92 | 46.7% | 1.13 | **+1.97%**  | +1.17%  | 64 / 28 |
| NVDA   | 84 | 42.9% | 0.89 | -3.53%      | -5.06%  | 60 / 24 |
| TSLA   | 91 | 40.7% | 1.69 | **+19.53%** | -26.23% | 66 / 25 |

4 of 5 symbols show a real profit factor above 1.0 and beat their own
buy-and-hold over the same window; NVDA is the one loser (PF 0.89), though
it still loses less than buy-and-hold did. Win rates cluster in the low-to-
mid 40s across every symbol, so the edge (where it exists) comes from
win/loss size asymmetry (the ATR-based invalidation distance), not from
being right more often than wrong — consistent with the engine's own
design (an inventory-stress thesis that either resolves favorably or gets
stopped at a fixed ATR multiple).

## Why this is "promising," not "proven"

- **One window, zero tuning.** ~38 trading days, June-July 2026, one regime. Same caveat class as every other engine's first backtest in this repo — real evidence for this window, not proof the strategy always wins.
- **No options modeled, despite this being a 0DTE-labeled tool.** The Pine script's own tooltip says "Optimized for high-velocity 0DTE response" and its dashboard talks about calls/puts — but this backtest traded the *underlying's* directional %-move, exactly like `breakout_engine.py`/`druck_engine.py` do. Real 0DTE options decay (theta) extremely fast intraday; a directional move that looks profitable on the underlying could easily be a loss once real option premium, theta burn, and bid/ask spread are priced in. **This backtest says nothing about actual 0DTE options P&L** — it only tells you the underlying's directional signal has real edge on this window, which is a necessary but not sufficient condition for the options version to work.
- **No slippage or commissions modeled**, same as every backtest in this repo to date.
- **Gamma-pressure/strike-magnet component is a disclosed proxy** (round-number grid + volume ratio), not real per-strike open interest — same proxy class as `SML_Gamma_Pin_v6.pine`. It contributes to the entry gate (`gamma_critical`) but isn't separately validated here.
- **Exit is symmetric and mechanical** (ATR-multiple stop, or inventory z-score crossing back through zero) — there is no profit target beyond that resolution condition, so trades can resolve at a small gain or loss depending on exactly where the crossing happens.

## What would raise this from "promising" to "proven"

- A second, non-overlapping window (different months/regime) showing the same sign and rough magnitude of edge.
- A real options-aware backtest (actual 0DTE contract pricing, theta decay, spread) instead of the underlying %-move proxy — this is the single biggest gap given the tool's own stated purpose.
- Sensitivity testing across the `z_critical`/`gamma_thresh`/`inv_stop_mult` parameter space to confirm the edge isn't a fragile artifact of the Pine defaults.

## Status

Not wired to `iam_executor` or any scanner — this build stopped at "port +
backtest + honest verdict" per the operator's explicit scope. `IAM_PAPER_MODE`
is unaffected either way. If a live-paper wiring pass is wanted next (same
pattern as DRUCK/CIE/Breakout/SR-Matrix), that's a separate, explicit ask.
