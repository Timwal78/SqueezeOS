"""
SML Triple Lock Scanner — Python port of SML_Triple_Lock_Engine_Beastmode+.pine

Runs market-wide on 15-min bars. Three EMA stacks must align:
  GEO stack  : EMA 3/9/18/36/72       — short-term price structure
  ARI stack  : EMA 13/26/39/52/65     — intermediate momentum
  MAC stack  : EMA 30/60/90/120/741   — macro anchor (requires ≥741 bars)

Volume surge (1.5× 20-bar SMA) required before LOCK fires.
Squeeze (BB inside KC) is a flag — adds urgency but not required.

Scans the top N symbols by volume ratio from the live market scanner universe.
Runs every 4 minutes on a background daemon thread.
"""

import math
import os
import time
import logging
import threading
from typing import List, Optional, Tuple

logger = logging.getLogger("SML-TL-Scanner")

# ─── CONFIG ────────────────────────────────────────────────────────────────────
_SCAN_INTERVAL_S  = 240    # re-evaluate every 4 min (15-min bars = slow-moving)
_MAX_SYMBOLS      = int(os.environ.get("TL_MAX_SYMBOLS", "60"))
_HISTORY_TTL_S    = 900    # 15-min cache on bars (they don't change mid-bar)
_MIN_BARS_FULL    = 741    # need this for MAC/741 EMA
_MIN_BARS_PARTIAL = 72     # GEO-only fallback

# ─── IN-MEMORY STORES ─────────────────────────────────────────────────────────
_results:  dict = {}   # symbol → scored result dict
_history:  dict = {}   # symbol → {"bars": [...], "ts": float}
_results_lock = threading.Lock()

# ─── MATH HELPERS ─────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    out = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
        else:
            out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def _stdev(values: List[float], period: int) -> List[Optional[float]]:
    out = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
        else:
            w = values[i - period + 1 : i + 1]
            mean = sum(w) / period
            out.append(math.sqrt(sum((x - mean) ** 2 for x in w) / period))
    return out


def _stack_state(series: List[List[float]], idx: int) -> Tuple[bool, bool]:
    """Returns (is_bull, is_bear) for a list of EMA series at bar index."""
    vals = [s[idx] for s in series]
    bull = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
    bear = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    return bull, bear


def _alignment_pts(series: List[List[float]], idx: int) -> Tuple[int, int]:
    """Count bull/bear alignment points (0–4 per stack of 5 EMAs)."""
    bull_pts = sum(
        1 for i in range(len(series) - 1) if series[i][idx] > series[i + 1][idx]
    )
    bear_pts = sum(
        1 for i in range(len(series) - 1) if series[i][idx] < series[i + 1][idx]
    )
    return bull_pts, bear_pts


# ─── TRIPLE LOCK SCORING ──────────────────────────────────────────────────────

