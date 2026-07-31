"""
Squeeze Fuel Funnel Diagnostics
===============================
Answers the one question nobody in this codebase can currently answer:

    "My squeeze engine is armed and live. Is it actually firing, and if not,
     WHICH gate is killing the setups?"

`squeeze_fuel_engine.analyze()` requires SEVEN conditions to align before it
returns a BUY: composite >= 70, bullish direction, a fresh RSI-cross-above-50,
a real recent options-flow anomaly, and three refinement gates that must not
be blocking (short interest, earnings blackout, IV rank). Each was added for a
defensible reason. **Nobody has ever measured how often all seven align.**

That matters because an engine firing twice a month looks IDENTICAL, from the
outside, to a quiet market. There is no alert for "your entry conditions are
mutually near-exclusive." This module makes that state visible.

The precedent is direct and recent: `cvd_regime_engine`'s conviction filter
turned out to be a complete no-op for any threshold from 17 to 83 -- flat
scoring meant an aligned bar always scored >=84 or <=16, so the knob could
never bind. That was only ever found by MEASURING the distribution rather than
reasoning about the code. Same class of blind spot, same remedy.

What this records (all of it real, observed, never estimated)
------------------------------------------------------------
Per evaluation, one row:
  • the first gate that blocked it, in the engine's own evaluation order, so
    every rejection attributes to exactly one gate and the counts sum cleanly;
  • the FULL gate state, so co-occurrence is visible -- "flow blocked it, but
    RSI would have blocked it too" is a different problem from "flow was the
    only thing in the way";
  • whether a failed gate failed for lack of DATA or because real data said
    no. This distinction decides the fix: no data means wire up a source
    (e.g. FINRA credentials that are still unset), while real-data-says-no is
    a threshold or logic question. Conflating them wastes the whole exercise;
  • the composite score and its distance from the threshold, so "nothing
    fired" becomes "11 setups landed within 4 points of the line";
  • per-component availability, which surfaces a dead input directly -- an
    axis that is unavailable 100% of the time is contributing nothing to the
    composite and is silently capping the achievable score.

This module NEVER changes a trading decision. It observes `analyze()`'s real
inputs and outputs and writes them down. Nothing here can cause, block, or
resize an order.

Storage: Redis when REDIS_URL is set (survives redeploy -- the same shared
instance CASCADE/AEO/paper_trade_ledger already use), local JSON otherwise.
The JSON fallback does NOT survive a Render redeploy, and `summary()`
discloses which backend actually answered so this is never ambiguous.

Environment:
  SQUEEZE_FUNNEL_ENABLED   = true   # master switch for recording
  SQUEEZE_FUNNEL_MAX_ROWS  = 5000   # rolling cap, same convention as
                                    # paper_trade_ledger's PAPER_LEDGER_MAX_CLOSED
  SQUEEZE_FUNNEL_JSON_PATH = squeeze_funnel.json
"""

import os
import json
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger("SQUEEZE-FUNNEL")

_REDIS_URL = os.environ.get("REDIS_URL", "")
_JSON_PATH = os.environ.get("SQUEEZE_FUNNEL_JSON_PATH", "squeeze_funnel.json")
_REDIS_KEY = "squeeze_funnel:rows"


def _env_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("true", "1", "yes")


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.environ.get(key, default)))
    except (TypeError, ValueError):
        return default


ENABLED  = lambda: _env_bool("SQUEEZE_FUNNEL_ENABLED", True)
MAX_ROWS = lambda: max(100, _env_int("SQUEEZE_FUNNEL_MAX_ROWS", 5000))

_lock = threading.Lock()
_rows: list = []      # newest last; capped at MAX_ROWS
_loaded = False


# Gate identifiers, in the engine's own evaluation order. Kept as constants so
# the recorder, the summary and the tests all refer to the same strings and
# cannot drift apart.
GATE_COMPOSITE   = "composite_below_threshold"
GATE_DIRECTION   = "direction_not_bullish"
GATE_RSI         = "rsi_not_confirmed"
GATE_FLOW        = "flow_not_confirmed"
GATE_SHORT_INT   = "short_interest_weak"
GATE_EARNINGS    = "earnings_blackout"
GATE_IV_RANK     = "iv_rank_out_of_band"
FIRED            = "fired"

GATE_ORDER = [GATE_COMPOSITE, GATE_DIRECTION, GATE_RSI, GATE_FLOW,
              GATE_SHORT_INT, GATE_EARNINGS, GATE_IV_RANK]


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"[SQUEEZE-FUNNEL] Redis unavailable ({e}) — using local JSON")
        return None


