# Engine Evidence Scoreboard — 2026-07-17

Measurement pass for the operator's "delete what doesn't win" directive.
**Nothing was deleted.** This document is the evidence; execution-side cuts are
made per engine×symbol with the operator's sign-off via `IAM_SYMBOL_ALLOWLIST`.

## Method

- Harness: `tests/backtest_engines.py` (shared simulator with `tests/backtest_imo.py`)
- Data: real split-adjusted daily OHLCV, 2021-07 → 2026-07 (~1,265 bars/symbol,
  interpolated bars dropped), 10 symbols
- Rules: long-only, signal on bar N → execute bar N+1 open, hard 8% intrabar
  stop (executor `IAM_STOP_LOSS_PCT` semantics), one position at a time, no
  lookahead, no synthetic bars
- IAM caveat: dealer analyst ran without gamma-wall data (historical option
  chains don't exist and were not faked) — same degraded mode production hits
  when chains are unavailable
- IMO caveat: measured on **daily** bars; it is designed for intraday (4h/65m).
  Daily results are a floor, not a verdict.

## Results (strat% = strategy return, B&H% = buy-and-hold)

| Engine | Symbol | Trades | Win% | PF | Stops | Strat% | B&H% | MaxDD% |
|--------|--------|-------:|-----:|-----:|------:|-------:|-------:|-------:|
| IMO | SPY | 12 | 75.0 | 2.35 | 3 | +34.5 | +74.4 | 15.4 |
| IMO | IWM | 12 | 50.0 | 2.11 | 5 | **+40.8** | +27.7 | 16.4 |
| IMO | QQQ | 14 | 64.3 | 1.63 | 5 | +24.0 | +99.1 | 23.5 |
| IMO | PLTR | 19 | 42.1 | 1.65 | 11 | +41.8 | +443.9 | 35.5 |
| IMO | HOOD | 18 | 27.8 | 1.37 | 13 | +16.5 | +204.5 | 46.8 |
| IMO | NVDA | 13 | 23.1 | 0.79 | 9 | −22.8 | +926.1 | 54.7 |
| IMO | MSTR | 24 | 12.5 | 1.02 | 20 | −33.3 | +44.5 | 56.1 |
| IMO | TSLA | 15 | 20.0 | 0.45 | 12 | −47.6 | +73.1 | 49.7 |
| IMO | GME | 20 | 10.0 | 0.56 | 16 | −56.0 | −57.1 | 61.0 |
| IMO | AMC | 23 | 17.4 | 0.32 | 18 | −70.1 | −99.4 | 75.7 |
| CASCADE | NVDA | 142 | 66.9 | 1.44 | 29 | **+144.0** | +926.1 | 46.4 |
| CASCADE | PLTR | 129 | 60.5 | 1.41 | 33 | **+140.6** | +443.9 | 33.7 |
| CASCADE | TSLA | 52 | 59.6 | 1.44 | 11 | +43.7 | +73.1 | 30.4 |
| CASCADE | SPY | 81 | 86.4 | 1.66 | 4 | +29.9 | +74.4 | 15.4 |
| CASCADE | QQQ | 76 | 78.9 | 1.46 | 7 | +27.6 | +99.1 | 15.4 |
| CASCADE | IWM | 52 | 78.8 | 1.39 | 6 | +18.6 | +27.7 | 15.4 |
| CASCADE | HOOD | 111 | 58.6 | 1.09 | 31 | +2.4 | +204.5 | 58.3 |
| CASCADE | AMC | 0 | — | — | 0 | **0.0 (stayed out)** | −99.4 | 0.0 |
| CASCADE | GME | 16 | 43.8 | 0.52 | 7 | −26.6 | −57.1 | 35.1 |
| CASCADE | MSTR | 106 | 48.1 | 0.91 | 47 | −56.9 | +44.5 | 79.1 |
| IAM | NVDA | 98 | 58.2 | 1.81 | 15 | **+250.3** | +926.1 | 37.8 |
| IAM | HOOD | 136 | 42.6 | 1.44 | 42 | **+203.1** | +204.5 | 63.0 |
| IAM | QQQ | 116 | 59.5 | 1.53 | 3 | +62.3 | +99.1 | 20.0 |
| IAM | SPY | 101 | 69.3 | 1.62 | 3 | +41.9 | +74.4 | 18.8 |
| IAM | IWM | 101 | 53.5 | 1.22 | 5 | +16.7 | +27.7 | 23.0 |
| IAM | MSTR | 138 | 39.1 | 1.14 | 60 | −27.2 | +44.5 | 90.7 |
| IAM | TSLA | 123 | 40.7 | 1.05 | 31 | −29.1 | +73.1 | 50.4 |
| IAM | PLTR | 140 | 39.3 | 1.01 | 45 | −40.9 | +443.9 | 61.4 |
| IAM | GME | 133 | 33.1 | 1.05 | 52 | −81.1 | −57.1 | 93.0 |
| IAM | AMC | 129 | 28.7 | 0.64 | 55 | **−97.3** | −99.4 | 98.6 |

## Findings

1. **No engine deserves deletion — every engine wins somewhere.** The losers
   are engine×symbol *pairs*, not engines. Cutting a whole engine would also
   destroy paid API products (Council/CASCADE/IAM sell these signals for
   RLUSD) over an execution-side problem.
2. **CASCADE is the most consistent** (7 of 10 symbols positive or protective;
   the AMC zero-trade result is its best result — the anchor filter refused a
   −99% stock for five years).
3. **IAM is boom-or-bust:** strong on liquid index/megacap names (NVDA +250%,
   HOOD +203%, QQQ, SPY), catastrophic on meme/chop names (AMC −97%, GME −81%).
4. **IMO on daily bars earns IWM/SPY/QQQ only** — consistent with its intraday
   design; IWM (+40.8% vs +27.7% B&H) is its best market, which matches
   SqueezeOS's IWM focus.
5. **Nobody earned the right to trade GME, AMC, or MSTR.** All three engines
   lose or barely survive there.

## Actioned (this PR)

- `IAM_SYMBOL_ALLOWLIST` env var: restricts executor **entries** to listed
  symbols; exits are never blocked. Empty default = unchanged behavior.

## Recommended setting (needs operator sign-off — not applied)

```
IAM_SYMBOL_ALLOWLIST=SPY,IWM,QQQ,NVDA,HOOD
```

Rationale: intersection of where the engines that feed the executor (IAM, IMO
via webhook) showed a real edge. Add TSLA/PLTR only if CASCADE directives are
later routed to execution (CASCADE carries them).

## Not measurable from OHLCV (not deleted, not endorsed — just unmeasured)

`gamma_flow_engine`, `mmle_engine` (standalone), `options_intelligence`,
`iwm_odte_engine`, `whale_stalker_engine` — need recorded options-flow /
dark-pool history that doesn't exist in this repo. If we want evidence on
these, start recording their live signals now (`performance_tracker.py`
exists for exactly this) and re-score in 60–90 days.
`sml_engine.compute_all` — needs the 9-symbol macro complex (incl. VIX/DXY)
historical set; adapter is future work.
