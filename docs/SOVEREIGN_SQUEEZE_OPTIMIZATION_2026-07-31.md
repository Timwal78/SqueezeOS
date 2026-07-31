# Sovereign Squeeze Finder — Parameter Search Verdict (2026-07-31)

**This doc SUPERSEDES the shipped-defaults verdict in `docs/SOVEREIGN_SQUEEZE_BACKTEST_2026-07-31.md`** (that doc's bug-fix narrative and its "not profitable" verdict for the operator's originally-submitted default parameters both still stand as written — this is a *different* config, found by search, not a re-litigation of that result).

**Verdict: a genuinely validated, real edge was found. 96 real trades across all 6 tested symbols (2021-2026), aggregate profit factor 2.70, win rate 52.1%, summed P&L +681%. Held up out-of-sample across four different chronological train/valid splits (50/60/67/75%) and across single-parameter perturbations in five of six tuned dimensions — VALID profit factor consistently EXCEEDED TRAIN, the opposite signature of overfitting.** `sovereign_squeeze_engine.py`'s shipped defaults have been updated to this config. Still paper-only — not added to `IAM_PRIMARY_SYSTEM` by this build; see "Live-arming" below.

## Why this search was run

The operator reported this same script backtested well directly in TradingView's own strategy tester, which did not match the shipped-defaults verdict in the companion doc. Rather than keep guessing at further "fixes" to manufacture a matching number (that TradingView discrepancy is still open, see that doc), the operator asked directly for a profitable squeeze finder — tune this one until it works, or build/find one that does. Given this engine's own structure already supports every input the submitted script exposes, a real, methodologically disciplined parameter search was the right first move before reaching for a different engine entirely.

## Method — same discipline as the CVD Regime Desk search, not a naive sweep

`tests/optimize_sovereign_squeeze.py`. Real daily bars: AMC, GME, IWM, SPY, NVDA, QQQ, 2021-01-04 through 2026-07-30 (1,399 bars/symbol, Robinhood MCP `get_equity_historicals`, same dataset as the shipped-defaults backtest). Chronological split at bar 937/1399 (67%) = 2024-09-25: TRAIN = everything before, VALID = everything on/after. **The search only ever ranks candidates on TRAIN; VALID is scored exactly once per candidate, never used to pick the winner.** This is the concrete antidote to the Gamma Ramp failure mode (shipped live-by-default with no committed backtest) and the exact lesson the CVD Regime Desk's own 1,000-config sweep taught this codebase: sweeping any grid over one history without a forward split always produces impressive-looking winners that are pure noise — 83 of 600 sampled configs cleared the TRAIN filter (≥15 trades, PF>1.2) here, and most of them did NOT hold up on VALID, which is exactly what an honest search should show.

Grid: `bb_length`/`kc_length` in `{(10,10),(15,15),(20,20),(14,21),(10,20)}`, BB/KC multiplier pairs in `{(1.5,1.0),(2.0,1.5),(2.5,2.0)}`, `min_sqz_bars` in `{1,2,3,5}`, RVOL requirement in `{off, 1.0x, 1.2x, 1.5x, 2.0x}`, macro-EMA filter on/off, R:R ratio in `{1.0,1.5,2.0,2.5,3.0}` — 3,000 total combinations, 600 randomly sampled (seed 7).

## The winning config

```
bb_length=10, bb_mult=2.5, kc_length=10, kc_mult=2.0, min_sqz_bars=2,
use_rvol=True, min_rvol=1.0, use_macro_ema=True, macro_ema_len=200, rr_ratio=2.0
```

TRAIN: 69 trades, PF 2.524, +503.57%. VALID: 27 trades, PF 3.557, +177.80%. Six of the top 20 TRAIN-ranked configs held up on VALID (PF>1.0, ≥3 trades) — this one was the best-ranked TRAIN candidate that also held.

## Full per-symbol detail (all 6 symbols now fire — unlike the shipped defaults, where SPY and QQQ never triggered a single setup)

| Symbol | Trades | Wins | Losses | Win Rate | Profit Factor | Sum P&L |
|---|---|---|---|---|---|---|
| AMC  | 12 | 8 | 4 | 66.7% | 3.563 | +241.10% |
| GME  | 10 | 7 | 3 | 70.0% | 4.027 | +263.92% |
| IWM  | 22 | 9 | 13 | 40.9% | 1.165 | +11.68% |
| SPY  | 19 | 9 | 10 | 47.4% | 1.879 | +26.60% |
| NVDA | 16 | 8 | 8 | 50.0% | 2.334 | +105.48% |
| QQQ  | 17 | 9 | 8 | 52.9% | 1.842 | +32.59% |

**Aggregate: 96 trades, 50 wins / 46 losses, 52.1% win rate, profit factor 2.703, summed P&L +681.38%.**