def backend_name() -> str:
    return "redis" if _get_redis() is not None else "local_json_no_redis_configured"


def _load():
    """Lazy one-time restore, so a redeploy doesn't silently reset the window
    the operator is about to draw conclusions from."""
    global _rows, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        r = _get_redis()
        raw = None
        if r is not None:
            raw = r.get(_REDIS_KEY)
        elif os.path.exists(_JSON_PATH):
            with open(_JSON_PATH) as f:
                raw = f.read()
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                _rows = loaded[-MAX_ROWS():]
                logger.info(f"[SQUEEZE-FUNNEL] restored {len(_rows)} evaluation row(s)")
    except Exception as e:
        logger.warning(f"[SQUEEZE-FUNNEL] restore failed (starting empty): {e}")


def _persist():
    """Best effort — a persistence failure must never disturb the scan loop
    this is observing."""
    try:
        snapshot = list(_rows)
        r = _get_redis()
        if r is not None:
            r.set(_REDIS_KEY, json.dumps(snapshot))
            return
        with open(_JSON_PATH, "w") as f:
            json.dump(snapshot, f)
    except Exception as e:
        logger.debug(f"[SQUEEZE-FUNNEL] persist failed (non-fatal): {e}")


# ── Classification ────────────────────────────────────────────────────────────
def classify(result: dict, entry_threshold: float) -> dict:
    """
    Pure function: given a real `squeeze_fuel_engine.analyze()` result, return
    which gate blocked it (first in the engine's evaluation order) plus the
    full gate state.

    Mirrors analyze()'s own boolean exactly. It is deliberately a SEPARATE
    reading of the same fields rather than a hook inside analyze(), so this
    diagnostic can never alter the trading decision it is measuring -- but that
    also means the two could drift apart if analyze()'s condition changes.
    `tests/test_squeeze_funnel.py` pins them together by asserting agreement on
    the fire/no-fire outcome across the real engine's own output.
    """
    # Key names are read straight off FuelComponents.as_dict() -- verified
    # against the real structure, not assumed. Getting these wrong would make
    # every row read as a zero composite and report a uniform, false
    # "composite_below_threshold", which is exactly the kind of silently-wrong
    # diagnostic this module exists to prevent.
    composite = float(result.get("composite_score") or 0.0)
    direction = str(result.get("direction") or "NEUTRAL").upper()

    rsi   = result.get("rsi_confirmation") or {}
    flow  = result.get("flow_confirmation") or {}
    si    = result.get("short_interest_check") or {}
    earn  = result.get("earnings_blackout_check") or {}
    ivr   = result.get("iv_rank_check") or {}

    rsi_confirmed  = bool(rsi.get("confirmed"))
    rsi_available  = bool(rsi.get("available"))
    flow_confirmed = bool(flow.get("confirmed"))
    flow_available = bool(flow.get("available"))
    si_blocked     = bool(si.get("blocked"))
    earn_blocked   = bool(earn.get("blocked"))
    ivr_blocked    = bool(ivr.get("blocked"))

    # First blocking gate, in analyze()'s evaluation order.
    if composite < entry_threshold:
        gate = GATE_COMPOSITE
    elif direction != "BULLISH":
        gate = GATE_DIRECTION
    elif not rsi_confirmed:
        gate = GATE_RSI
    elif not flow_confirmed:
        gate = GATE_FLOW
    elif si_blocked:
        gate = GATE_SHORT_INT
    elif earn_blocked:
        gate = GATE_EARNINGS
    elif ivr_blocked:
        gate = GATE_IV_RANK
    else:
        gate = FIRED

    # Why a fail-closed gate failed. "no real data" and "real data said no" are
    # completely different problems with completely different fixes, and
    # collapsing them into one counter would defeat the point of measuring.
    def _reason(confirmed: bool, available: bool) -> Optional[str]:
        if confirmed:
            return None
        return "no_real_data" if not available else "real_data_said_no"

    return {
        "gate": gate,
        "fired": gate == FIRED,
        "composite": round(composite, 2),
        "threshold": entry_threshold,
        "distance_to_threshold": round(entry_threshold - composite, 2),
        "direction": direction,
        "gates": {
            GATE_COMPOSITE: composite >= entry_threshold,
            GATE_DIRECTION: direction == "BULLISH",
            GATE_RSI:       rsi_confirmed,
            GATE_FLOW:      flow_confirmed,
            GATE_SHORT_INT: not si_blocked,
            GATE_EARNINGS:  not earn_blocked,
            GATE_IV_RANK:   not ivr_blocked,
        },
        "fail_reasons": {
            GATE_RSI:  _reason(rsi_confirmed, rsi_available),
            GATE_FLOW: _reason(flow_confirmed, flow_available),
        },
        "components": {
            "ignition":  {"value": (result.get("ignition") or {}).get("score"),
                          "available": bool((result.get("ignition") or {}).get("available"))},
            "ftd":       {"value": (result.get("ftd_fuel") or {}).get("score"),
                          "available": bool((result.get("ftd_fuel") or {}).get("available"))},
            "short_vol": {"value": (result.get("short_volume_fuel") or {}).get("score"),
                          "available": bool((result.get("short_volume_fuel") or {}).get("available"))},
            "gamma":     {"value": (result.get("gamma_amplifier") or {}).get("score"),
                          "available": bool((result.get("gamma_amplifier") or {}).get("available"))},
        },
    }


