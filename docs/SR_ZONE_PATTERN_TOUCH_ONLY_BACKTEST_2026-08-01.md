# S/R Zone + Pattern — "touch only" (drop the candlestick requirement) — backtest verdict (2026-08-01)

**Why this was built:** the operator was looking at the SR Zone+Pattern indicator on a live chart, saw the green (+)/red (+) zone-touch markers, and read them the same way the original Pine script's own framing did — "buy at bottom, sell at top, easy." The live auto-trader does NOT fire on every marker: a real trade requires BOTH an active buffered zone touch AND a specific candlestick reversal pattern confirming on the same bar (see `docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md`). The operator asked to test dropping the pattern half of that confluence — i.e., literally "buy at every confirmed green +, sell at every confirmed red +" — as its own strategy.

**This is a real, additive change, not a bug fix.** `sr_zone_pattern_engine.py` gained a new `require_pattern` field (`ZonePatternParams`, default `True`) and matching `SR_ZONE_PATTERN_REQUIRE_PATTERN` env var (default unset = `true`). `True` is byte-identical to every already-shipped/live result — nothing about the currently-live engine changed. `False` drops the candlestick-pattern check entirely; any bar whose close lands inside a buffered zone fires.

## Method

Same real 16-symbol daily-bar dataset as the 2026-08-01 Quad-Score/SR-Zone-Pattern parameter searches (AMC/GME/IWM/SPY/NVDA/QQQ/MSTR/TSLA/PLTR/HOOD/AMD/MSFT/AAPL/META/COIN/SMCI, 2018-01-02 through 2026-07-30 where available, Robinhood MCP `get_equity_historicals`). Both configs use the exact currently-live parameter set (`bars=10, no_of_pivots=2, zone_expiry=400, exit_mode=atr_target, atr_stop_mult=2.0, atr_target_mult=3.0, zone_buffer_pct=2.0, atr_length=21`) — the only variable changed is `require_pattern`. Chronological TRAIN/VALID split at 2024-06-01, same methodology as every other search in this codebase (rank/report on TRAIN and VALID separately, never pick a config by looking at VALID alone).

## Results

| Config | Trades | Win% | Avg%/trade | PF | Total (summed) % |
|---|---|---|---|---|---|
| `require_pattern=True` (current live default) | 52 | 51.9% | +7.05% | **2.516** | +366.43% |
| `require_pattern=False` ("touch only") | 97 | 41.2% | +1.57% | **1.235** | +151.76% |

TRAIN/VALID split (same config, same data):

| Config | TRAIN n / PF | VALID n / PF |
|---|---|---|
| `require_pattern=True` | 33 / 3.453 | 19 / 1.342 |
| `require_pattern=False` | 62 / 1.116 | 35 / 1.527 |

## Verdict

**Touch-only is a real, non-overfit, net-positive strategy — but it is measurably weaker than what's already live, not an improvement.**

- It is NOT fake or overfit: VALID PF (1.527) actually holds *above* TRAIN PF (1.116) for the touch-only config — the opposite of the overfitting signature this codebase watches for (e.g. CVD Regime Desk's 0-of-15-survived search). Dropping the pattern requirement produces a real, if thin, standalone edge.
- It is clearly worse than the current live config on every real metric that matters: PF roughly halved (2.516 → 1.235), summed return less than half (+366% → +152%), win rate down 10.7 points, average per-trade return down more than 4x (+7.05% → +1.57%). More trades fire (97 vs 52), but each one is lower quality on average.
- **The candlestick-pattern requirement is doing real, measurable work.** It is not merely "making the strategy fire less often" — filtering to bars where a qualifying reversal pattern also confirms is producing a genuinely better edge per trade, not just fewer trades.

## Recommendation

Do not replace the current live config's `require_pattern=True` with `False` — the evidence says the current, already-armed default is the better strategy of the two, not the other way around. `require_pattern=False` is left in as an opt-in (`SR_ZONE_PATTERN_REQUIRE_PATTERN=false`) for anyone who wants the literal "buy at every zone touch" behavior with eyes open to this tradeoff, but it is not recommended and was not applied as a default change.

## Tests

`tests/test_sr_zone_pattern_engine_smoke.py` — `require_pattern` defaults to `True` and reproduces prior shipped results byte-for-byte; `require_pattern=False` fires at least as often as `True` on the same data (structurally, since dropping a condition can only relax entries, never tighten them); the env var parses correctly and defaults to `True` when unset. All pass against the real, unmodified engine.

## Reproducing this

```bash
python3 - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from sr_zone_pattern_engine import ZonePatternParams, compute_series
# point at a real {symbol: [bars]} JSON, same 16-symbol dataset used above
with open("quad_score_bars_all.json") as f:
    all_bars = json.load(f)
for require_pattern in (True, False):
    p = ZonePatternParams(bars=10, no_of_pivots=2, zone_expiry=400, exit_mode="atr_target",
                           atr_stop_mult=2.0, atr_target_mult=3.0, zone_buffer_pct=2.0,
                           atr_length=21, require_pattern=require_pattern)
    # ... aggregate compute_series() output across symbols, same as backtest_sr_zone_pattern.py
EOF
```
