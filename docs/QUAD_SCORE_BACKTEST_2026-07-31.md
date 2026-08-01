# SML Quad-Score Explosive Breakout Finder — Backtest (2026-07-31)

**⚠️ SUPERSEDED by `docs/QUAD_SCORE_OPTIMIZATION_2026-07-31.md`.** This doc's method and its verdict for the operator's *originally-specified* default thresholds both still stand as written below — that shipped-defaults result really was thin and mixed. But `quad_score_engine.py`'s shipped defaults were subsequently changed to a different, TRAIN/VALID-validated config found by a real chronological parameter search (146 trades, PF 1.989, held up across four split points and six perturbed dimensions) — read that doc for the current, evidence-backed verdict. This doc is kept for the bug-fix narrative and as the historical record of the first (unprofitable-on-a-thin-sample) pass.

**Original verdict (superseded): mixed but net positive, on a THIN sample. Not backtest-proven to the same bar as CASCADE/Breakout/S-R Matrix.** Real daily bars, AMC/GME/IWM/SPY/NVDA/QQQ, 2018-01-02 through 2026-07-30 (Robinhood MCP `get_equity_historicals`, split-adjusted, one interpolated bar per symbol dropped — same real-data channel used for every other backtest in this codebase). Shipped-defaults parameters (the exact thresholds from the operator's spec: composite≥70, trend≥50, trigger≥60, temporal≥65 within 10 bars, weekly macro filter), no tuning attempted.

**20 trades across 6 symbols, aggregate profit factor 1.795, 50.0% win rate, summed P&L +51.32%.** AMC never fired a single setup in 8.5 years of real data — its own multi-year post-2021 decline meant the weekly macro filter (Close > Weekly EMA200 AND Weekly ADX > 18) essentially never validated for it.

## Per-symbol detail

| Symbol | Trades | Wins | Losses | Win Rate | Profit Factor | Sum P&L |
|---|---|---|---|---|---|---|
| AMC  | 0 | 0 | 0 | — | — | 0.00% |
| GME  | 4 | 2 | 2 | 50.0% | 1.140 | +4.81% |
| IWM  | 2 | 0 | 2 | 0.0% | 0.000 | -8.65% |
| SPY  | 4 | 1 | 3 | 25.0% | 0.636 | -2.13% |
| NVDA | 6 | 4 | 2 | 66.7% | 4.108 | +39.51% |
| QQQ  | 4 | 3 | 1 | 75.0% | 6.996 | +17.78% |

NVDA and QQQ carry almost the entire positive result; IWM and SPY are both net losers on a small handful of trades.

## Why the sample is so thin

The spec's own gates are genuinely restrictive layered together:
- Composite ≥70 (a 0.25/0.35/0.20/0.20 blend of four already-selective pillar scores)
- Trend ≥50 individually (requires at least EMA20>EMA50, i.e. a real short-term uptrend)
- Trigger ≥60 individually (needs a real momentum-acceleration percentile + breakout/candle confirmation)
- Temporal sequence gate: Compression must have cleared 65 within the 10 bars immediately before entry
- **The weekly macro regime filter is the single biggest reducer of opportunity** — it requires ~4 years of real weekly history just to seed (Weekly EMA_200), and then only validates during a genuinely healthy weekly uptrend (Close > Weekly EMA200 AND Weekly ADX > 18). This is why AMC (persistently weak on the weekly timeframe most of this window) never fired at all, and why the whole 8.5-year window only produced 20 total qualifying setups across 6 symbols.

This is a **selectivity finding, not a losing-strategy finding** — similar in spirit to CIE's "1 signal across 5 symbols" verdict, though this one is net positive rather than inconclusive.

## What this does NOT establish

- **No options economics modeled** — same disclosed convention as every other directional-%-move backtest in this codebase (`breakout_engine.py`, `mm_intel_engine.py`, `sovereign_squeeze_engine.py`). The engine's stop/target are ATR-based (2.0x/4.0x per the spec) applied to the underlying's own move.
- **No commission/slippage modeled.**
- **Sample size is real but small** — 20 trades over 8.5 years across 6 symbols is thinner than CASCADE's or MM-Intel's 80+ trades per symbol, and thinner than Sovereign Squeeze's own validated 96-trade result. It's in the same rough class as SR-Zone-Pattern's 12-trade thin-but-real positive result.
- **No parameter search was run.** These are the operator's exact spec thresholds, unmodified. A TRAIN/VALID search (same discipline as `tests/optimize_sovereign_squeeze.py`/`tests/optimize_cvd_regime.py`) was not attempted here since splitting only 20 trades into train/valid halves would leave too few trades per side to say anything meaningful either way — a search would need a wider symbol universe to be worth running, not a re-slice of this same thin sample.
- **Does not establish whether this composite/gate design generalizes beyond these 6 symbols** — all six are large, liquid, well-covered names; no small/mid-cap testing was done.

## Live-arming

**Not added to `IAM_PRIMARY_SYSTEM`.** Per this codebase's standing rule, a net-positive-but-thin result does not itself justify going live — that requires an explicit, informed operator decision after seeing this evidence stated plainly, exactly as documented in CLAUDE.md's Quad-Score section. The scanner and blueprint trade on paper (`IAM_PAPER_MODE=true` default) out of the box, same as every other engine here, so real paper-trade evidence will keep accumulating via the existing Paper Trade Ledger (`system="SML_QUAD_SCORE"`) without any further action.

## Reproducing this

Real bars were fetched once via the Robinhood MCP `get_equity_historicals` tool (AMC/GME/IWM/SPY/NVDA/QQQ, 2018-01-01 to now, daily, split-adjusted) and saved to a local JSON file. Point `QUAD_SCORE_BARS_JSON` at an equivalent saved response and run:

```bash
python3 tests/backtest_quad_score.py
```
