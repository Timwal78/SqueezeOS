# Squeeze Momentum Engine v6 — independent verification of the reported results (2026-07-30)

**Verdict: the reported performance matrix did not reproduce.** On the rows this
session could source real bars for, the measured result is the opposite sign:
AMC 2D was reported at **+$5,930.40 / PF 5.007** and measures **−$439.16 / PF
0.731 on 9 trades**. Four concrete script bugs were confirmed by measurement, and
the reported "0.44%–1.60% max drawdown" column is shown to be an artifact of the
2%-of-equity position size, not a property of the strategy.

Source: operator-submitted Pine v6 `strategy("ScriptMaster - Squeeze Momentum
Engine v6")` plus a reported Strategy Tester matrix across 8 tickers.

| Artifact | Path |
|---|---|
| Python port of the submitted strategy | `squeeze_momentum_engine.py` |
| Verification harness | `tests/backtest_squeeze_momentum.py` |

Why verify at all: this repo has a standing precedent — the "History note" under
*SML Breakout Target/Stop* in `CLAUDE.md` — where a chat-reported backtest table
(336-parameter sweep, 191 trades) could not be reproduced and its aggregates did
not match an independent run. Chat-reported Strategy Tester output is a hypothesis
until re-derived.

---

## 1. Reported vs measured

Real bars via Robinhood MCP `get_equity_historicals`, split-adjusted, RTH,
interpolated/zero-volume bars discarded. Port models Pine strategy **defaults**:
market orders submitted on the signal bar fill at the **next bar's open**
(`process_orders_on_close` is not set in the submitted script), 2% of equity per
entry, 0.03% commission per side, 1 tick slippage.

| Row | Reported | Measured | Trades | Verdict |
|---|---|---|---:|---|
| AMC 2D (2013–2026) | +$5,930.40, PF 5.007, WR 41.67% | **−$439.16, PF 0.731, WR 44.4%** | 9 | **contradicted** |
| GME (reported 1h) | +$1,343.03, PF 1.248, WR 35.89% | **−$928.68, PF 0.647, WR 33.3%** (1D) | 42 | different TF — see §4 |
| COSM 1D | +$2,171.02, PF 1.549, WR 46.88% | +$536.86, PF 1.773, WR 50.0% | 6 | sign agrees, magnitude does not |
| DJT 4h | +$3,219.64, PF 3.156 | **0 trades** | 0 | untestable — see §4 |
| IONQ 4h | +$2,921.11, PF 2.224 | **0 trades** | 0 | untestable — see §4 |
| BTCUSD 1D | +$5,528.25, PF 4.977 | not tested | — | untestable — see §4 |
| XRPUSD 1h | +$1,464.01, PF 1.446 | not tested | — | untestable — see §4 |
| FFAI 30m | +$1,648.62, PF 1.468 | not tested | — | untestable — see §4 |

Additional measured rows (not in the reported matrix, full clean history available):
AMC 1D — 28 trades, PF 0.525, −$1,089.31.

**COSM is not a second data point in favour.** Its single best trade is **110.6%
of net P&L** and its top 3 are **229.4%** — one trade carries it and the rest lose
money, on a 6-trade sample. That is the same single-event pattern already flagged
for AMC in the reported matrix, and it is not an edge.

---

## 2. The drawdown column does not mean what it appears to

`default_qty_type=strategy.percent_of_equity` with `default_qty_value=2` deploys
**$2,000 of a $100,000 account** per trade. Profit factor, win rate and trade
count are invariant to that choice; **dollar P&L and drawdown-% are not.** Running
the identical strategy at 100% of equity instead of 2%:

| | 2% sizing | 100% sizing |
|---|---:|---:|
| AMC 2D max drawdown | 1.21% | **49.90%** |
| GME 1D max drawdown | 1.39% | **52.95%** |

The reported 0.44%–1.60% drawdowns therefore say nothing about the strategy's
risk profile — they measure the position size. At full size this is a ~50%
drawdown system. Reading "PF 4.977 with 0.44% DD" as a fortress conflates a
size-invariant ratio with a size-dependent one.

The same arithmetic reframes the returns: **+$5,528.25 on $100,000 over 12 years
is +5.5% total, ≈0.45%/yr** — with BTC buy-and-hold over that window orders of
magnitude higher. The reported table's largest number is a near-flat return.

---

## 3. Four script defects, each measured

