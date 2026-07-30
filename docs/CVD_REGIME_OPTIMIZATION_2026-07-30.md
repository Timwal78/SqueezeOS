# SML CVD Regime Desk — parameter search + out-of-sample validation (2026-07-30)

**Supersedes the verdict in `docs/CVD_REGIME_BACKTEST_2026-07-30.md`.** That doc's
numbers were correct for what it measured but its conclusion was drawn from 8
trading sessions and does not generalize. This doc replaces the verdict; the
earlier file is left intact so the original measurement stays auditable.

Operator directive that prompted this: *"that means run ur python or what ever
the fuck u do till u get a winning script."* Fair — the first pass stopped at a
verdict off too little data. So: 1,000 configurations searched, on 13× the data,
with out-of-sample validation.

---

## The short version

1. **The earlier "no demonstrated edge" call was based on an unrepresentative
   window.** On 109 sessions the shipped defaults are **net positive**: PF 1.090,
   +67.5% summed, **2,222 trades**.
2. **No configuration survived out-of-sample.** 0 of 15 train winners held up.
   Parameter tuning does not fix this strategy — that lever is exhausted.
3. **The edge is decaying monotonically** and is currently below break-even:
   PF 1.360 (Apr) → 1.225 (May) → 1.069 (Jun) → 0.916 (Jul).
4. **The finding that actually decides it: the edge averages +0.030% of the
   underlying's move per trade.** Even in the best month it is +0.097%. That is
   almost certainly smaller than real transaction costs, and *definitely* smaller
   than a typical option bid/ask spread. See §5 — this is the reason I cannot hand
   over a "winning script," and it is not a data-quantity problem.

**Recommendation: do not arm live. Paper-trade it forward** (the Paper Trade
Ledger already records per-system automatically) and revisit with real forward
results. `SML_CVD_DESK` is still not in `IAM_PRIMARY_SYSTEM` and nothing is wired
to the executor.

---

## 1. Data

Real 5-minute OHLCV, **8 symbols** (SPY QQQ IWM NVDA TSLA AMD AAPL MSFT),
**2026-02-23 → 2026-07-29, 109 trading sessions, 8,502 bars/symbol — 68,016 bars
total.** Robinhood MCP `get_equity_historicals`, the same channel used for the
DRUCK/CIE/Breakout/MM-Intel backtests.

**Data hygiene — this mattered a lot.** 109,248 raw bars were fetched across three
calls covering 2025-11-14 → 2026-07-30. **41,232 of them (38%) came back flagged
`interpolated` with zero volume** and were dropped. That is not a rounding
detail: all 5-minute history before 2026-02-23 on this feed is synthetic
gap-fill, so the requested "9 months" is really 5. Feeding zero-volume synthetic
bars to a *volume-weighted* CVD engine would have produced a completely
fabricated result that looked like real history. Same for the 2026-07-30 session
(intraday, not yet real).

## 2. Method

`tests/optimize_cvd_regime.py`, running the real unmodified
`cvd_regime_engine.compute_series()`.

Chronological split on session boundaries:

| Slice | Sessions | Bars/symbol | Seen by the search? |
|---|---:|---:|---|
| **TRAIN** | 73 (Feb 23 – Jun 5) | 5,694 | yes |
| **VALID** | 36 (Jun 5 – Jul 29) | 2,808 | **no** — scored once, at the end |

Fit on the past, verify forward — the only split that mirrors deployment.

Random search, 1,000 configs (seeded, reproducible) over 11 parameters:
`smooth_len, slope_len, htf_minutes, stdev_len, ema_len, min_conviction,
use_early, stop_atr, target_r, cooldown_bars, exit_on_flip`.

To even be validated, a config had to clear on TRAIN: **≥300 trades** and **≥5/8
symbols with PF>1** (a config that only works on one ticker is noise).

## 3. Baseline — the shipped defaults, unchanged

| Slice | Trades | Win% | PF | Symbols PF>1 | Sum% |
|---|---:|---:|---:|---:|---:|
| TRAIN | 1,485 | 39.6 | **1.149** | 6/8 | **+68.2** |
| VALID | 728 | 37.9 | 0.984 | 3/8 | −4.66 |
| Full 109 sessions | 2,222 | 39.1 | **1.090** | — | **+67.5** |

The 8-session window used in the earlier doc (Jul 20–29) sits entirely inside the
flat VALID stretch. That measurement was real; generalizing from it was the
mistake.

### Month by month (defaults, no tuning — so this is not a fitted curve)

| Month | Trades | Win% | PF | Sum% | Avg/trade |
|---|---:|---:|---:|---:|---:|
| 2026-02 (partial) | 93 | 34.4 | 0.585 | −16.92 | −0.182% |
| 2026-03 | 458 | 41.0 | 1.117 | +17.27 | +0.038% |
| 2026-04 | 427 | 41.9 | **1.360** | +41.58 | +0.097% |
| 2026-05 | 412 | 36.7 | 1.225 | +27.53 | +0.067% |
| 2026-06 | 423 | 40.2 | 1.069 | +11.31 | +0.027% |
| 2026-07 | 409 | 36.4 | **0.916** | −13.23 | −0.032% |

Apr → Jul is a monotonic decline across four consecutive months on ~420 trades
each. That is a decay pattern, not month-to-month noise.

## 4. The search result: nothing survived

