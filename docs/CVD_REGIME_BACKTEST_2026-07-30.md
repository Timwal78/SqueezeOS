# SML CVD Regime Desk — bug audit + real backtest (2026-07-30)

**Verdict: NO DEMONSTRATED EDGE. Do not arm this for live trading.**
Profit factor 0.989 over 102 trades — flat to slightly negative. 4 of 5 symbols
lost money. This is not the clean negative verdict ORB/DRUCK/AETHER got, and it
is not a positive one either: the tested window is only **8 trading days in a
single down-trending regime**, which is too thin to settle the question. What it
does settle is that there is no *demonstrated* edge to justify live capital.

Source script: operator-submitted Pine v6 `"CVD Regime Fast → Call/Put Desk"`
(pasted 2026-07-30, asking for it to be fixed "for trading perfectly delta
options").

| Artifact | Path |
|---|---|
| Corrected Pine indicator | `indicators/SML_CVD_Regime_Desk_v6.pine` |
| Python engine (source of truth) | `cvd_regime_engine.py` |
| Backtest harness | `tests/backtest_cvd_regime.py` |
| Regression tests (one per bug) | `tests/test_cvd_regime_engine_smoke.py` |
| Original-vs-fixed measurement | `tests/compare_cvd_original_vs_fixed.py` |

---

## 1. Seven real bugs, each one measured rather than asserted

Every number here comes from reproducing the original formula alongside the
fixed one, in `tests/test_cvd_regime_engine_smoke.py` and
`tests/compare_cvd_original_vs_fixed.py` — not from reading the code and
guessing.

### BUG 1 (critical) — the higher-timeframe filter was measured on chart bars

```pine
htfCvdS  = request.security(syminfo.tickerid, htfTF, cvdS)
htfSlope = htfCvdS - htfCvdS[slopeLen]     // <-- indexes CHART bars
```

`request.security()` holds the last **closed** HTF value flat across every chart
bar inside the forming HTF bar. On a 5-minute chart with a 60-minute HTF that is
12 identical bars, so `htfCvdS - htfCvdS[3]` is **exactly 0.0 on 73.7% of bars**
(measured, real SPY data). On each of those bars `htfBull` and `htfBear` are both
false — and `alignedBull`, `alignedBear`, `earlyCall` and `earlyPut` *all* require
one of them, so no signal of any kind could fire.

The consequence is not what I first assumed, and the measurement corrected it:
**this did not starve the script of signals, it quantized them.** All of the
original's signals were crammed into the **26.4%** of bars where a bucket
boundary happened to fall inside the 3-bar window — i.e. the script could only
ever form an opinion in a short burst after each hourly close, and on those bars
it was reading a **1-HTF-bar difference, never the intended 3-bar slope**. It
fired 217 signals across 5 symbols (below) from only 165 eligible bars per
symbol. Both the timing and the lookback were wrong.

**Fix:** the HTF series is built natively from bar timestamps and its slope is
measured in HTF space over `slope_len` completed buckets. `request.security()` is
removed entirely, which also eliminates its realtime repaint and guarantees the
chart and the Python engine agree.

### BUG 2 — the conviction filter was a no-op at every usable setting

Scoring used flat ±14 (flow) / ±10 (price) / ±10 (HTF) off a base of 50, and
alignment requires all three to agree. So an aligned-bull bar always scored ≥84
and an aligned-bear bar always ≤16, while the gates were `score >= minConviction`
and `score <= 100 - minConviction`. For **any `minConviction` from 17 to 83** (the
default is 55) the score test was always satisfied whenever alignment held.
Measured: **only 0% of bars could land in the 25–75 band** the original's
arithmetic can't reach; the fixed engine puts **69.2%** there. Raising
`min_conviction` 55 → 90 now changes the entry count (31 → 19); in the original it
could not have changed a single signal.

**Fix:** contributions are continuous (magnitude-scaled), weights sum to 50 so a
fully-aligned max-strength bar reaches exactly 100.

### BUG 3 — `strength` divided a change by the stdev of a level

`abs(cvdSlope) / ta.stdev(cvdS, 30)` divides a 3-bar *change* in CVD by the
standard deviation of the cumulative *level*. With a daily reset the level's
stdev is dominated by session drift. Measured median **0.326**, hitting the
`math.min(strength*7, 14)` cap on only **1.5%** of bars — so the term contributed
about 2 of a possible 14 points nearly always, and could not distinguish a
violent flow impulse from a drifting one, which is its entire purpose.

**Fix:** normalize the slope by the rolling stdev of the **slope**. Median rises
to **0.948**.

### BUG 4 — the smoothed CVD carried across every session reset

`cvd` was reset daily; `ta.ema(cvd, smoothLen)` was not. The smoothed series
therefore inherited the prior session's ending CVD level, producing a large
artificial slope on the first bars of every day, in whichever direction yesterday
closed. Verified directly: with day 1 ending at a smoothed CVD of 68,400,000, the
first bar of day 2 must read its own bar delta (−200,000), not a blend.

**Fix:** re-seed the EMA on reset, clear the slope window, and refuse to signal
until `slope_len` bars into the session. The HTF slope additionally never
compares across a reset (it walks its lag down to stay inside the session rather
than blanking the first ~3 hours of the day).

### BUG 5 — exits were neither position-aware nor edge-gated

`exitLong = putSignal or (flowBear and callSignal[1])` was drawn with
`plotshape` on **every bar** the condition held — an X-cross on every bar of a
downtrend — and fired whether or not anything was ever open.

**Fix:** a real one-position-at-a-time state machine. 56 exits in the regression
run, every one paired to an open position, none while flat.

### BUG 6 — signals were evaluated on the live bar (repaint)

No `barstate.isconfirmed` anywhere, so shapes and `alertcondition()` could fire
mid-bar and then vanish. Every other v6 script in `indicators/` confirms on
close. Guarded now by a prefix-stability test: truncating the series leaves every
earlier bar byte-identical.

### BUG 7 — no risk container on a script for buying options

No stop, no target, no cooldown, no cap on flipping. Added: ATR stop
(`stop_atr=1.5`), R-multiple target (`target_r=2.0`), post-exit cooldown
(3 bars).

---

## 2. Original vs fixed, on the same real bars

`tests/compare_cvd_original_vs_fixed.py` reproduces the submitted script as
submitted (all seven bugs present) and counts its rising-edge signals.

| Symbol | Bars | Original `toCall` | Original `toPut` | Original total | HTF slope = 0 | Fixed entries | Fixed trades |
|---|---:|---:|---:|---:|---:|---:|---:|
| IWM | 624 | 18 | 25 | 43 | 73.7% | 20 | 20 |
| NVDA | 624 | 21 | 25 | 46 | 73.7% | 21 | 21 |
| QQQ | 624 | 18 | 22 | 40 | 73.7% | 20 | 20 |
| SPY | 624 | 20 | 22 | 42 | 73.7% | 22 | 22 |
| TSLA | 624 | 19 | 27 | 46 | 73.7% | 19 | 19 |
| **ALL** | | | | **217** | | **102** | **102** |

The original produced **more** signals, not fewer — the opposite of what "the
HTF filter blocks everything" suggests, and worth stating plainly because it
corrects the intuitive reading of BUG 1. The reason is BUG 2 and BUG 5 together:
with the conviction gate inert and no position state, every re-arming of a loose
`earlyCall`/`earlyPut` condition counted as a fresh signal, including while
already in a trade. **The original script has no exit logic at all, so no P&L can
be computed for it** — it was not merely unprofitable, it was un-backtestable as
a trading system. That is why the table compares signal counts, not returns.

Signal count is not signal quality. Fewer, better-timed, position-managed
signals is the improvement; the count going down is incidental.

---

## 3. Backtest method

- **Data:** real 5-minute OHLCV bars, `SPY QQQ IWM NVDA TSLA`, **2026-07-20 →
  2026-07-29, 8 trading sessions, 624 bars per symbol**, regular trading hours,
  split-adjusted. Sourced via the Robinhood MCP `get_equity_historicals`
  channel — the same real-data path used for the DRUCK, CIE, Breakout, MM-Intel
  and Gamma Ramp backtests in this repo.
- **Data hygiene:** the raw pull covered 2026-07-20 → 2026-07-30, but every bar
  of the 2026-07-30 session came back flagged `interpolated` with zero volume
  (synthetic gap-fill, per the tool's own guidance). That entire session was
  dropped rather than fed to a volume-weighted engine — 78 bars per symbol
  discarded, 0 interpolated bars in the tested set.
- **Engine:** the real, unmodified `cvd_regime_engine.compute_series()`. Nothing
  is reimplemented in the harness.
- **Trade model:** entry at the signal bar's close; ATR stop and 2R target
  checked on each subsequent bar's close; regime-flip exit; one position at a
  time; 3-bar cooldown after every exit. No intrabar fills, no lookahead
  (prefix-stability tested).
- **Costs:** no commission or slippage modelled. On a 5-minute strategy holding
  ~16–20 bars this is a modest but real omission that flatters the result.

---

## 4. Results — default config is the verdict

```
CONFIG [DEFAULT]  min_conviction=55  stop_atr=1.5  target_r=2.0  cooldown=3  htf=60m  early=True
SYM     BARS  TRD   WIN%      PF     SUM%    B&H%     AVG%  HELD
IWM      624   20   30.0   0.569    -2.38    -2.20  -0.1189  19.6
NVDA     624   21   57.1   1.905    +4.68    -8.07  +0.2230  16.5
QQQ      624   20   40.0   0.785    -1.33    -6.08  -0.0666  18.1
SPY      624   22   40.9   0.713    -1.03    -2.47  -0.0466  16.0
TSLA     624   19   36.8   0.970    -0.25   -21.85  -0.0132  20.3
ALL           102   41.2   0.989    -0.30
exit reasons: EXIT_STOP 53, EXIT_TARGET 28, EXIT_FLIP 21
long: 38 trades, -2.65%   short: 64 trades, +2.35%
```

**102 trades, 41.2% win rate, profit factor 0.989, −0.30% summed.** Only NVDA is
positive (PF 1.905). Four of five symbols lose.

### Sensitivity — is the result an artifact of one setting?

Run to check robustness, **not** to hunt for a winning configuration. Picking the
best row here as "the" result would be curve-fitting on 8 days of data.

| Config | Trades | Win% | PF | Sum% |
|---|---:|---:|---:|---:|
| **DEFAULT** | **102** | **41.2** | **0.989** | **−0.30** |
| confirmed-only (no early signals) | 89 | 44.9 | 1.071 | +1.72 |
| `min_conviction=70` | 94 | 43.6 | 0.977 | −0.63 |
| `target_r=1.0` | 140 | 47.9 | 0.904 | −3.26 |
| no flip exit | 80 | 36.2 | 0.875 | −3.92 |

Every configuration sits in a band from PF 0.875 to 1.071 — nothing decisively
wins, and nothing catastrophically loses. That is the signature of a strategy
with no measurable edge on this window, not of one config being mis-set. The
best row (confirmed-only, PF 1.071, +1.72% over 89 trades) is well inside noise
for this sample size and is **not** being promoted to the default on that basis.

### One result that looks better than it is

Short trades netted +2.35% and longs −2.65%. Every one of the five symbols fell
over the window (buy-and-hold −2.2% to −21.9%), so shorts winning is the market's
direction, not evidence the signal has a bearish edge. Equally, "TSLA only lost
0.25% versus −21.85% buy-and-hold" is what any mostly-flat strategy does in a
falling market — it is not alpha.

---

## 5. Limitations that bound this verdict

1. **8 trading sessions, one regime.** All five symbols declined. This is a thin,
   single-direction window — the same evidentiary class as the CIE
   ("inconclusive") and Trade Desk v3 ("thin evidence") verdicts in this repo,
   not the 29–56-session windows behind the ORB and DRUCK verdicts. A longer
   window spanning an up-trend could move this either way.
2. **No options economics.** The stop/target model the underlying's directional
   %-move — no premium, leverage, theta, spread or assignment — the same disclosed
   convention as `breakout_engine.py` / `druck_engine.py` / `mm_intel_engine.py`.
   For a script whose stated purpose is buying 0.30–0.40Δ options, a positive
   directional result would have been **necessary but not sufficient**. This
   result is not even positive, and that direction of inference is safe: if the
   underlying read does not pay before theta is charged, theta cannot rescue it.
3. **"CVD" is a proxy, not delta.** It is
   `volume * ((close-low) - (high-close)) / (high-low)` from ordinary OHLCV, not
   true bid/ask delta — that needs tick/quote data neither TradingView's standard
   feed nor this codebase's providers supply. Same proxy class as the OFI/DLMD
   labelling in `SML_Cycle_Intelligence_Engine_v6.pine`. A real signed-delta feed
   could plausibly change these numbers; nothing here should be read as a verdict
   on true-CVD strategies.
4. **No commission or slippage.**
5. **5-minute chart with a 60-minute HTF only.** No other timeframe pairing was
   tested.

---

## 6. What to do with this

- **Do not add `SML_CVD_DESK` to `IAM_PRIMARY_SYSTEM`** and do not flip any
  live-trading flag for it. Same bar ORB, DRUCK, AETHER, RSI-ML and Gamma Ramp
  did not clear.
- No scanner was built for it, so it has no path to the executor at all unless
  someone configures the TradingView webhook bridge (passphrase empty by default
  — it sends nothing until deliberately filled in).
- The fixed script is genuinely worth putting on a chart: the mechanics are now
  correct, tested, non-repainting, and the dashboard reports honest state
  including `Awaiting Data` when no HTF confirmation exists. Use it to *watch*
  regime and conviction, with the knowledge that its entries have no proven edge.
- **If a longer window is ever tested, re-run `tests/backtest_cvd_regime.py` and
  add a new dated doc** rather than editing this one's numbers — same convention
  the DRUCK and CIE docs follow.
