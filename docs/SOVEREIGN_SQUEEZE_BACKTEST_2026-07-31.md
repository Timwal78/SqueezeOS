# Sovereign Squeeze Finder — Backtest Verdict (2026-07-31)

**Verdict: NOT profitable as-configured, on a thin sample. 9 completed trades across 4 symbols over 5.5 years (2021-01–2026-07); SPY and QQQ never triggered a single setup. Aggregate profit factor 0.34, summed P&L -104.32% across the 9 trades that did fire.** Built and wired to PAPER trading only (`sovereign_squeeze_scanner.py`, `/api/sovereign-squeeze`) — same as every other new scanner in this codebase. **Do not add `SML_SOVEREIGN_SQUEEZE` to `IAM_PRIMARY_SYSTEM`** — same bar ORB/DRUCK/AETHER/RSI-ML didn't clear.

## ⚠️ Correction (same day): a real bug in the momentum term was found and fixed after the operator reported a materially better result from TradingView's own strategy tester on this script. The verdict above is POST-FIX. It does not match the operator's reported TradingView result — see "Open discrepancy" below, which is not yet resolved.

The first version of this doc (11 trades, PF 0.31) was built on `sovereign_squeeze_engine.py`'s original port of the momentum term, which had a real bug: Pine's `source - math.avg(math.avg(ta.highest(high,kcLength), ta.lowest(low,kcLength)), ta.sma(close,kcLength))` is a SERIES expression — at every bar, `ta.highest`/`ta.lowest`/`ta.sma` each use their OWN rolling `kcLength`-bar window ending at that bar, producing a per-bar deviation value. `ta.linreg(that_series, kcLength, 0)` then regresses the trailing `kcLength` values of that already-per-bar-computed series.