**588 of 1,000 configs cleared the TRAIN filters** — which by itself shows how
easy it is to manufacture an impressive-looking backtest. Top 15 by median
per-symbol PF on TRAIN, then the same 15 on VALID:

| # | TRAIN medPF | VALID medPF | VALID PF | Symbols + | VALID trades | VALID sum% | Verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 1.388 | 0.853 | 0.878 | 1/8 | 196 | −27.53 | collapsed |
| 2 | 1.387 | 0.768 | 0.841 | 2/8 | 306 | −41.99 | collapsed |
| 3 | 1.371 | 0.977 | 0.834 | 2/8 | 481 | −47.55 | collapsed |
| 4 | 1.368 | 0.865 | 0.842 | 3/8 | 254 | −36.08 | collapsed |
| 5 | 1.361 | 0.933 | 0.979 | 3/8 | 343 | −5.97 | collapsed |
| 6 | 1.357 | 0.795 | 0.912 | 2/8 | 630 | −28.59 | collapsed |
| 7 | 1.351 | 1.058 | 1.067 | 4/8 | 319 | +16.16 | collapsed |
| 8 | 1.350 | 1.011 | 0.980 | 4/8 | 377 | −6.09 | collapsed |
| 9 | 1.347 | 0.911 | 0.883 | 3/8 | 386 | −31.94 | collapsed |
| 10 | 1.333 | 0.985 | 0.893 | 2/8 | 215 | −26.06 | collapsed |
| 11 | 1.331 | 0.878 | 0.884 | 2/8 | 338 | −29.60 | collapsed |
| 12 | 1.329 | 0.863 | 0.938 | 3/8 | 190 | −13.53 | collapsed |
| 13 | 1.325 | 0.914 | 0.899 | 3/8 | 382 | −27.99 | collapsed |
| 14 | 1.320 | 1.055 | 1.034 | 4/8 | 500 | +9.76 | collapsed |
| 15 | 1.315 | 1.015 | 1.026 | 4/8 | 377 | +7.20 | collapsed |

**0 of 15 held up.** Every TRAIN winner sat at medPF 1.32–1.39; forward, they
land at 0.77–1.06. Three (#7, #14, #15) are mildly positive on VALID but only
reach 4/8 symbols, missing the 5/8 robustness bar — and picking one of those
three *after* seeing the validation column is exactly the mistake the split
exists to prevent, so they are not being promoted either.

Note the pattern: the TRAIN winners did *worse* on VALID than the untuned
defaults did (defaults: VALID PF 0.984). Tuning actively made forward performance
worse — the signature of fitting noise.

## 5. Why this is not a "needs more data" problem

Across 2,222 trades the edge is **+0.030% of the underlying's move per trade**.
Best month: **+0.097%**.

The backtest charges nothing for costs. Reality charges:

- **Option bid/ask spread.** On the 0.30–0.40Δ contracts this script is meant to
  trade, a 1–3% round-trip spread cost is ordinary. A +0.097% underlying move at
  ~5–10× option leverage is roughly a +0.5–1.0% option move — i.e. the *best
  month's* entire edge is the same order of magnitude as the spread, and the full
  period's edge (+0.030%) is well inside it.
- **Theta.** Positions are held ~16–20 bars (80–100 minutes). On short-dated
  contracts that decay is charged against every trade, winners included.
- **Slippage** on 5-minute entries in 8 names.

So the honest read is not "the sample is too small" or "the parameters are
wrong." It is that **the measured directional edge is too thin to pay for the
instrument it is meant to trade**, and it is shrinking. More data or more tuning
does not change that arithmetic; only a structurally stronger signal would.

## 6. What would actually be next (none of it done here)

Parameter tuning is exhausted. Honest remaining levers, each needing its own
decision:

1. **Paper-trade forward.** Cheap, zero risk, and the Paper Trade Ledger already
   attributes per-system. Real forward results beat any further backtesting.
2. **A genuinely different signal**, not a re-parameterization — e.g. requiring
   true signed delta from a tick/quote feed instead of the OHLCV bar-range proxy.
   That is a data-acquisition problem, not a code problem, and the proxy is the
   most likely reason the signal is thin.
3. **Trade the underlying, not options**, if the +0.03%/trade edge is ever made
   robust — equities have far lower per-trade friction than short-dated options.

## 7. Standing limitations

- Directional %-move on the underlying only; no option premium, leverage, theta,
  spread or assignment modelled (same disclosed convention as
  `breakout_engine.py` / `druck_engine.py` / `mm_intel_engine.py`).
- No commission or slippage.
- "CVD" is a bar-range proxy from OHLCV, **not** true bid/ask delta.
- 5-minute chart only; `htf_minutes` was searched (15/30/60/120) but the chart
  timeframe was not.
- 5 months of real history — the requested 9 months did not exist on this feed.

## 8. Reproduce

```bash
# 1000-config search with out-of-sample validation
python tests/optimize_cvd_regime.py <datadir> 1000

# single-config backtest + sensitivity
python tests/backtest_cvd_regime.py <datadir>/*_5m.csv

# regression tests for the 7 fixed bugs (no data needed)
python tests/test_cvd_regime_engine_smoke.py
```

CSV format: `ts,high,low,close,volume`, one file per symbol named `SYM_5m.csv`.
Drop any bar the feed flags `interpolated` or with zero volume before use.
