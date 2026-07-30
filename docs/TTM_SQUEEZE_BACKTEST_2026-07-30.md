# TTM Squeeze Engine — Backtest Verdict (2026-07-30)

**Verdict: NOT profitable as-configured. Do not wire to any scanner or `IAM_PRIMARY_SYSTEM`.**

## Why this was built

Operator asked for a "sure fire" Keltner/Bollinger squeeze buy setup. Real
TTM Squeeze (Bollinger-inside-Keltner) logic already existed in
`squeeze_analyzer.py`'s `_compression_score()` — but only as one 15-point
component buried inside an 8-module composite score, never isolated as its
own standalone signal and never independently backtested. `ttm_squeeze_engine.py`
extracts that exact same BB(20,2)/KC(20,1.5×ATR) math into a standalone
walk-forward engine (squeeze ON when BB sits entirely inside KC; squeeze
FIRES the bar it expands back out; direction from TTM's real published
momentum histogram — `linreg(close - avg(donchian_mid_20, sma_20), 20)`, not
an invented proxy) and backtests it honestly before making any claim.

No "sure fire" claim is or was ever going to be made without real evidence —
same discipline as every other engine in this codebase (see AETHER, DRUCK,
RSI-ML, Gamma Ramp, CVD Regime sections of `CLAUDE.md`, all of which shipped
with real backtests before any live-arming decision).

## Method

`tests/backtest_ttm_squeeze.py` drives `ttm_squeeze_engine.compute_series()`
(the full position state machine — 1.5× ATR stop, 3× ATR target, both long
and short) over real daily bars, 2022-01-03 through 2026-07-29, pulled via
Robinhood MCP `get_equity_historicals` (same real-data channel used for every
other backtest in this codebase — DRUCK/CIE/Breakout/MM-Intel/CVD Regime).
7 symbols: SPY, QQQ, IWM, NVDA, TSLA, AMC, GME — 1,146 real daily bars each,
zero interpolated bars (checked). No lookahead: entries fill at the fire
bar's own close (Bollinger/Keltner values at that bar are fully known at
that bar's close, unlike an intraday breakout), exits checked on each
subsequent bar's close only.

## Results

| Symbol | Bars | Fires | Trades | Win% | Avg Trade | PF | Strategy Return | Buy & Hold |
|---|---|---|---|---|---|---|---|---|
| SPY  | 1146 | 24 | 15 | 53.3% | +1.667% | 2.39 | **+26.45%** | +52.70% |
| QQQ  | 1146 | 19 | 15 | 20.0% | -1.462% | 0.45 | -20.77% | +64.74% |
| IWM  | 1146 | 27 | 20 | 30.0% | -0.580% | 0.76 | -12.77% | +28.07% |
| NVDA | 1146 | 22 | 17 | 23.5% | -4.892% | 0.36 | **-60.95%** | **+530.82%** |
| TSLA | 1146 | 25 | 22 | 40.9% | +2.198% | 1.37 | +25.41% | -25.41% |
| AMC  | 1146 | 31 | 23 | 34.8% | -0.065% | 0.99 | -42.06% | -98.37% |
| GME  | 1146 | 31 | 22 | 36.4% | -1.484% | 0.83 | -49.68% | -42.84% |

**Aggregate: 134 trades, 34.3% win rate, PF 0.901, net losing.**

