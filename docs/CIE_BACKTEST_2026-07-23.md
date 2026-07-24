# CIE Backtest — 2026-07-23

**Verdict: INCONCLUSIVE — not enough signals fired to say anything about profitability.**
This is a different kind of result than ORB's or DRUCK's backtests (both fired plenty of
trades and lost money). CIE barely fired at all under the conditions this pass could
actually test. Do not read "1 trade, +1.0%, 100% win rate" as "CIE works" — a sample of 1
proves nothing either way.

## Scope limitation (read this before the numbers)

`cycle_intelligence_engine.py` combines four axes. Two of them had **zero real data** in
this backtest:

- **Settlement layer** (SEC FTD + Reg SHO threshold list) — the live scanner pulls this
  from `core/ftd_data.py`'s real SEC feed, but that feed only holds *current* data
  (rolling ~180-day window scraped from SEC's site); there is no historical SEC FTD
  archive wired into this backtest, so settlement pressure was 0.0 for every bar tested.
- **Dark-pool layer** — no real dark-pool print feed exists anywhere in this codebase
  (confirmed by search before building this engine). Always 0.0, by design, not faked.

That leaves only **fractal** (self-mined historical-analog matching) and **meme-cycle**
(volume ratio + realized-vol-proxy phase) actually contributing. Production's `CIE_FIRE`
state requires `composite_z >= 3.0` with `>=2` axes active — with only two axes in play,
both would need to be simultaneously at their individual max (1.5 each), which is
essentially unreachable. So this backtest entered on the weaker `PRIMED` state instead
(`composite_z >= 1.5` with `>=2` axes active, resolved `BUY` direction) — a materially
lower bar than what the live, fully-fed engine will actually fire on. **This tested
"fractal+meme convergence only," not the 4-axis engine.**

## Method

- **Data**: real daily bars, GME / AMC / SPY / IWM / NVDA, via Robinhood MCP
  `get_equity_historicals` (`interval=day`, split-adjusted), ~2024-01 through today
  (640 bars/symbol). Same real-data channel used for the DRUCK backtest
  (`docs/DRUCK_BACKTEST_2026-07-21.md`) — this sandbox has no direct market-data network
  access, Robinhood MCP is a separate allowed channel.
- **Harness**: `tests/backtest_cie.py`. Expanding window — `analyze()` only ever sees
  `bars[:i+1]` when evaluating bar `i` (no lookahead). Entry fills at bar `i+1`'s open.
  Long-only, fixed 10-bar hold (`CIE_BT_HOLD_BARS`, matches the fractal matcher's own
  forward-return horizon), no stop-loss in this v1 pass. 60-bar warmup before the first
  possible signal.

## Result

| Symbol | Bars | Signals seen (PRIMED+/BUY) | Trades | Win rate | PF | Total % |
|--------|------|------|--------|----------|----|---------|
| GME  | 640 | 1 | 1 | 100% | ∞ | +1.00% |
| AMC  | 640 | 0 | 0 | — | — | 0% |
| SPY  | 640 | 0 | 0 | — | — | 0% |
| IWM  | 640 | 0 | 0 | — | — | 0% |
| NVDA | 640 | 0 | 0 | — | — | 0% |

One qualifying signal across 5 symbols × 640 daily bars each (3,200 bar-days). That is a
**signal-frequency problem**, not a losing (or winning) strategy — there isn't enough of
a sample to compute a meaningful profit factor or win rate from one trade.

## Why so rare

`hfm_min_corr = 0.85` (Pearson correlation against a self-mined 20-bar-return library) is
a strict bar, and the meme-cycle layer's higher-scoring phases (IGNITION/PARABOLIC) need
a real volume spike (>=2.5x rolling ADV) — both conditions holding at once, on the same
bar, for a `>=1.5`-composite `PRIMED` read, is inherently uncommon. That's arguably
correct behavior for a *squeeze-detection* engine (it should be rare — squeezes are
rare) — but it means this two-axis-only configuration can't be evaluated for
profitability from ~2.5 years of 5-symbol daily data.

## What this does NOT tell you

- Whether the **full 4-axis engine** (with real settlement-layer FTD data, which is the
  axis this engine was actually built around — see the module docstring) is profitable.
  That can only be measured once `cie_scanner.py` has been running in production long
  enough to accumulate real state alongside real settlement pressure, or by wiring a
  historical SEC FTD archive into a future backtest pass.
- Whether loosening `hfm_min_corr` or the `PRIMED` composite threshold produces a
  large-enough, still-meaningful sample. That's a legitimate follow-up but was **not**
  done here — do not read this doc as having quietly tuned parameters until something
  looked good. The thresholds above are the engine's shipped defaults, untouched.

## Bottom line

Per this repo's evidence-before-claims rule: **do not set `IAM_PRIMARY_SYSTEM=SML_CIE`
or claim this engine is profitable.** Unlike ORB/DRUCK (measured and found not
profitable as configured), CIE is *unmeasured* — the honest status is "not enough
signal density to test," not "tested and works" or "tested and fails." Re-run this
backtest after `cie_scanner.py` has accumulated real settlement-layer history in
production, or extend `tests/backtest_cie.py` with a historical FTD data source, before
drawing any profitability conclusion.