def _score(symbol: str, bars: List[dict]) -> dict:
    """
    bars: list of {close, open, high, low, volume} dicts, oldest-first.
    Returns a scored result dict — always returns something, never raises.
    """
    try:
        closes  = [float(b.get("close",  b.get("c", 0))) for b in bars]
        highs   = [float(b.get("high",   b.get("h", closes[i]))) for i, b in enumerate(bars)]
        lows    = [float(b.get("low",    b.get("l", closes[i]))) for i, b in enumerate(bars)]
        volumes = [float(b.get("volume", b.get("v", 0))) for b in bars]

        n = len(closes)
        if n < _MIN_BARS_PARTIAL:
            return {"symbol": symbol, "state": None, "reason": f"only {n} bars (need ≥{_MIN_BARS_PARTIAL})"}

        idx = n - 1

        # ── GEO stack
        g_series = [_ema(closes, p) for p in (3, 9, 18, 36, 72)]
        geo_bull, geo_bear = _stack_state(g_series, idx)
        g_bull_pts, g_bear_pts = _alignment_pts(g_series, idx)

        # ── ARI stack
        a_series = [_ema(closes, p) for p in (13, 26, 39, 52, 65)]
        ari_bull, ari_bear = _stack_state(a_series, idx)
        a_bull_pts, a_bear_pts = _alignment_pts(a_series, idx)

        # ── MAC stack (graceful degrade)
        has_mac = n >= _MIN_BARS_FULL
        if has_mac:
            m_series = [_ema(closes, p) for p in (30, 60, 90, 120, 741)]
            mac_bull, mac_bear = _stack_state(m_series, idx)
            m_bull_pts, m_bear_pts = _alignment_pts(m_series, idx)
            mac741_val = m_series[4][idx]
        else:
            mac_bull = mac_bear = False
            m_bull_pts = m_bear_pts = 0
            mac741_val = None

        # ── Triple lock
        triple_call = geo_bull and ari_bull and mac_bull
        triple_put  = geo_bear  and ari_bear  and mac_bear

        # ── Volume surge
        vol_sma = _sma(volumes, 20)
        vol_surge = (
            vol_sma[idx] is not None
            and volumes[idx] > vol_sma[idx] * 1.5
        )

        # ── Squeeze: BB inside KC
        bb_basis = _sma(closes, 20)
        bb_std   = _stdev(closes, 20)
        trs = [
            max(highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]) if i > 0 else 0,
                abs(lows[i]  - closes[i - 1]) if i > 0 else 0)
            for i in range(n)
        ]
        kc_basis = _ema(closes, 20)
        kc_range = _ema(trs, 20)

        in_squeeze = False
        if bb_basis[idx] is not None and bb_std[idx] is not None:
            bb_u = bb_basis[idx] + 2.0 * bb_std[idx]
            bb_l = bb_basis[idx] - 2.0 * bb_std[idx]
            kc_u = kc_basis[idx] + 1.5 * kc_range[idx]
            kc_l = kc_basis[idx] - 1.5 * kc_range[idx]
            in_squeeze = (bb_u < kc_u) and (bb_l > kc_l)

        # ── Confluence score (-12 to +12, or -8 to +8 without MAC)
        net_score = (
            (g_bull_pts + a_bull_pts + m_bull_pts) -
            (g_bear_pts + a_bear_pts + m_bear_pts)
        )
        max_score = 12 if has_mac else 8

        # ── Final state (volume gate required for LOCK)
        if triple_call and vol_surge:
            state = "LOCK_CALL"
        elif triple_put and vol_surge:
            state = "LOCK_PUT"
        elif triple_call:
            state = "CALL_FORMING"   # structure aligned, no volume yet
        elif triple_put:
            state = "PUT_FORMING"
        else:
            state = "STANDBY"

        return {
            "symbol":      symbol,
            "state":       state,
            "net_score":   net_score,
            "max_score":   max_score,
            "in_squeeze":  in_squeeze,
            "vol_surge":   vol_surge,
            "geo":         "BULL" if geo_bull else ("BEAR" if geo_bear else "MIX"),
            "ari":         "BULL" if ari_bull else ("BEAR" if ari_bear else "MIX"),
            "mac":         ("BULL" if mac_bull else ("BEAR" if mac_bear else "MIX")) if has_mac else "DEGRADED",
            "has_mac":     has_mac,
            "bars":        n,
            "price":       closes[idx],
            "mac741":      round(mac741_val, 4) if mac741_val else None,
            "ts":          time.time(),
        }

    except Exception as e:
        logger.warning(f"[TL-SCAN] score error {symbol}: {e}")
        return {"symbol": symbol, "state": None, "reason": str(e)}


# ─── HISTORY FETCH ─────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, tradier) -> List[dict]:
    """
    Pull 35 days of 15-min bars from Tradier (≈910 bars on active symbols).
    Caches per symbol for 15 minutes.
    """
    now = time.time()
    cached = _history.get(symbol)
    if cached and (now - cached["ts"]) < _HISTORY_TTL_S:
        return cached["bars"]

    try:
        import tradier_api as ta
        bars = ta.get_timesales(symbol, interval="15min", days_back=35)
        if bars:
            _history[symbol] = {"bars": bars, "ts": now}
            return bars
    except Exception as e:
        logger.warning(f"[TL-SCAN] bar fetch failed {symbol}: {e}")

    return []


