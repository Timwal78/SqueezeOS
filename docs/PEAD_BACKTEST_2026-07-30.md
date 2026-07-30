# Post-Earnings-Announcement Drift (PEAD) — Backtest Verdict (2026-07-30)

**Verdict: NO DEMONSTRATED EDGE in this test. Not wired to any scanner or `IAM_PRIMARY_SYSTEM`.**

## Why this was tested

After the squeeze-fire and CVD-regime chart-pattern signals both came back
flat-to-negative under honest measurement, operator asked to keep looking
for something real. PEAD (Bernard & Thomas 1989) is one of the most
robustly published anomalies in finance — decades of peer-reviewed evidence
across many market regimes that stocks beating earnings estimates keep
drifting up afterward, and misses keep drifting down. Worth a real test
before assuming every earnings-adjacent signal fails the way the chart
patterns did.

## Method

`tests/backtest_pead.py` — real EPS estimate/actual + report date/timing
(`get_earnings_results`) and real daily bars (`get_equity_historicals`),
both via Robinhood MCP, same real-data channel used for every backtest in
this codebase. Entry is the close of the first trading day the market could
react (report day itself for before-market reports, next day for
after-market) — deliberately excludes the initial jump/gap to isolate
drift specifically, matching how PEAD is studied academically. Exit N
trading days later; three windows tested (30/60/90).

Two independent universes, run separately, not blended:
- **Mega-cap** (AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META, AMD, NFLX, CRM,
  ADBE, PYPL, SBUX, DIS, INTC) — 98 real earnings events since late 2024.
- **Mid-cap** (CROX, PLNT, FIVE, WING, CAKE, TXRH, SHAK, CELH, ELF, DUOL,
  AFRM, UPST, CVNA, ROOT, DECK) — 94 real earnings events since late 2024.
  Chosen specifically because the literature documents PEAD as *strongest*
  on smaller/less-covered names — testing PEAD in mega-caps alone would be
  closer to its worst case (institutional algos arbitrage the surprise away
  within hours on the most liquid names).

## Results

| Universe | Window | Beats (n, avg drift) | Misses (n, avg drift) |
|---|---|---|---|
| Mega-cap | 30d | 78, +0.374% | 12, -0.195% |
| Mega-cap | 60d | 72, +5.765% | 12, +9.502% |
| Mega-cap | 90d | 64, +8.583% | 11, +11.875% |
| Mid-cap | 30d | 73, -2.628% | 17, +5.135% |
| Mid-cap | 60d | 66, -1.665% | 13, +14.581% |
| Mid-cap | 90d | 62, -1.826% | 13, +11.863% |

## The finding that actually decides it

Six independent tests (2 universes × 3 windows), zero of them show PEAD's
real signature — beats pulling clearly ahead of misses. Mega-cap: at longer
windows both groups drift up by similar or larger amounts for MISSES,
meaning nothing separates them — everything just rode the broader market up
over this window regardless of earnings. Mid-cap: misses consistently
**outperform** beats at every window length, the opposite of the prediction.

## Honest interpretation

This is not evidence PEAD is fake — it has real decades of peer-reviewed
evidence across many market cycles and much larger samples than this test
could pull in one session. It's evidence that **this specific test** can't
isolate it, for two disclosed, real reasons:

1. **Single market regime.** Dec 2024–Jul 2026 was a broadly bullish window
   for most of these names — beta swamps the earnings-specific signal when
   almost everything drifts up regardless of what happened at the print.
2. **Trailing-EPS-surprise-only is an incomplete predictor**, especially for
   high-multiple growth names (DUOL, CELH, AFRM, UPST, CVNA) where forward
   guidance revisions are frequently the dominant driver of post-earnings
   price action, not the trailing beat/miss itself. No guidance data was
   available in this test.

## What was deliberately NOT done

Did not keep re-running additional window lengths or universes chasing a
number that flips positive — that is the exact overfitting failure mode
`docs/CVD_REGIME_OPTIMIZATION_2026-07-30.md` already documents and warns
against repeating. Six honest, real tests with a consistent null/inverted
result is a real finding, not a reason to keep searching for a lucky
configuration.

## What this does NOT do

- Does not get wired to any scanner or `iam_executor.py`.
- Does not get added to `IAM_PRIMARY_SYSTEM`.
- Real data pulls (`data/earnings_events.json`, `data/earnings_events_midcap.json`)
  are not committed — same convention as every other backtest's OHLCV CSVs
  in this codebase (see `tests/backtest_druck.py`'s own docstring). Only the
  reusable harness (`tests/backtest_pead.py`) is committed.

## If this is revisited

Would need real forward-guidance data (raised/cut/reaffirmed), not just
trailing EPS surprise, to properly test PEAD the way the literature does —
that data source was not investigated this session. A broader universe
(hundreds of names, multiple market regimes/years) would also meaningfully
increase confidence either way; this test's ~100-190 events in one bull
market is a real but modest sample.
