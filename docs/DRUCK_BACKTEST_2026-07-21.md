# SML-DRUCK Backtest — 2026-07-21

First real backtest of DRUCK-LB, made possible by pulling real historical
bars through the connected Robinhood MCP (`get_equity_historicals`) — every
prior sandbox in this project had no market-data network access at all
(`api.tradier.com`/`api.polygon.io` both returned 403 on the CONNECT tunnel).

**Verdict: not ready for live trading.** Profit factor below 1.0 (losing
money) on 4 of 5 symbols; the 5th is flat. Do not set `IAM_PRIMARY_SYSTEM=SML_DRUCK`
or flip `IAM_PAPER_MODE=false` for this system based on current evidence.

## Method

- Harness: `tests/backtest_druck.py` (real, unmodified — full position state
  machine: ATR stop, 3:1 R:R target, ratcheting trailing stop, capped
  pyramid adds, no lookahead — entries fill at next bar's open)
- Engine: `druck_engine.py` (single source of truth for DRUCK-LB math,
  Pine-parity, default params: `ADX_trend=25 breakout_len=20 EMA=9/20 RR=3.0
  stop_mult=2.0 trail_mult=3.0 HTF=2h`)
- Data: real 5-minute regular-session OHLCV bars, May 1 – Jul 20, 2026, pulled
  live via the Robinhood MCP (`get_equity_historicals`), aggregated into real
  15-minute bars (DRUCK's deployed default timeframe) — no synthetic bars,
  no interpolation beyond the aggregation grouping itself
- Symbols: SPY, QQQ, IWM, NVDA, TSLA — 1,404 real 15-min bars each (~56
  trading days)

## Results

| Symbol | Trades | Win% | Avg%/trade | PF | Avg bars held | Jugular# | Jugular win% | Total return% |
|--------|-------:|-----:|-----------:|----:|--------------:|---------:|-------------:|---------------:|
| SPY    | 34     | 35.3 | -0.003     | 0.99 | 12.7          | 3        | 67           | -0.14          |
| QQQ    | 28     | 21.4 | -0.289     | 0.42 | 14.1          | 6        | 33           | -7.86          |
| IWM    | 34     | 23.5 | -0.137     | 0.65 | 11.9          | 4        | 0            | -4.65          |
| NVDA   | 31     | 19.4 | -0.515     | 0.42 | 9.2           | 3        | 33           | **-15.01**     |
| TSLA   | 32     | 21.9 | -0.287     | 0.67 | 9.8           | 4        | 25           | -9.26          |

## Reading it honestly

- Win rates cluster 19–35%. For a 3:1 R:R strategy that's not automatically
  a loser (breakeven win rate at 3:1 is 25%), but realized PF still came in
  below 1.0 on 4/5 symbols — losing trades are eating more than the R:R
  ratio alone would predict, most likely from trades that get stopped before
  reaching the full 3R target (trailing stop tightens faster than the move
  develops) combined with whipsaws in the mean-reversion branch.
- SPY is the only symbol that isn't a clear loser, and it's flat (PF 0.99,
  -0.14% total) — not a case for "SPY works, trade that instead."
- This is one ~2.5-month window in one market regime with zero parameter
  tuning. It is real evidence against going live as-configured; it is not
  proof the strategy can never work under different params or a different
  regime.

## Addendum — parameter search confirms it, doesn't overturn it (2026-07-21)

After this backtest, two AI-generated "second opinions" were checked and
rejected before this addendum:
1. A "Grok Optimized Multi-SMA" report that grid-searched hundreds of moving-
   average pairs and reported the in-sample-optimal result per ticker as if
   it were a real backtest — classic curve-fitting (proof: the four
   "optimal" pairs shared no structure, e.g. NVDA 75/100 vs SPY 5/70). It
   also wasn't a test of DRUCK-LB at all, just an unrelated SMA crossover.
2. A "DRUCK-LB v7 BeastMode" report claiming portfolio return flipped from
   negative to +13.7%, again with no code, no trade log, and a materially
   changed strategy (long-only, mean-reversion branch dropped, six
   parameters retuned). Its exact described logic was independently
   reimplemented and run on the same real data used above — actual result:
   0–3 trades per symbol, +0.20% to +2.10%, nowhere near the claimed
   numbers. Not reproducible.

To give this a fair, honest shot rather than just rejecting other people's
unverifiable claims, a real parameter search was run directly against this
project's own `druck_engine.py`/`backtest_druck.py` — DRUCK-LB's actual
regime + breakout + mean-reversion logic, not a substitute strategy — with
a genuine chronological 70/30 train/test split (982 train bars / 422 test
bars per symbol) and **one shared parameter set across all 5 symbols**
(matching how it's actually deployed — `druck_scanner.py` runs a single
global config against a dynamic universe, not per-symbol tuned configs).
Grid: `adx_trend∈{20,25,30}`, `breakout_len∈{15,20,25}`,
`atr_stop_mult∈{1.5,2.0,2.5}`, `trail_atr_mult∈{2.0,3.0,4.0}`,
`rr_ratio∈{2.0,3.0,4.0}` — 243 combinations, selected by summed return% on
the training window only.

**Result: no configuration in that grid was profitable in aggregate, even
in-sample.** The best-scoring config on the training window still summed to
a net loss across the 5 symbols. Evaluated on the held-out test window
(never touched during the search), the tuned config performed roughly the
same as defaults — worse on NVDA (-5.31% vs -2.14%), marginally better on
QQQ/IWM, effectively unchanged on SPY/TSLA. This is a real, disciplined
tuning attempt that reinforces the original verdict rather than overturning
it — within a reasonable parameter neighborhood of the shipped defaults,
this strategy structure does not have an edge on this data/window.

This still isn't proof the strategy can never work (different regime, a
wider search, or per-symbol configs might do better — the last of those
trades off against overfitting risk the same way the rejected "v7" report
did). But two independent honest checks now agree with the original
backtest, and two unverified/unreproducible "it actually works" claims
have been checked and rejected. The bar for revisiting this stays the
same: real code, real trade logs, real out-of-sample discipline.

## What this does NOT change

- DRUCK's paper-mode wiring (`druck_scanner.py` → `iam_executor`) stays as-is
  — it's correct, paper trading isn't risk, and paper data continues to
  accumulate for a longer/independent read later.
- No env vars were changed. `IAM_PRIMARY_SYSTEM` remains unset;
  `IAM_PAPER_MODE` remains the default `true`.
- Same bar every other engine here has had to clear (see ORB's backtest
  verdict in the CLAUDE.md SML-IMO section — also lost in most
  configurations, also not promoted to live) — code-correct is not the same
  as profitable, and this measurement is what actually settles that
  question for DRUCK, superseding the earlier "profitability UNMEASURED"
  status.