**ISSUE A — the short trigger is inverted relative to the long.**
```pine
sqzReleaseLong  = scolor == C_WHITE and scolor[1] == C_BLACK   // ON -> OFF: a RELEASE
sqzReleaseShort = scolor == C_BLACK and scolor[1] == C_WHITE   // OFF -> ON: an ONSET
```
Despite the matching names, longs enter on squeeze *release* and shorts on
squeeze *onset* — opposite events. And the accidental shorts are the only thing
holding the equity curve up: removing them makes everything worse.

| | with shorts | long-only |
|---|---:|---:|
| AMC 2D | PF 0.731 | **PF 0.115** |
| GME 1D | PF 0.647 | **PF 0.344** |

The documented thesis ("wait for compression to build energy, then ride the
release") is the *long* side — which is the weaker half by a wide margin.

**ISSUE B — there is no stop loss anywhere.** The only exit is a one-bar
momentum tick (`val < val[1]`). Position *size* is capped at 2%; risk per trade
is not bounded at all. Any claim this script "enforces real-world risk" refers to
sizing, not to risk control.

**ISSUE C — `val > valLowest` is a tautology.** `valLowest = ta.lowest(val,100)[1]`;
val exceeding its own trailing 100-bar minimum is essentially always true.
Measured: the term rejected **0.00%** of otherwise-qualifying bars on every
symbol tested. Same class as the dead conviction gate found in the CVD Regime
script.

**ISSUE E — `noSqz` and its blue zero-cross are unreachable.** `basis` and `ma`
are both `ta.sma(source, 20)`, so BB and KC share one centre and
`lowerBB > lowerKC ⟺ upperBB < upperKC` — making `sqzOn`/`sqzOff` exact logical
complements. Over 4,166 GME daily bars: 747 'on', 3,400 'off', **0 'none'**.

This one is worth recording because it *falsifies* a plausible-sounding
criticism. One would reasonably expect the strict `ON -> OFF` transition to miss
most real releases (those landing in `noSqz` first). It does not: ON→OFF
transitions equal ON→anything transitions exactly — 41 of 41 on AMC 2D, 120 of
120 on GME 1D. The very low trade count comes from the *conjunction* of the other
entry filters, not from missed transitions. Measurement corrected the hypothesis.

---

## 4. What this verification could NOT check, and why

Stated explicitly so nothing here is over-claimed:

- **BTCUSD and XRPUSD:** no historical crypto bar source is available in this
  session. The Crypto.com MCP server exposes `get_candlestick` but caps at **50
  candles** — unusable for a 12-year daily test. The headline BTCUSD row is
  therefore **unverified, not disproven.**
- **DJT 4h and IONQ 4h (reported 2021–2026):** the Robinhood feed returned real
  4-hour bars only from **2025-11-03** (267 real bars; 1,597 of 1,864 came back
  flagged `interpolated`). On that short window the strategy takes 0 trades.
  Reported 4h rows spanning 2021 cannot be reached from here. Separately, DJT did
  not trade under that ticker in 2021 (it began March 2024, DWAC before) — a
  2021 start implies chained pre-merger history.
- **COSM 1D (reported 2010–2026):** real daily bars only from **2022-02-28**.
- **FFAI 30m:** not pulled.
- **Port fidelity:** fills are modelled at the next bar's open (Pine's default).
  If the reported run used `process_orders_on_close=true`, fills differ. Bar data
  also differs in source (TradingView vs Robinhood) and AMC 2D here is aggregated
  from daily bars. These can move numbers — they do not plausibly move a profit
  factor from 0.73 to 5.01.

---

## 5. What would make this worth another look

1. **Fix ISSUE A** and re-measure — a squeeze-release short is a different (and
   coherent) strategy from what is currently coded.
2. **Add a real stop** so risk per trade is bounded rather than only sized.
3. **Delete ISSUE C's dead filters** so the remaining logic is honest about what
   is actually gating entries.
4. **Report trade counts** alongside every PF. 9 trades over 12 years cannot
   support a profit-factor claim in either direction, and neither can 6.
5. **Then validate out-of-sample**, using the chronological split in
   `tests/optimize_cvd_regime.py` — without it, any tuning of this script will
   produce a great-looking table that does not survive forward.

**Do not wire this to `iam_executor.py`, do not add it to `IAM_PRIMARY_SYSTEM`,
and do not promote it to a watchlist engine on the current evidence.** No scanner
was built and nothing is wired to execution.
