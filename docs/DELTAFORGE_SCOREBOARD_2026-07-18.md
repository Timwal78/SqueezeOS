# DeltaForge (SM-DF-FLAG v2.1) — First Real Backtest Scoreboard (2026-07-18)

First measured performance evidence for the ScriptMaster DeltaForge Flagship strategy
(`indicators/ScriptMaster_DeltaForge_Flagship_v6.pine`), run by the operator in TradingView's
Strategy Tester and reported via screenshots the same day the strategy merged (PR #351).
Recorded here so the results survive chat history — per the engine-scoreboard discipline
(`docs/ENGINE_SCOREBOARD_2026-07-17.md`): no performance claim without a run behind it.

**Test conditions (comparable set):** 20-minute chart, Jul 1 2022 → Jul 17 2026 (4 years),
$1M initial capital, default strategy settings (8% equity/trade, 0.1% commission, no slippage
modeled), long + short.

## Results — 20m / 4y comparable set

| Symbol | Profit factor | Total return | Max DD | Win rate | Trades | Verdict |
|--------|--------------|--------------|--------|----------|--------|---------|
| HOOD | **1.941** | **+5.31%** | 1.13% | 39.7% (23/58) | 58 | ✅ Earner — steadily rising curve from mid-2024, at new equity highs at test date |
| XRT  | **1.904** | +1.50% | 0.40% | 44.7% (21/47) | 47 | ✅ Earner — smooth low-drawdown grind |
| SPY  | 1.597 | +0.59% | 0.30% | 42.9% (15/35) | 35 | ➖ Survives, barely earns; buy-and-hold crushed it |
| QQQ  | 1.154 | +0.28% | 0.86% | 35.7% (15/42) | 42 | ➖ Peaked Apr 2025, gave most of it back |
| IWM  | 0.92  | −0.18% | 0.68% | 29.8% (14/47) | 47 | ❌ Slight loser |
| AMC  | 0.847 | −1.20% | 2.42% | 27.5% (11/40) | 40 | ❌ Worst of the set |

### Non-comparable extra run (recorded for the cautionary tale)

| Symbol | Timeframe / period | Profit factor | Return | Max DD | Win rate |
|--------|--------------------|---------------|--------|--------|----------|
| AMC | 5m / 1y (Jul 2025–Jul 2026) | 2.278 | +2.84% | 0.53% | 42.5% (17/40) |

**The AMC lesson (winner's-curse caught in the wild):** at 5m over one recent year, AMC
looked like the star (PF 2.278). At the comparable 20m/4y test, AMC is the *worst* symbol in
the set — money-losing, lowest win rate, largest drawdown. The short window happened to catch
AMC's one favorable recent regime and missed two years of grinding decline. Do not select
symbols from short flattering windows; this is exactly the selection-bias failure mode the
LAUREATE validation rules (doc Appendix A / rule 13) exist to prevent.

## Findings

1. **The edge lives in liquid, retail-flavored, trending names** — HOOD and XRT earn;
   deep-meme chop (AMC) and broad small-caps (IWM) lose; the big efficient indices (SPY, QQQ)
   roughly break even. The "high-distortion meme names" hypothesis from the initial AMC run
   is falsified on the comparable set.
2. **HOOD cross-engine confirmation:** HOOD was also a winner in the 2026-07-17 engine
   scoreboard (it's in the recommended `IAM_SYMBOL_ALLOWLIST`). Two independent engines
   earning the same symbol is meaningfully stronger evidence than either alone.
3. **Profit-factor-vs-win-rate shape is healthy where it earns:** HOOD/XRT earn with ~40-45%
   win rates and winners ~2x losers — the convexity/R-multiple exit design working as
   intended, not a fragile high-win-rate profile.
4. **Absolute returns are modest by construction** (heavy filters, conservative sizing,
   40-58 trades in 4 years). This is a selective overlay, not a compounding machine — no
   "doubling" claims are supported by any of these numbers.

## Caveats

- TradingView backtests model commission (0.1%) but not slippage; live fills will be worse.
- 35-58 trades per symbol is a moderate sample — enough to rank, not enough for precision.
- Single strategy-settings vector (defaults); no parameter search was done (good for
  avoiding overfit, but the defaults are also untuned).
- Not yet tested at 20m/4y: NVDA, GME, MSTR, TSLA, PLTR.

## Recommended next steps (awaiting operator decision — nothing applied)

1. Run NVDA at 20m/4y to complete the July-17 allowlist overlap.
2. If DeltaForge is ever wired into live paper execution via its webhook bridge
   (`system: SML_DELTAFORGE`), gate entries to the earners only — HOOD, XRT — via
   `IAM_SYMBOL_ALLOWLIST`-style filtering, and explicitly exclude AMC/IWM despite the
   strategy having been demoed on AMC.
3. Re-measure after 60-90 days of paper signals through `performance_tracker.py` before any
   live-arming conversation. Paper mode remains the standing default per the 2026-07-17
   operator decision.
