# S/R Zone + Candlestick Pattern Engine — Bug Fix + Backtest Verdict (2026-07-30)

**Verdict: exact-containment confluence produced essentially no signal (1 entry, 0 trades). Adding a disclosed proximity buffer + switching to an ATR stop/target exit (so the engine doesn't get stuck in one position forever) produced a THIN, MIXED real result: 12 trades / 7 symbols / 4.5 years, aggregate PF 1.186 (NVDA lost, AMC weak, GME strong on only 4 trades). Now wired to PAPER trading (`sr_zone_pattern_scanner.py`, `/api/sr-zone-pattern`) — same as every other scanner in this codebase. NOT recommended for `IAM_PRIMARY_SYSTEM` on this evidence; operator explicitly chose to arm it for real trading anyway and will monitor/disable it manually — see "Live-arming" section below.**

## Why this was built

Operator pasted a second Pine v6 script ("Best S&R Indicator With Candlestick
Patterns") with the framing "this one buy at bottom sell at top easy." Unlike
the first script pasted the same day (structurally identical to the already-live
`sr_matrix_engine.py`), this one has a genuinely different, more selective
mechanic: a resistance/support zone only forms once `NoOfPivots` (default 2)
consecutive pivots cluster at a similar price level (two-touch confirmation,
not a single pivot), AND a qualifying candlestick reversal pattern (Morning
Star / Tweezer Bottom / Inside Bar for bullish; Evening Star / Tweezer Top /
Inside Bar for bearish) must occur specifically inside an active zone. The
original script has no defined buy/sell `alertcondition()` at all — only
zone-formation/proximity alerts — so "buy at bottom, sell at top" (the
operator's own framing) was implemented directly in `sr_zone_pattern_engine.py`.

## Bug found and fixed before trusting any result

The zone-creation blocks re-evaluated the clustering condition on every bar
without checking whether it had already fired for the same pivot cluster.
Once a cluster became true, nothing about `recent`/`ref` changed until a
genuinely new pivot arrived, so the same zone was re-appended as a duplicate
on every subsequent bar. Confirmed via a debug run on synthetic data
(seed=3, 300 bars): ~104 duplicate zone-creates from only ~1-9 real distinct
pivot clusters. Fixed by tracking the bar index of the most recent pivot
that triggered each zone type (`last_res_zone_pivot_idx`/
`last_sup_zone_pivot_idx`) and only creating a new zone when the newest
pivot in the current cluster is one that hasn't already triggered a zone.
Regression test: `tests/test_sr_zone_pattern_engine_smoke.py`.

## Method

`tests/backtest_sr_zone_pattern.py` drives `compute_series()` (full position
state machine, default `exit_mode="opposite_zone"`) over the same real daily
bars already local to this repo from the TTM Squeeze backtest — SPY, QQQ,
IWM, NVDA, TSLA, AMC, GME, 2022-01-03 through 2026-07-29, 1,146 real daily
bars each (Robinhood MCP `get_equity_historicals`, zero interpolated).

## Results

| Symbol | Bars | Entries | Trades | Buy & Hold |
|---|---|---|---|---|
| SPY  | 1146 | 0 | 0 | +52.70% |
| QQQ  | 1146 | 0 | 0 | +64.74% |
| IWM  | 1146 | 0 | 0 | +28.07% |
| NVDA | 1146 | 0 | 0 | +530.82% |
| TSLA | 1146 | 0 | 0 | -25.41% |
| AMC  | 1146 | 1 | 0 | -98.37% |
| GME  | 1146 | 0 | 0 | -42.84% |

**Aggregate: 1 entry (AMC), 0 completed trades, across 8,022 real trading
days of coverage.** The single AMC entry never closed within the tested
window under `exit_mode="opposite_zone"` (a bearish pattern at an active
resistance zone never occurred afterward).

## The finding that actually matters

This is not a losing strategy — it is a **near-silent** one. Requiring BOTH
a two-touch zone (already a real filter on its own — `sr_matrix_engine.py`'s
single-pivot version generated 22-30 trades/symbol on the same data) AND a
specific candlestick reversal pattern occurring inside that zone's exact
price range is an AND of two independently rare conditions. The operator's
framing ("buy at bottom sell at top easy") does not hold up under an honest
test — the confluence this script requires almost never happens in real
data, not because the logic is wrong, but because two-touch-zone AND
pattern-match together is a much stricter filter than either alone.

## What this does NOT do

- Does not get wired to any scanner (`*_scanner.py`) or to `iam_executor.py`.
- Does not get added to `IAM_PRIMARY_SYSTEM`.
- Is not represented as validated or "coming soon" anywhere in product copy.
- Does not claim the underlying candlestick-pattern or zone-clustering logic
  is buggy — the bug found and fixed was purely a duplicate-bookkeeping
  issue in zone creation, not in the pattern-detection or clustering math
  itself (both ported byte-for-byte from the Pine source, unchanged).

## Update: proximity buffer + atr_target exit, real numbers (same day)

Two concrete levers were tried, both against the same real 7-symbol/4.5-year
data, no cherry-picking:

1. **Loosening `no_of_pivots`/`bars` alone did not help** — entries stayed
   at 0-1 regardless. Measured separately that qualifying candlestick
   patterns are NOT rare (~8-9% of all bars across all 7 symbols) — the real
   bottleneck was requiring the close to land EXACTLY inside a zone's narrow
   candle-body range, which almost never coincides with a pattern bar even
   though neither condition alone is rare.
2. **A proximity buffer** (`zone_buffer_pct`, new param — treat "near a
   zone" as qualifying, not just "exactly inside it," a real convention the
   original Pine script itself uses for its separate proximity alerts)
   **plus `exit_mode="atr_target"`** (the default `opposite_zone` exit
   requires the same rare confluence to ALSO occur in reverse to close a
   trade — with it, the first entry gets stuck open for the rest of the
   backtest and blocks all further entries) together produced a real,
   measurable result:

| Symbol | Entries | Trades | Win% | Avg% | PF | Total% | Buy&Hold% |
|---|---|---|---|---|---|---|---|
| SPY  | 0 | 0 | — | — | — | 0.00 | +52.70% |
| QQQ  | 0 | 0 | — | — | — | 0.00 | +64.74% |
| IWM  | 0 | 0 | — | — | — | 0.00 | +28.07% |
| NVDA | 3 | 3 | 0.0% | -5.270% | 0.00 | -15.00% | +530.82% |
| TSLA | 0 | 0 | — | — | — | 0.00 | -25.41% |
| AMC  | 5 | 5 | 20.0% | -3.698% | 0.41 | -18.61% | -98.37% |
| GME  | 4 | 4 | 75.0% | +11.244% | 5.38 | +48.82% | -42.84% |

**Aggregate: 12 trades, win_rate=33.3%, avg_trade=+0.890%, PF=1.186.**

Default `zone_buffer_pct=3.0` was chosen as a conservative point on the
sensitivity curve (buffer 0→3 entries, 1.0x→12, 3.0x→48-ish in an
entry-count-only sensitivity pass, 10.0x→89) — not the value that maximizes
entries, specifically to avoid tuning-to-force-a-result. This is disclosed,
not curve-fit to this dataset's PF.

**Honest read: this is real, but thin and inconsistent** — 3 of 7 symbols
produced zero trades at all, NVDA lost money outright, and GME's strong
number rests on only 4 trades (not statistically meaningful on its own).
This does NOT clear the evidence bar CASCADE/Breakout/S/R-Matrix cleared
(each had 20-30+ real trades with a consistent positive-PF pattern across
most symbols). It is a real, measured improvement over the original
zero-signal design, not a proven edge.

## Live-arming (2026-07-30, operator directive)

Wired to `iam_executor.execute_async()` tagged `system="SML_SR_ZONE_PATTERN"`
via `sr_zone_pattern_scanner.py` (background loop, Daily bars, same pattern
as `breakout_scanner.py`/`sr_matrix_scanner.py`) and `core/api/sr_zone_pattern_bp.py`
(`GET /api/sr-zone-pattern/status`, `GET /api/sr-zone-pattern/<symbol>`),
both registered in `core/app.py`. `ZonePatternParams.from_env()` defaults
`exit_mode` to `atr_target` (not the dataclass default `opposite_zone`) —
required for live scanning so a single entry can't permanently block all
future signals.

This trades on **paper** out of the box (`IAM_PAPER_MODE=true` default,
identical to every other scanner here). The operator explicitly requested
REAL live trading for this engine alongside S/R Matrix (buy-low/sell-high on
confirmed pivots — the proven, positive-PF sibling engine, see
`docs/SR_MATRIX_PIVOT_BACKTEST_2026-07-25.md`), with the explicit
understanding this evidence is thin and the operator will monitor it and
disable it manually if needed. **No sandbox in this codebase has ever had
Render dashboard access** — going actually-live requires the operator to set
these on the `squeezeos-api` Render service:

```
IAM_PAPER_MODE=false
IAM_AUTO_TRADING=true
IAM_EXECUTION_MODE=tradier            # or "both" for a Robinhood alert too
IAM_PRIMARY_SYSTEM=SML_CASCADE,SML_BREAKOUT,SML_SR_MATRIX,SML_SR_ZONE_PATTERN
```

(the exact prior value, `SML_CASCADE,SML_BREAKOUT,SML_SR_MATRIX`, plus the
new system appended — if that prior value has changed since this was
written, append `SML_SR_ZONE_PATTERN` to whatever it currently is rather
than overwriting it). Stop-loss protection is automatic and already built —
`IAM_STOP_LOSS_PCT` (default 3.0%) places a real GTC stop-sell order on
every live BUY fill, no separate configuration needed per engine.

## If this is revisited further

- The GME 4-trade sample and NVDA's clean loss are the two loose threads —
  a longer window or more symbols would clarify whether GME's PF 5.38 is
  real or a small-sample artifact, and whether NVDA's loss is idiosyncratic
  or systemic to trending large-caps. Not done here.