# ─── IAM PRIORITY INTEGRATION ─────────────────────────────────────────────────

_TL_IAM_SEMAPHORE = threading.Semaphore(3)  # max 3 concurrent IAM resolves from TL


def _trigger_iam_resolution(symbol: str, tl_result: dict):
    """
    When Triple Lock fires LOCK_CALL/LOCK_PUT, immediately trigger IAM resolution
    for that symbol — bypasses the 45s IAM cache and runs ahead of the next scheduled
    IAM cycle. Runs in a daemon thread; never blocks the scan loop.

    Direction guard: if TL and IAM disagree (e.g., TL=CALL but IAM=SELL), execution
    is suppressed and the conflict is logged. IAM always wins on direction.
    """
    def _do():
        if not _TL_IAM_SEMAPHORE.acquire(blocking=False):
            logger.info(f"[TL-IAM] {symbol}: semaphore full — IAM resolve deferred")
            return
        try:
            from iam_engine import IAMEngine
            from core.legacy import get_service
            from iam_executor import execute_from_resolution

            engine = IAMEngine({
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
            })
            result = engine.resolve(symbol)

            if "error" in result:
                logger.warning(f"[TL-IAM] {symbol} resolve error: {result.get('error')}")
                return

            action     = result["resolution"]["action"]
            window     = result["truth_layer"]["time_window"]
            confidence = result["resolution"]["resolution_confidence"]
            price      = float(result.get("price") or 0.0)
            tl_state   = tl_result.get("state", "")
            score      = tl_result.get("net_score", 0)
            max_score  = tl_result.get("max_score", 12)

            # Direction guard — if TL and IAM disagree, log and skip execution
            if tl_state == "LOCK_CALL" and action == "SELL":
                logger.info(
                    f"[TL-IAM] {symbol}: TL=LOCK_CALL vs IAM=SELL — "
                    f"directional conflict, skipping exec (IAM wins)"
                )
                return
            if tl_state == "LOCK_PUT" and action == "BUY":
                logger.info(
                    f"[TL-IAM] {symbol}: TL=LOCK_PUT vs IAM=BUY — "
                    f"directional conflict, skipping exec (IAM wins)"
                )
                return

            # Tag the rationale so Discord embed surfaces the Triple Lock trigger
            direction_label = "CALL" if tl_state == "LOCK_CALL" else "PUT"
            squeeze_tag     = " +SQZ" if tl_result.get("in_squeeze") else ""
            orig_rationale  = result["resolution"].get("rationale", "")
            result["resolution"]["rationale"] = (
                f"[TL {direction_label} LOCK {score}/{max_score}{squeeze_tag}] {orig_rationale}"
            )

            logger.info(
                f"[TL-IAM] ✅ CONFIRMED {symbol} | TL={tl_state} | IAM={action} | "
                f"window={window} | conf={confidence:.0f}% | score={score}/{max_score}"
            )
            execute_from_resolution(symbol, result["resolution"], window, confidence, price)

        except Exception as e:
            logger.error(f"[TL-IAM] IAM resolution error for {symbol}: {e}")
        finally:
            _TL_IAM_SEMAPHORE.release()

    threading.Thread(target=_do, daemon=True, name=f"tl-iam-{symbol}").start()


# ─── BACKGROUND SCANNER ────────────────────────────────────────────────────────