def record(symbol: str, result: dict, entry_threshold: float) -> Optional[dict]:
    """
    Observe one real analyze() evaluation. Returns the classification (useful
    for logging at the call site) or None when disabled.

    Never raises into the caller: this sits inside a live scan loop and a
    diagnostic must not be able to break the thing it measures.
    """
    if not ENABLED():
        return None
    try:
        _load()
        row = classify(result, entry_threshold)
        row["symbol"] = (symbol or "").upper().strip()
        row["ts"] = time.time()
        with _lock:
            _rows.append(row)
            if len(_rows) > MAX_ROWS():
                del _rows[:len(_rows) - MAX_ROWS()]
        _persist()
        return row
    except Exception as e:
        logger.warning(f"[SQUEEZE-FUNNEL] record failed for {symbol} (non-fatal): {e}")
        return None


# ── Reporting ─────────────────────────────────────────────────────────────────
def summary(window_hours: float = 0.0, near_miss_points: float = 5.0) -> dict:
    """
    The report that answers "which gate is killing my setups."

    window_hours=0 means the whole retained window. `near_miss_points` defines
    how close to the threshold counts as a near miss.
    """
    _load()
    now = time.time()
    with _lock:
        rows = list(_rows)
    if window_hours > 0:
        cutoff = now - window_hours * 3600.0
        rows = [r for r in rows if r.get("ts", 0) >= cutoff]

    total = len(rows)
    if total == 0:
        return {
            "status": "no_data",
            "message": ("No evaluations recorded yet. The scanner writes a row per "
                        "symbol per pass while SQUEEZE_FUNNEL_ENABLED is true — if this "
                        "stays empty during market hours, the scanner itself is not "
                        "running, which is its own finding."),
            "backend": backend_name(),
            "total_evaluations": 0,
        }

    fired = sum(1 for r in rows if r.get("fired"))
    blockers = {g: 0 for g in GATE_ORDER}
    for r in rows:
        g = r.get("gate")
        if g in blockers:
            blockers[g] += 1

    # How often each gate passed, independent of whether it was THE blocker.
    # A gate that passes 2% of the time is the binding constraint even if an
    # earlier gate usually rejects first and hides it from the blocker counts.
    pass_rates = {}
    for g in GATE_ORDER:
        seen = [r for r in rows if g in (r.get("gates") or {})]
        if seen:
            passed = sum(1 for r in seen if r["gates"][g])
            pass_rates[g] = {
                "passed": passed,
                "evaluated": len(seen),
                "pass_rate_pct": round(passed / len(seen) * 100.0, 1),
            }

    # Why the two fail-closed gates failed — data absent vs data said no.
    fail_reasons = {}
    for g in (GATE_RSI, GATE_FLOW):
        no_data = sum(1 for r in rows if (r.get("fail_reasons") or {}).get(g) == "no_real_data")
        said_no = sum(1 for r in rows if (r.get("fail_reasons") or {}).get(g) == "real_data_said_no")
        fail_reasons[g] = {"no_real_data": no_data, "real_data_said_no": said_no}

    # Component availability — a permanently-unavailable axis silently caps the
    # maximum achievable composite and is a data problem, not a tuning problem.
    comp_avail = {}
    for key in ("ignition", "ftd", "short_vol", "gamma"):
        avail = sum(1 for r in rows if ((r.get("components") or {}).get(key) or {}).get("available"))
        comp_avail[key] = {
            "available_count": avail,
            "available_pct": round(avail / total * 100.0, 1),
        }

    composites = [r.get("composite", 0.0) for r in rows]
    composites_sorted = sorted(composites)
    threshold = rows[-1].get("threshold", 70.0)
    near_miss = [r for r in rows
                 if not r.get("fired") and 0 < r.get("distance_to_threshold", 999) <= near_miss_points]

    top_blocker = max(blockers.items(), key=lambda kv: kv[1]) if any(blockers.values()) else (None, 0)

    def _pct(p):
        if not composites_sorted:
            return None
        i = min(len(composites_sorted) - 1, max(0, int(round(p / 100.0 * (len(composites_sorted) - 1)))))
        return round(composites_sorted[i], 2)

    return {
        "status": "ok",
        "backend": backend_name(),
        "window_hours": window_hours or "all_retained",
        "total_evaluations": total,
        "fired": fired,
        "fire_rate_pct": round(fired / total * 100.0, 2),
        "entry_threshold": threshold,
        "top_blocker": {"gate": top_blocker[0], "count": top_blocker[1],
                        "pct_of_all": round(top_blocker[1] / total * 100.0, 1)},
        "blocked_by": {g: {"count": c, "pct_of_all": round(c / total * 100.0, 1)}
                       for g, c in blockers.items()},
        "gate_pass_rates": pass_rates,
        "fail_closed_reasons": fail_reasons,
        "component_availability": comp_avail,
        "composite_distribution": {
            "min": round(min(composites), 2),
            "p25": _pct(25), "median": _pct(50), "p75": _pct(75), "p90": _pct(90),
            "max": round(max(composites), 2),
            "mean": round(sum(composites) / total, 2),
        },
        "near_misses": {
            "within_points": near_miss_points,
            "count": len(near_miss),
            "symbols": sorted({r.get("symbol") for r in near_miss if r.get("symbol")})[:25],
        },
        "interpretation": _interpret(total, fired, blockers, pass_rates, fail_reasons,
                                     comp_avail, len(near_miss)),
        "disclosure": (
            "These are real recorded evaluations of the live engine, not a backtest "
            "and not evidence of profitability. This report says which conditions are "
            "binding and which inputs are dead — it says nothing about whether firing "
            "more often would make or lose money."
        ),
    }


