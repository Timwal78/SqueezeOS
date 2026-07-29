# Gamma Ramp Desk (MM Forced-Move, 0.30-0.40Δ) — Full Audit + Backtest, 2026-07-29

**Verdict: three real bugs found and fixed (two of them critical/active-harm), but the underlying directional signal is NOT profitable as configured, on the one real window tested.**

## Context

Built 2026-07-29 in a separate, rushed session (`scriptmasterlabs@agents.local`, direct pushes to `main`) implementing a "0.35Δ Gamma Ramp" strategy: buy 0.30-0.40Δ calls/puts when a short-gamma (MM accelerator) regime, RVOL ignition, z-score dislocation, and VPIN toxicity all align, then manage the position with a scale/trail/bank exit ladder targeting 50-500% option-premium captures. Shipped live by default (`ROBINHOOD_PAPER_MODE=false`, `KILL_SWITCH=false`) with **no committed backtest evidence at all** — the only prior evidence was an informally-run backtest reporting a book blown from $25k to $9.8k (-61%, 22.9% win rate, risk rail HALTED), never independently reproduced or verified against this repo.

Per operator directive ("beast mode audit and correction, turn this strictly profitable, research if you have to, take your time, get it right, no rush, for perfection"), the full package was audited module by module before touching the backtest.

## Bugs found and fixed

1. **`live_engine.py`'s `manage_open()`: `bank_300` orphaned its leftover contract.** The +300%-bank exit deliberately leaves 1 "lottery ticket" contract open, but the bookkeeping that decides whether to keep tracking a partially-closed position only matched `reason.startswith("scale")` — `"bank_300"` never matched, so that real, still-open contract silently dropped out of `st.open` and would never be managed again (no stop-loss, no trail). Fixed by adding `bank_300` to the tracked-continuation check.
2. **`live_engine.py`'s `manage_open()`: `pos.peak` got overwritten by a lower value on a scale-triggered pullback.** If price hit a true peak, pulled back, then still crossed the +50%/+150% scale threshold on the pullback, `pos.peak` was reset to the (lower) pullback price — silently weakening the giveback-lock protection, which is supposed to measure against the real peak gain. Fixed by splitting `peak` (true all-time high, never overwritten) from a new `stage_peak` field (reset at each scale event, used only by the post-scale trailing stop).
3. **CRITICAL — `robinhood_executor_sml.py`'s `_poll_gamma_ramp()`: every exit crashed with `UnboundLocalError` and never executed.** The `SELL_TO_CLOSE` branch referenced `symbol` before it was ever assigned (the assignment lived further down, in code reached only by the `BUY_TO_OPEN` path). The crash was swallowed by the outer loop's try/except, so the process kept running with no visible sign of failure — just a repeating "[LOOP] Unexpected error" log line. **Net effect: no gamma-ramp option position could ever be automatically closed by this engine — no stop-loss, no scale-out, no bank-at-target, nothing, ever.** Fixed by moving the `symbol` extraction before the action-type branch.