def _run_tl_scan():
    """One full Triple Lock scan pass over the top-N market universe."""
    from core.api.market_scanner import _scan_cache, _scan_lock
    from core.state import sse_queues
    import core.signal_history as signal_history

    # Get current quote universe — sorted by volume ratio (highest first)
    with _scan_lock:
        quotes = dict(_scan_cache.get("quotes", {}))

    if not quotes:
        logger.debug("[TL-SCAN] no quotes yet — skipping cycle")
        return

    ranked = sorted(quotes.items(), key=lambda kv: kv[1].get("volRatio", 0), reverse=True)
    symbols = [sym for sym, _ in ranked[:_MAX_SYMBOLS]]

    # Always include mandatory anchors
    for anchor in ("IWM", "GME", "AMC"):
        if anchor not in symbols:
            symbols.append(anchor)

    import tradier_api as ta
    if not ta.is_available():
        logger.warning("[TL-SCAN] Tradier not available — skipping")
        return

    new_locks: list = []
    scored = 0

    for sym in symbols:
        bars = _fetch_bars(sym, ta)
        if not bars:
            continue

        result = _score(sym, bars)
        scored += 1

        with _results_lock:
            prev = _results.get(sym, {})
            prev_state = prev.get("state")
            _results[sym] = result

        state = result.get("state")

        # Only broadcast on new locks (state transition → LOCK_CALL/LOCK_PUT)
        if state in ("LOCK_CALL", "LOCK_PUT") and prev_state != state:
            new_locks.append(result)
            _broadcast_lock(sym, result, sse_queues, signal_history)

    fired = len(new_locks)
    logger.info(
        f"[TL-SCAN] {scored}/{len(symbols)} symbols scored | "
        f"{fired} new locks | "
        f"active locks: {sum(1 for r in _results.values() if r.get('state') in ('LOCK_CALL','LOCK_PUT'))}"
    )

    # Priority injection: trigger immediate IAM resolution for each new lock
    for lock_result in new_locks:
        _trigger_iam_resolution(lock_result["symbol"], lock_result)


def _broadcast_lock(symbol: str, result: dict, sse_queues_ref, sh):
    state = result["state"]
    event = {
        "type":        f"TL_{state}",      # TL_LOCK_CALL / TL_LOCK_PUT
        "symbol":      symbol,
        "net_score":   result["net_score"],
        "in_squeeze":  result["in_squeeze"],
        "price":       result.get("price"),
        "ts":          result["ts"],
    }
    # SSE broadcast
    dead = []
    for q in list(sse_queues_ref):
        try:
            q.put_nowait(event)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            sse_queues_ref.remove(q)
        except ValueError:
            pass

    # Signal history
    try:
        sh.record(symbol, "TL_LOCK", event)
    except Exception:
        pass

    logger.info(
        f"[TL-LOCK] {state} {symbol} | score={result['net_score']}/{result['max_score']} | "
        f"squeeze={result['in_squeeze']} | price={result.get('price')}"
    )


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def get_active_locks() -> list:
    """Return all symbols currently in LOCK_CALL or LOCK_PUT state, ranked by score."""
    with _results_lock:
        locks = [
            r for r in _results.values()
            if r.get("state") in ("LOCK_CALL", "LOCK_PUT")
        ]
    return sorted(locks, key=lambda r: abs(r.get("net_score", 0)), reverse=True)


def get_forming() -> list:
    """Return symbols in CALL_FORMING or PUT_FORMING (structure set, volume pending)."""
    with _results_lock:
        forming = [
            r for r in _results.values()
            if r.get("state") in ("CALL_FORMING", "PUT_FORMING")
        ]
    return sorted(forming, key=lambda r: abs(r.get("net_score", 0)), reverse=True)


def get_all_results() -> dict:
    with _results_lock:
        return dict(_results)


# ─── THREAD START ─────────────────────────────────────────────────────────────

_tl_thread: Optional[threading.Thread] = None


def start_tl_scanner():
    global _tl_thread
    if _tl_thread and _tl_thread.is_alive():
        return

    def _loop():
        logger.info("[TL-SCAN] SML Triple Lock Scanner started (15-min bars, market-wide)")
        time.sleep(15)  # wait for market scanner to populate quotes first
        while True:
            try:
                _run_tl_scan()
            except Exception as e:
                logger.error(f"[TL-SCAN] loop error: {e}")
            time.sleep(_SCAN_INTERVAL_S)

    _tl_thread = threading.Thread(target=_loop, daemon=True, name="SML-TL-Scanner")
    _tl_thread.start()