The original port instead computed a single "mid" reference level using only the CURRENT bar's highest-high/lowest-low/sma, then subtracted that one constant from every raw close in the trailing window before regressing — a materially different quantity (`close[j] - constant` instead of the correct per-bar `dev[j]`), which distorts the momentum term's slope. Fixed in `compute_series()` by building the real `dev[]` series first (rolling highest/lowest/sma computed at every bar, matching Pine's per-bar evaluation) and regressing the trailing window of that series. Regression-tested via the existing coil→breakout/breakdown fixtures in `tests/test_sovereign_squeeze_engine_smoke.py`, which still pass post-fix.

**This was a real, worth-fixing bug regardless of the backtest outcome — but fixing it did NOT flip the verdict to profitable.** Re-running the identical real-data backtest post-fix actually reduced the trade count (11 → 9, two of AMC's/GME's previously-winning trades no longer qualify as setups under the corrected momentum term) and left the aggregate profit factor essentially unchanged (0.31 → 0.34, still solidly unprofitable).

## Open discrepancy — NOT resolved, needs the operator's exact TradingView test parameters

The operator reported this script backtested well directly in TradingView's own strategy tester. That has not been reproduced here on the same real data (AMC/GME/IWM/SPY/NVDA/QQQ daily bars, 2021-01–2026-07, shipped default parameters) with either the pre-fix or post-fix engine. Rather than keep guessing at further code changes to manufacture a match — which would risk exactly the kind of curve-fitting this codebase's CVD Regime Desk backtest explicitly warns against — the honest next step needs specifics from the operator's actual TradingView run: which symbol(s), what date range, what chart timeframe, and whether any input (BB/KC length, RVOL threshold, macro EMA on/off, R:R ratio) was changed from the script's own defaults. Candidate explanations not yet ruled out:

- **A different symbol/date range/timeframe than tested here.** TradingView's strategy tester only backtests the currently-loaded chart's visible/available history on whatever symbol and timeframe is active — if that was a different, more favorable stock or a shorter recent window (or an intraday chart), it would not be the same test as this doc's 5.5-year daily run across 6 symbols.
- **Fill-timing semantics.** This engine assumes a fill at the signal bar's own close (`entry_price = closes[i]`). Pine's `strategy.entry()` without `process_orders_on_close=true` typically fills at the NEXT bar's open by default — a real, unverified divergence from what's built here that could move numbers in either direction.
- **Commission/slippage.** The Pine script itself configures `commission_value=0.03%` and `slippage=1` tick — this backtest (like every other directional-%-move backtest in this codebase, e.g. `breakout_engine.py`) does not model either. Since commission/slippage only ever hurts a strategy, this can't explain a WORSE result here than in TradingView; it's mentioned for completeness, not as the answer.

**Until the operator supplies which exact run produced the good TradingView result, this verdict stands as measured: not profitable as-configured, on the real data available here.**

## Why this was built

Operator pasted a Pine v6 script ("ScriptMaster - Sovereign Squeeze Setup Finder v6") — a classic TTM-squeeze-style compression/release strategy: Bollinger Bands collapsing inside a Keltner Channel (squeeze ON), then expanding back outside (squeeze OFF/"fired"), gated by a linear-regression momentum term accelerating in the setup's direction, a relative-volume spike (≥1.5x the 20-bar volume EMA), and an optional 200-EMA trend filter. This is a genuinely different mechanic from every other squeeze-adjacent engine already in this codebase — not a duplicate of `squeeze_analyzer.py`'s price/volume ignition score or `squeeze_fuel_engine.py`'s FTD/short-volume/gamma composite. Ported to `sovereign_squeeze_engine.py`, same pattern as every other engine here (Pine is a visual, Python is the single source of truth).

## Method

Real, unmodified `compute_series()` full position state machine (one open position at a time, entry at the setup bar's close, target/stop checked on each subsequent bar's close, no lookahead) over real daily bars: AMC, GME, IWM, SPY, NVDA, QQQ, 2021-01-04 through 2026-07-30 (1,399 real daily bars each, Robinhood MCP `get_equity_historicals`, split-adjusted). Shipped defaults used throughout — no tuning attempted: `bb_length=20/mult=2.0`, `kc_length=20/mult=1.5`, `min_sqz_bars=3`, `min_rvol=1.5`, `use_macro_ema=True/len=200`, `rr_ratio=2.5`.

## Results (post-fix)

| Symbol | Bars | Trades | Wins | Losses | Win Rate | Profit Factor | Sum P&L | Buy & Hold |
|---|---|---|---|---|---|---|---|---|
| AMC  | 1399 | 1 | 0 | 1 | 0.0%   | 0.000 | -65.29% | -78.3% |
| GME  | 1399 | 4 | 0 | 4 | 0.0%   | 0.000 | -78.76% | +407.4% |
| IWM  | 1399 | 3 | 1 | 2 | 33.3%  | 0.957 | -0.56%  | +51.2% |
| NVDA | 1399 | 1 | 1 | 0 | 100.0% | inf   | +40.29% | +1387.3% |
| SPY  | 1399 | 0 | — | — | — | — | — | +101.1% |
| QQQ  | 1399 | 0 | — | — | — | — | — | +121.0% |

**Aggregate across all 6 symbols: 9 trades, 2 wins, 7 losses, 22.2% win rate, profit factor 0.34, summed P&L -104.32%.**

Trade-level detail (all 9):

```
AMC  put  2024-04-01@3.14   -> 2024-05-13@5.19   -65.29%  (EXIT_STOP)
GME  call 2021-11-02@51.75  -> 2021-12-03@43.10  -16.72%  (EXIT_STOP)
GME  put  2022-12-07@22.26  -> 2024-05-13@30.45  -36.79%  (EXIT_STOP)
GME  call 2024-12-26@32.99  -> 2025-01-14@27.88  -15.49%  (EXIT_STOP)
GME  call 2026-04-15@24.79  -> 2026-05-12@22.37   -9.76%  (EXIT_STOP)
IWM  put  2021-07-08@221.70 -> 2021-10-25@229.57  -3.55%  (EXIT_STOP)
IWM  call 2024-07-11@210.68 -> 2024-11-06@237.22 +12.60%  (EXIT_TARGET)
IWM  put  2025-04-03@189.65 -> 2025-05-12@207.87  -9.61%  (EXIT_STOP)
NVDA call 2021-08-23@21.96  -> 2021-11-08@30.80  +40.29%  (EXIT_TARGET)
```

## The finding that actually matters

Two things are true at once, and neither should get lost:

1. **This is a genuinely rare setup.** The compound gate (squeeze must hold ≥3 bars, THEN release, AND momentum must already be accelerating in the release direction, AND volume must be spiking 1.5x+, AND price still has to sit on the correct side of a 200-day EMA) legitimately almost never aligns on SPY/QQQ across 5.5 years of daily bars. This is not a bug — it's a direct, mechanical consequence of stacking that many independent conditions on a single-timeframe daily signal.
2. **Where it did fire, it mostly lost money.** 7 of 9 completed trades hit the stop, not the target. AMC and GME's completed trades are a clean sweep of losses; IWM is closest to breakeven; NVDA's single trade is the one clear winner.

This is a real, measured result on real data with the corrected math — not enough trades on any single symbol to be statistically definitive, but a consistent enough negative skew in aggregate to say the setup, as configured, does not have a demonstrated edge on daily bars for this symbol set and window.

## Standing limitations

- **No options economics modeled.** Same disclosed convention as `breakout_engine.py`/`druck_engine.py`/`mm_intel_engine.py` — this backtest trades the underlying's directional %-move to entry/target/stop, not modeled call/put premium, spread, or theta.
- **Untuned.** Every parameter is the script's own submitted default. A parameter sweep was not run — per the CVD Regime Desk's lesson in CLAUDE.md, sweeping without a chronological train/valid split reliably manufactures a false positive, so this wasn't attempted casually. If this is revisited, use `tests/optimize_cvd_regime.py`'s split methodology, not a naive sweep.
- **Daily bars only.** Not tested on any intraday timeframe.
- **Fill-timing assumption not verified against Pine's real default** (see "Open discrepancy" above) — this is the single most likely source of the reported gap with TradingView's own backtest and is flagged as unresolved, not silently assumed correct.
- **The Pine script's own webhook alert JSON schema (`action`/`symbol`/`type`/`score`/`stop`/`target`) does not match the real bridge contract** (`passphrase`/`system`/`EXECUTE_LONG`/`EXECUTE_SHORT`) — irrelevant to this engine's live wiring since it runs natively in Python, not via TradingView alerts.

## What this build does NOT do

- **No live-arming flag was touched.** `sovereign_squeeze_scanner.py` feeds `iam_executor` under the exact same `IAM_PAPER_MODE=true` default as every other engine — it trades on paper out of the box. Nobody has added `SML_SOVEREIGN_SQUEEZE` to `IAM_PRIMARY_SYSTEM`, and this backtest is not a reason to.
- **This does not manufacture a positive verdict to match what was reported from TradingView.** The bug that was found and fixed was real and worth fixing on its own merits; it happened not to change the conclusion. If the operator's TradingView result turns out to reflect a different symbol/timeframe/date range/settings, that's a different, reproducible test this doc will be updated (or superseded by a new dated doc) to reflect once those specifics are known — not before.