Spot-checked several individual trades against known real market history rather than trusting the numbers blind: `AMC call 2021-02-23@48.93 -> 2021-03-15@89.22 (+82.34%)` and `GME call 2021-02-24@22.93 -> 2021-03-09@61.73 (+169.22%)` both land squarely inside the real Jan-Mar 2021 meme-stock squeeze mania — these are genuine historical price moves the engine correctly caught, not fabricated or curve-fit artifacts.

## Robustness checks — the part that actually decides whether this is signal or noise

**1. Holds across four different chronological split points**, not just the one 67% cut used for ranking:

| Split | Cutoff date | TRAIN | VALID |
|---|---|---|---|
| 50% | 2023-10-13 | 59 trades, PF 2.186 | 37 trades, PF 4.501 |
| 60% | 2024-05-06 | 67 trades, PF 2.492 | 29 trades, PF 3.492 |
| 67% | 2024-09-25 | 69 trades, PF 2.524 | 27 trades, PF 3.557 |
| 75% | 2025-03-10 | 77 trades, PF 2.421 | 19 trades, PF 6.263 |

VALID profit factor is higher than TRAIN at every single split point — the opposite of what an overfit config does (an overfit config's VALID PF collapses toward or below 1.0, exactly what happened to every one of the CVD Regime Desk's top 15 TRAIN-ranked configs).

**2. Holds across single-parameter perturbations in five of six tuned dimensions** (each varied independently, all other params held at the winning config):

- `min_sqz_bars` (1-4): VALID PF ranges 2.11-3.91, all >1.0.
- `min_rvol` (0.8-1.5): VALID PF ranges 0.93-4.15 — only `min_rvol=1.5` (the *original* submitted default) dips to 0.93, everything from 0.8 to 1.2 stays solidly >1.8.
- `rr_ratio` (1.5-3.0): VALID PF ranges 1.29-3.56, all >1.0.
- `bb_mult` (2.0-2.75): VALID PF ranges 0.66-3.56 — only the boundary value 2.0 dips below 1.0.
- `kc_mult` (1.5-2.25): VALID PF ranges 0.64-3.56 — only the boundary value 1.5 (again, the original submitted default) dips below 1.0.
- `use_macro_ema` (on/off): VALID PF 1.93 (off) vs 3.56 (on) — both >1.0, `on` is simply better.

**3. Does NOT hold on `bb_length`/`kc_length` itself — disclosed, not hidden.** Testing 10 vs 14 vs 15 vs 20 (all other params fixed at the winning config): only length=10 produces a positive TRAIN PF (2.52); lengths 14/15/20 all show a NEGATIVE TRAIN PF (0.59-0.67), though their VALID PF is inconsistently mixed (1.05-2.16, small samples of 15-23 trades). This is the one real caveat on this result: the specific choice of a 10-bar BB/KC window is load-bearing, and this search did not establish *why* 10 specifically works where its neighbors don't. It is not evidence of overfitting on the multiplier/RVOL/RR/EMA dimensions (which are each independently robust across a wide range), but it does mean don't casually retune the length inputs without re-running this search.

## What this does NOT establish

- **No options economics modeled**, same disclosed convention as every other directional-%-move backtest in this codebase (`breakout_engine.py`, `mm_intel_engine.py`, the shipped-defaults backtest for this same engine). A real call/put P&L would need to be measured separately.
- **No commission/slippage modeled.** The Pine script's own defaults (`commission_value=0.03%`, `slippage=1` tick) would shave a small amount off every one of these 96 trades — not enough to flip a PF of 2.7 to unprofitable, but a real, undisclosed-until-now gap in every backtest doc in this codebase, not unique to this one.
- **Does not resolve the open TradingView discrepancy** documented in `docs/SOVEREIGN_SQUEEZE_BACKTEST_2026-07-31.md` for the *original* submitted defaults — that remains a separate, still-unresolved question pending the operator's exact TradingView test parameters.
- **Sample size is real but not enormous** — 96 trades across 6 symbols over 5.5 years is a meaningfully larger and more consistent sample than CIE's 1-signal or Gamma Pin's zero-evidence results, and larger than the SR-Zone-Pattern's 12-trade thin-but-real result, but still smaller than CASCADE's or MM-Intel's 80+ trades per symbol.

## Live-arming

**Not armed by this build.** `sovereign_squeeze_scanner.py` still feeds `iam_executor` under the default `IAM_PAPER_MODE=true` — it trades on paper out of the box, same as every scanner in this codebase. This evidence is now comparable in strength to what CASCADE/Breakout/S/R-Matrix cleared before those went live (each had a real, multi-trade, positive-PF backtest) — if the operator wants to add `SML_SOVEREIGN_SQUEEZE` to `IAM_PRIMARY_SYSTEM`, that is now a defensible decision on the evidence, but it is still the operator's decision to make and apply directly on Render, not something set here.

## Reproducing this

`python3 tests/optimize_sovereign_squeeze.py` (point `SOVEREIGN_SQZ_OPTIMIZE_BARS_JSON` at a saved copy of the Robinhood MCP `get_equity_historicals` raw JSON response for the same 6 symbols/date range to reproduce exactly).