Params used (real published TTM Squeeze defaults, not tuned): BB(20, 2.0σ),
KC(20, 1.5× ATR), momentum lookback 20, 1.5× ATR stop / 3× ATR target
(~1:2 R:R, same stop-multiplier convention already used elsewhere in this
codebase — `robinhood_executor_sml.py`'s `ATR_STOP_MULTIPLIER`).

## The finding that actually matters

Only 2 of 7 symbols (SPY, TSLA) were net profitable. The rest lose money
outright — and on the two names with the biggest real trending moves in this
window, the strategy didn't just fail to capture the trend, it actively lost
money fighting it: **NVDA -60.95% strategy vs +530.82% buy-and-hold; QQQ
-20.77% strategy vs +64.74% buy-and-hold.** A squeeze-fire signal firing 19-31
times over 4.5 years on a strongly trending name and losing money on the
round trips is a real, measured finding, not a parameter-tuning problem —
the signal is trading noise around a trend it isn't actually predicting.

## Honest context for why this doesn't match "scanners catching 200-600% moves"

Real Bollinger/Keltner squeeze logic (the same math many retail scanner
tools market) does not, on this honest test, reliably front-run big moves.
Content showing scanners "catching" huge moves over and over is near-certain
survivorship bias — scanning thousands of tickers and posting the rare
outlier hit, never the much larger number of false fires. This backtest is
the opposite of that: every fire on every symbol over the full window is
counted, wins and losses alike.

## What this does NOT do

- Does not get wired to any scanner (`*_scanner.py`) or to `iam_executor.py`.
- Does not get added to `IAM_PRIMARY_SYSTEM`.
- Is not represented as validated or "coming soon" anywhere in product copy.
- `squeeze_analyzer.py`'s existing 8-module composite score is untouched —
  this finding is about the SQUEEZE COMPONENT in isolation, not a claim that
  the full composite score (which also weighs volume, momentum, RSI, money
  flow, structure, trend, Z-score) is equally weak. That composite has its
  own separate, already-live role in `squeeze_fuel_engine.py`'s Ignition
  score — not re-litigated here.

## Correctness verification (operator asked "make sure you're writing these backtests correctly")

Before the refinement below, the arithmetic itself was independently checked
two ways, both against real NVDA data:

1. **Momentum isn't degenerate.** 1,105 real readings, range -17.84 to
   +25.27, 669 positive / 436 negative / zero exactly-zero — real variance,
   not the "flat/near-no-op formula" bug class that wrecked CVD Regime
   earlier this session.
2. **A real closed trade was hand-verified independent of the engine.**
   First NVDA trade: entered 2022-03-18 at $26.453 (long), exited
   2022-04-07 at $24.208 (stop). Manually recomputed
   `(24.208 - 26.453) / 26.453 = -8.4868%` matches the engine's own
   `pnl_pct` output exactly.

Also worth noting: the entry-fill assumption (filling at the signal bar's
own close) is mildly *generous*, not harsh — same convention already used by
`breakout_engine.py`. A stricter next-bar-open fill would likely make results
look *worse*, not better, so this isn't a source of false-negative bias.

## Mechanical-rule refinement (operator-specified, 2026-07-30)

The operator provided a much more specific, disciplined mechanical rule set
than the naive "any fire, any nonzero momentum" version above: require a
minimum squeeze duration before a fire counts (5-6+ consecutive "red dots"),
require momentum to be both directionally aligned **and accelerating** (not
just non-zero sign), an optional higher-timeframe trend filter, and an
optional momentum-flip exit instead of a fixed R:R target. All four were
implemented as togglable `SqueezeParams` (default: `min_squeeze_bars=5`,
`require_momentum_slope=True`, `use_htf_filter=False`,
`exit_mode="atr_target"` — the original less-selective behavior above is
still reachable by setting `min_squeeze_bars=1, require_momentum_slope=False`).

10 smoke tests confirm each new gate/exit actually behaves as specified
(`tests/test_ttm_squeeze_engine_smoke.py`) — including one case where the
first version of a test was itself wrong (assumed a 2-bar compression when
the real `in_squeeze[]` output showed a 47-bar streak from an earlier tight
period bleeding into the test's window) and was fixed by verifying the real
engine output rather than assuming bar counts, not by weakening the assertion.

### Results, same 7 symbols/window, 4 configurations

| Configuration | Trades | Win% | Avg Trade | PF |
|---|---|---|---|---|
| Naive (original, no filters) | 134 | 34.3% | -0.578% | 0.901 |
| **Refined: 5-bar min squeeze + momentum slope, ATR target exit** | 68 | 33.8% | +0.199% | **1.042** |
| Refined + momentum-flip exit (instead of ATR target) | 68 | 27.9% | -1.060% | 0.781 |
| Refined + HTF 50-SMA trend filter, ATR target exit | 43 | 34.9% | +0.171% | 1.035 |
| Refined + HTF filter + momentum-flip exit | 43 | 30.2% | -0.295% | 0.939 |

**Verdict stands: still not a real edge, but the mechanical rules genuinely
help.** The best configuration (5-bar minimum compression + momentum-slope
confirmation, keeping the ATR target exit) moves PF from 0.901 to 1.042 and
average trade from -0.578% to +0.199% — a real, measured improvement, not
noise in the wrong direction. But at 68 trades and PF barely above 1.0, this
is well within statistical noise for a real edge claim (see the CVD Regime
section of `CLAUDE.md` for what happens to numbers like this under an
out-of-sample split — apparent edges at this trade count and PF level
routinely don't survive). The momentum-flip exit made things WORSE in both
tests, not better — cutting winners short without the ATR target's larger
per-trade payoff hurt more than the tighter exit helped. The HTF filter
mainly reduced trade count (more selective) without meaningfully changing
the per-trade edge.

**Still not wired to any scanner or `IAM_PRIMARY_SYSTEM`.** PF ~1.04 on 43-68
trades is "roughly breakeven, maybe slightly positive" — not "sure fire,"
and not enough to clear the bar every other live-wired engine in this
codebase (CASCADE, Breakout, S/R Matrix) cleared with real trade counts.

## If this is revisited

- **Next real step, not yet done: an out-of-sample train/valid split** (same
  methodology as `tests/optimize_cvd_regime.py`) on the refined-rules
  configuration specifically, before concluding the 1.042 PF is real signal
  rather than this particular window's noise. This is the honest next lever,
  not another naive parameter sweep.
- No scanner/live-wiring without that split clearing out-of-sample.
