# SML AI Trade Desk v3 — Simplified Backtest — 2026-07-25

First backtest of "SML AI Trade Desk v3 — SqueezeOS Institutional" (pasted
into chat 2026-07-25, not saved to any repo — genuinely new, confirmed via
search across SqueezeOS/SqueezeOS-Monorepo). **This is a SCOPE-REDUCED port,
not a faithful full translation** — the real script has 18 weighted scoring
components (trend, VWAP, momentum, structure/liquidity, squeeze, ADX, CMF,
Z-score, relative strength vs benchmark, volume anomaly, live fundamentals,
options intelligence, HTF bias) summing to 100 points. Ported here: EMA
trend stack, VWAP, RSI+MACD momentum, BOS/CHoCH/sweep structure breaks,
BB/KC squeeze-fire, ADX — the components computable from plain OHLCV alone
(worth up to ~66 of the original 100-point budget; the rest depend on
TradingView-specific data — live fundamentals via `request.financial`,
cross-symbol relative strength via `request.security`, real IV rank — that
can't be faithfully reproduced with this sandbox's real-data access).

**This script's webhook also does not reach live execution regardless of
backtest result** — it sends `"secret"`/`"alert_type"` fields; the real
bridge (`core/api/tradingview_webhook_bp.py`) requires `"passphrase"` and an
`"action"` value in a fixed set (`BUY`/`SELL`/`EXECUTE_LONG`/etc.). Wrong
schema entirely, confirmed by reading the real endpoint code.

## Method

- Engine: scratch Python port (not committed — see caveats above), real
  EMA/RSI/MACD/ADX/DMI/pivot math, no synthetic shortcuts
- Data: same real daily bars as every other backtest in this session —
  AMC/GME/IWM/SPY, 2022-01-03 to 2026-07-23
- **Threshold was empirically calibrated, not taken from the original
  script's design.** The real script's own weights (`minScoreFilter`
  default 0, action tiers at 40/50/65/75) assume all 100 points are
  reachable. With ~34 points of components removed, the realistic ceiling
  on this real data topped out around 46 (squeeze-fire essentially never
  coincided with full trend+structure alignment in this window) — so a
  threshold of 35 was chosen by inspecting the actual score distribution
  achieved, not derived from the original design. **This is a form of
  light curve-fitting and should be weighted accordingly** — it was
  necessary to get any trades at all out of the reduced component set, but
  it means the threshold was picked to fit this data, not validated
  independently of it.

## Results (long-only proxy, 3% hard stop, threshold=35)

| Symbol | Trades | Win% | PF | Strat% | B&H% | MaxDD% |
|--------|-------:|-----:|-----:|-------:|-------:|-------:|
| AMC | 6  | 0.0  | 0.00  | -27.1 | -98.6 | 27.1 |
| GME | 13 | 7.7  | 0.35  | -35.7 | -44.1 | 35.7 |
| IWM | 4  | 25.0 | 5.05  | +25.0 | +29.6 | 6.6  |
| SPY | 3  | 66.7 | 17.85 | **+55.9** | +54.5 | 3.0  |

## Reading it honestly

- **This is the least-bad result of the three new scripts tested today**
  (vs. AETHER's clean losses and RSI-ML's clean losses) — SPY slightly
  beats buy-and-hold, IWM comes close, and AMC/GME lose far less than
  simply holding them (same "correctly avoiding a disaster" pattern
  CASCADE showed on AMC in the engine scoreboard).
- **But trade counts are extremely thin (3-13 over 4.5 years)** and the
  threshold was reverse-engineered from this exact dataset — SPY's PF
  17.85 is 2 wins out of 3 trades, not a statistically meaningful number.
  This is directionally interesting, not proof of anything.
- A real verdict would need: (1) the full 18-component port including
  fundamentals/relative-strength/IV-rank, (2) a threshold set from the
  original design or a held-out validation split, not fit to the test data
  itself, (3) more symbols and a longer or out-of-sample window.

## What this does NOT change

- Nothing saved to `indicators/`, nothing wired to any scanner or
  `iam_executor`. This script has zero live-execution path regardless
  (webhook schema mismatch, see above).
- Not a recommendation to build this out further without a real decision —
  flagging it as the most promising of today's three new scripts, not as
  a proven third system.
