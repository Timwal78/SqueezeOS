# Sovereign Squeeze Finder — Backtest Verdict (2026-07-31)

**Verdict: NOT profitable as-configured, on a thin sample. 11 completed trades across 6 symbols over 5.5 years (2021-01–2026-07); 3 of 6 symbols (SPY, NVDA, QQQ) never triggered a single setup. Aggregate profit factor 0.31, summed P&L -111.66% across the 11 trades that did fire.** Built and wired to PAPER trading only (`sovereign_squeeze_scanner.py`, `/api/sovereign-squeeze`) — same as every other new scanner in this codebase. **Do not add `SML_SOVEREIGN_SQUEEZE` to `IAM_PRIMARY_SYSTEM`** — same bar ORB/DRUCK/AETHER/RSI-ML didn't clear.

## Why this was built

Operator pasted a Pine v6 script ("ScriptMaster - Sovereign Squeeze Setup Finder v6") — a classic TTM-squeeze-style compression/release strategy: Bollinger Bands collapsing inside a Keltner Channel (squeeze ON), then expanding back outside (squeeze OFF/"fired"), gated by a linear-regression momentum term accelerating in the setup's direction, a relative-volume spike (≥1.5x the 20-bar volume EMA), and an optional 200-EMA trend filter. This is a genuinely different mechanic from every other squeeze-adjacent engine already in this codebase — not a duplicate of `squeeze_analyzer.py`'s price/volume ignition score or `squeeze_fuel_engine.py`'s FTD/short-volume/gamma composite. Ported directly to `sovereign_squeeze_engine.py`, same pattern as every other engine here (Pine is a visual, Python is the single source of truth), and no bugs were found in the submitted script's math during the port.

## Method

`scripts/_backtest_sovereign_squeeze.py` (throwaway, not committed as production wiring — same convention as `scripts/_rh_to_druck_csv.py`) drives the real, unmodified `compute_series()` full position state machine (one open position at a time, entry at the setup bar's close, target/stop checked on each subsequent bar's close, no lookahead) over real daily bars: AMC, GME, IWM, SPY, NVDA, QQQ, 2021-01-04 through 2026-07-30 (1,399 real daily bars each, Robinhood MCP `get_equity_historicals`, split-adjusted). Shipped defaults used throughout — no tuning attempted: `bb_length=20/mult=2.0`, `kc_length=20/mult=1.5`, `min_sqz_bars=3`, `min_rvol=1.5`, `use_macro_ema=True/len=200`, `rr_ratio=2.5`.

## Results

| Symbol | Bars | Trades | Wins | Losses | Win Rate | Profit Factor | Sum P&L | Buy & Hold |
|---|---|---|---|---|---|---|---|---|
| AMC  | 1399 | 2 | 1 | 1 | 50.0% | 0.348 | -42.55% | -78.3% |
| GME  | 1399 | 6 | 1 | 5 | 16.7% | 0.179 | -68.55% | +407.4% |
| IWM  | 1399 | 3 | 1 | 2 | 33.3% | 0.957 | -0.56% | +51.2% |
| SPY  | 1399 | 0 | — | — | — | — | — | +101.1% |
| NVDA | 1399 | 0 | — | — | — | — | — | +1387.3% |
| QQQ  | 1399 | 0 | — | — | — | — | — | +121.0% |

**Aggregate across all 6 symbols: 11 trades, 3 wins, 8 losses, 27.3% win rate, profit factor 0.31, summed P&L -111.66%.**

Trade-level detail (all 11):