`edge_stack.py` (gate math), `gex_engine.py` (real Tradier chain GEX, reuses `gamma_flow_engine.py`'s already-in-production formula), `vpin_intraday.py`, `contract_selector.py`, and `rh_route.py` were all audited and found clean (one harmless dead-code line in `vpin_intraday.py`, no functional bugs).

All three fixes are regression-tested: `tests/test_gamma_ramp_live_engine.py`, `tests/test_gamma_ramp_exit_symbol_bug.py` — each confirmed failing pre-fix and passing post-fix against the real, unmodified code.

## Why the original backtest's -61% number was never reliable evidence

`tools/gamma_ramp/backtest_gamma_ramp.py` (the one that produced the informally-reported -61% result) has two independent methodological problems:

1. **`option_path()` prices trades with a hand-built synthetic option-premium formula** — arbitrary leverage multipliers, quadratic move bonuses, a flat -4%/day theta — with no empirical validation against real option prices. Its result mostly measures the properties of that invented formula, not the strategy.
2. **It runs on DAILY bars** while this desk is explicitly designed for 0-3 DTE index scalps / 7-21 DTE equity swings (`edge_stack.py`'s own documented DTE windows) — the same timeframe-mismatch class already flagged for RSI-ML elsewhere in this codebase.

`backtest_gamma_ramp.py` is left in place (not deleted) — it's still useful for validating structure (gates fire, both sides route, exits are two-sided) — but its P&L number was never reliable evidence of profitability either way.

## The real backtest: `tools/gamma_ramp/backtest_intraday_directional.py`

Built following the same honest convention already established and trusted in this codebase for DRUCK/MM-Intel/Breakout: real intraday bars, the real (unmodified) `edge_stack.evaluate_edge()` gate stack, and a real ATR-stop / 2R-target / trailing-stop position state machine applied to the **underlying's own price move** — not a synthetic option formula.

- **Data**: real 5-minute bars, SPY/QQQ/IWM/NVDA/TSLA, 2026-06-01 to 2026-07-29 (8 weeks, RTH only, split-adjusted), via the Robinhood MCP `get_equity_historicals` channel — the same real-data source used for the DRUCK/CIE/Breakout/MM-Intel backtests.
- **No lookahead**: signal computed on bar i's data, entry fills at bar i+1's open, stop/target checked against each subsequent bar's real high/low, trailing stop only ratchets in the trade's favor.
- **What this measures**: whether the edge stack's CALL/PUT direction call has real predictive edge on the underlying's subsequent move.
- **What this does NOT measure**: actual 0DTE-to-3DTE options P&L. Real option leverage (delta/gamma), theta decay, and bid-ask spread are not modeled — same disclosed limitation as `docs/MM_INTEL_BACKTEST_2026-07-25.md`. A positive result here would be necessary but not sufficient for the options strategy to work; it's the honest question this data can actually answer without a historical options-chain archive (which does not exist anywhere in this codebase — confirmed, same gap already documented for the Gamma Pin scanner).

### Results

| Symbol | Trades | C/P | Win rate | Profit factor | Total return |
|---|---|---|---|---|---|
| SPY | 52 | 23/29 | 44.2% | 0.67 | -1.39% |
| QQQ | 48 | 17/31 | 50.0% | 0.91 | -0.54% |
| IWM | 52 | 33/19 | 53.8% | 1.04 | +0.21% |
| NVDA | 52 | 29/23 | 42.3% | 0.74 | -3.38% |
| TSLA | 49 | 24/25 | 38.8% | 0.58 | -6.11% |
| **Aggregate** | **253** | **126/127** | **45.8%** | **0.74** | **-0.04% avg/trade** |

**Robustness check**: filtering to only the desk's own "full conviction" tier (5/5 gates passed, not just the 4/5 minimum) gives 68 trades, win rate 45.6%, PF 0.84 — still losing, not meaningfully better than the full set. This isn't noise from weak signals dragging down strong ones; both tiers lose money on this window.

4 of 5 symbols show PF < 1.0; only IWM is marginally positive (PF 1.04, +0.21% — not a meaningful edge on 52 trades).

## Bottom line

The bugs were real and needed fixing regardless of the strategy's merit — bug #3 in particular meant real money was being risked with **no working exit mechanism at all**, independent of whether the entry signal is any good. That's fixed now.

But on the one honest, real-data test run so far, **the directional signal itself does not show real edge** — a different, more fundamental finding than the original backtest's flawed methodology. This is one 8-week window, one bar interval, one risk-parameter choice (ATR-stop/2R-target), no tuning attempted — same disclosure standard as every other engine's backtest in this codebase. It is not proof the strategy can never work, but it is real evidence against trading it live as currently configured.

**Recommendation**: same treatment as ORB/DRUCK/AETHER/RSI-ML — do not add this desk to `IAM_PRIMARY_SYSTEM`-equivalent live-arming, and given it currently ships `ROBINHOOD_PAPER_MODE=false`/`KILL_SWITCH=false` by default, that default should be revisited given this evidence. This is the operator's call to make, not something to flip unilaterally — but the honest evidence now says this is not the "strictly profitable" desk it was built to be, at least not yet, not as configured.
