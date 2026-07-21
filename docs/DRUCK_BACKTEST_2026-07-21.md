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