def _interpret(total, fired, blockers, pass_rates, fail_reasons, comp_avail, near_miss_count) -> list:
    """Plain-language findings derived strictly from the recorded numbers.
    Each line states what was measured; none of them recommend a trade."""
    out = []
    if fired == 0:
        out.append(f"ZERO fires across {total} evaluations — the engine is armed but has "
                   f"never cleared its own entry conditions in this window.")
    else:
        out.append(f"{fired} fire(s) in {total} evaluations ({fired/total*100:.2f}%).")

    for key, label in (("ignition", "Ignition"), ("ftd", "FTD fuel"),
                       ("short_vol", "Short-volume"), ("gamma", "Gamma")):
        pct = comp_avail.get(key, {}).get("available_pct", 0.0)
        if pct == 0.0:
            out.append(f"{label} data was NEVER available — that axis is contributing 0 to "
                       f"every composite, capping the achievable score. This is a data-source "
                       f"problem, not a threshold problem.")
        elif pct < 25.0:
            out.append(f"{label} data available only {pct}% of the time — mostly contributing 0.")

    for g in (GATE_RSI, GATE_FLOW):
        r = fail_reasons.get(g, {})
        nd, sn = r.get("no_real_data", 0), r.get("real_data_said_no", 0)
        if nd and nd >= sn:
            out.append(f"'{g}' failed mostly for LACK OF DATA ({nd} vs {sn} real rejections) — "
                       f"this is a fail-closed gate, so missing data silently blocks entries. "
                       f"Wiring the source up is the fix, not lowering a threshold.")

    for g, stats in (pass_rates or {}).items():
        if stats["evaluated"] >= 20 and stats["pass_rate_pct"] <= 2.0:
            out.append(f"'{g}' passed only {stats['pass_rate_pct']}% of {stats['evaluated']} "
                       f"evaluations — it is the binding constraint regardless of blocker order.")

    if fired == 0 and near_miss_count > 0:
        out.append(f"{near_miss_count} setup(s) landed within the near-miss band of the "
                   f"composite threshold — the score is close, so the composite is not the "
                   f"only thing standing in the way.")
    return out


def reset() -> dict:
    """Clear the recorded window (e.g. after changing gate configuration, so
    the next report measures the new configuration cleanly)."""
    global _rows
    with _lock:
        n = len(_rows)
        _rows = []
    _persist()
    return {"status": "ok", "cleared": n}
