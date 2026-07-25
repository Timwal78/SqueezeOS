# SML RSI Multi Length PRO [Beast Mode] Backtest — 2026-07-25

First backtest of the "SML RSI Multi Length PRO [Beast Mode]" Pine script
(pasted into chat 2026-07-25, not yet saved to `indicators/` — see the
licensing note below before deciding whether to). Core RSI logic is credited
in the script's own header to LuxAlgo under **CC BY-NC-SA 4.0
(Attribution-NonCommercial-ShareAlike)**, "upgraded" by ScriptMasterLabs —
**this needs an explicit decision before it goes anywhere near a paid
SqueezeOS product or live execution**, since the NonCommercial clause is a
real constraint this repo hasn't had to deal with on any other indicator
(every other Pine script here is originally ScriptMasterLabs' own work).

**Verdict: negative on all 4 tested symbols on DAILY bars — but likely the
wrong timeframe, not a clean loss verdict.** The script's own comment labels
its signal-line input group "Trigger (0DTE Scalping)" — it's designed for a
fast intraday timeframe, not daily bars. Same caveat class as IMO's
"daily is a floor, not a verdict" from `docs/ENGINE_SCOREBOARD_2026-07-17.md`.

## Method

- Engine: `rsi_ml_engine.py` (new — Python port of the multi-length adaptive
  RSI averaging + EMA signal-line crossover, single source of truth)
- Harness: `tests/backtest_rsi_ml.py` (long-only proxy: CALL crossover enters
  next-bar-open, PUT crossover or a 3% hard stop exits — the Pine script's
  real intended use is CALL/PUT **options** entries per its own plotshape
  labels, so this is a directional proxy, not modeled option premium/theta,
  same convention as every other options-adjacent backtest in this repo)
- Data: same real daily bars as the AETHER/Breakout backtests above —
  AMC/GME/IWM/SPY, 2022-01-03 to 2026-07-23 (~4.5 years, reused pull)

## Results

| Symbol | Trades | Win% | PF | Stops | Strat% | B&H% | MaxDD% |
|--------|-------:|-----:|-----:|------:|-------:|-------:|-------:|
| AMC | 70  | 27.1 | 1.16 | 49 | -17.2 | -98.6 | 78.4 |
| GME | 85  | 20.0 | 1.16 | 52 | -16.3 | -44.1 | 65.1 |
| IWM | 97  | 27.8 | 0.63 | 27 | **-41.5** | +29.6 | 45.5 |
| SPY | 107 | 36.4 | 0.90 | 14 | -11.5 | +54.5 | 23.8 |

## Reading it honestly

- **Trade counts are very high for a daily-bar test** — 70-107 trades over
  4.5 years is roughly one trade every 2-3 weeks, with 14-52 of them (20-73%)
  hitting the hard stop. That stop-out rate is the real signal here: this is
  a fast-reacting crossover firing on noise a daily candle is too coarse to
  resolve cleanly — exactly what "0DTE Scalping" in its own input group name
  implies it was built for.
- **All 4 symbols net negative on daily bars**, IWM worst (-41.5% vs a
  strongly positive +29.6% buy-and-hold environment).
- **This is not a clean "the strategy loses" verdict** the way AETHER's
  meme-stock result is — it's a timeframe mismatch until proven otherwise.
  A fair test needs real intraday bars (same approach already used for
  DRUCK/CIE/IMO's intraday re-tests) before drawing any real conclusion.

## What this does NOT change

- Nothing was saved to `indicators/` yet, nothing wired to any scanner or
  `iam_executor` — this script currently has zero path to live execution by
  design (its own `alertcondition()` calls are titled "(Watchlist)").
- No decision made on the NonCommercial licensing question — flagging it
  here so it isn't silently forgotten if this indicator is revisited.