```
AMC  put 2023-07-24@58.50 -> 2023-07-27@45.20  +22.73%  (EXIT_TARGET)
AMC  put 2024-04-01@3.14  -> 2024-05-13@5.19   -65.29%  (EXIT_STOP)
GME  call 2021-11-02@51.75 -> 2021-12-03@43.10 -16.72%  (EXIT_STOP)
GME  put  2022-12-07@22.26 -> 2024-05-13@30.45 -36.79%  (EXIT_STOP)
GME  call 2024-12-26@32.99 -> 2025-01-14@27.88 -15.49%  (EXIT_STOP)
GME  call 2025-05-14@28.73 -> 2025-05-23@33.03 +14.97%  (EXIT_TARGET)
GME  put  2025-09-10@24.37 -> 2025-09-15@25.53  -4.76%  (EXIT_STOP)
GME  call 2026-04-15@24.79 -> 2026-05-12@22.37  -9.76%  (EXIT_STOP)
IWM  put  2021-07-08@221.70 -> 2021-10-25@229.57 -3.55%  (EXIT_STOP)
IWM  call 2024-07-11@210.68 -> 2024-11-06@237.22 +12.60%  (EXIT_TARGET)
IWM  put  2025-04-03@189.65 -> 2025-05-12@207.87  -9.61%  (EXIT_STOP)
```

## The finding that actually matters

Two things are true at once, and neither should get lost:

1. **This is a genuinely rare setup.** The compound gate (squeeze must hold ≥3 bars, THEN release, AND momentum must already be accelerating in the release direction, AND volume must be spiking 1.5x+, AND — for the 3 symbols that trend strongly bull — price still has to sit on the correct side of a 200-day EMA) legitimately almost never aligns on SPY/NVDA/QQQ across 5.5 years of daily bars. This is not a bug — it's a direct, mechanical consequence of stacking that many independent conditions on a single-timeframe daily signal.
2. **Where it did fire, it lost money.** 8 of 11 completed trades hit the stop, not the target, and the profit factor on the two symbols with enough trades to compute one (AMC, GME) is well below 1.0. IWM's single-symbol PF (0.957) is closest to breakeven but still negative in aggregate P&L.

Both facts point the same direction: this is not a case of "the sample is too thin to conclude anything" (CIE's 1-signal outcome) — 11 real trades with a consistently negative skew is enough to say the setup, as configured, does not have a demonstrated edge on daily bars. It is also not as clearly dead as ORB/AETHER's catastrophic losses — closer to DRUCK's "flat-to-negative, no tuning attempted" verdict.

## Standing limitations

- **No options economics modeled.** Same disclosed convention as `breakout_engine.py`/`druck_engine.py`/`mm_intel_engine.py` — this backtest trades the underlying's directional %-move to entry/target/stop, not modeled call/put premium, spread, or theta. The Pine script's own alert payload proposes CALL/PUT execution; a real options P&L would need to be measured separately before that framing could be trusted.
- **Untuned.** Every parameter is the script's own submitted default. A parameter sweep was not run — per the CVD Regime Desk's lesson in CLAUDE.md, sweeping without a chronological train/valid split reliably manufactures a false positive, so this wasn't attempted casually. If this is revisited, use `tests/optimize_cvd_regime.py`'s split methodology, not a naive sweep.
- **Daily bars only.** The squeeze/RVOL/momentum mechanic might behave differently on an intraday timeframe (the same class of caveat already flagged for IMO/RSI-ML/Gamma Ramp) — not tested here.
- **The Pine script's own webhook alert JSON schema (`action`/`symbol`/`type`/`score`/`stop`/`target`) does not match the real bridge contract** (`passphrase`/`system`/`EXECUTE_LONG`/`EXECUTE_SHORT`, same JSON contract as the IMO/ORB/DRUCK/CIE/CVD v6 bridges) — same disclosed mismatch class as RSI-ML/Trade Desk v3. Irrelevant here since this engine runs natively in Python via `sovereign_squeeze_scanner.py`, not via TradingView alerts, but flagged so nobody wires a raw TradingView alert to this script expecting it to reach the executor.

## What this build does NOT do

- **No live-arming flag was touched.** `sovereign_squeeze_scanner.py` feeds `iam_executor` under the exact same `IAM_PAPER_MODE=true` default as every other engine — it trades on paper out of the box. Nobody has added `SML_SOVEREIGN_SQUEEZE` to `IAM_PRIMARY_SYSTEM`, and this backtest is not a reason to.
- **If a longer window or a tuned parameter set is ever tested, add a new dated doc** rather than editing these numbers — same convention the DRUCK/CIE/SR-Matrix docs follow.
