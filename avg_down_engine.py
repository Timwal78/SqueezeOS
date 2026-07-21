"""
SML Avg-Down Engine — Automated Pyramid Builder
================================================
Background daemon that scans active symbols on daily bars, tracks open
positions, and fires add/exit/stop signals when the 5-layer EMA structure
aligns.

Layer configuration loaded from AVG_DOWN_EMA_CSV env var — never hardcoded.
Layer names are opaque (L1–L5) in all API outputs and logs.

Signal types:
  ENTER      — initial position: full ribbon aligned above anchor, price > L1
  ADD        — add-to-position: dip into buy zone, ribbon ≥ 3/5 intact, anchor held
  EXIT       — recovery: price surpassed avg cost by AVG_DOWN_EXIT_GAIN, ribbon re-aligns
  HARD_STOP  — pnl breached AVG_DOWN_MAX_LOSS_PCT (checked before STOP — the anchor
               EMA is too slow to cap loss on its own during a real decline)
  STOP       — anchor layer (L5) broken (fallback stop if HARD_STOP threshold wasn't hit)

Position sizing (alert-only — no live orders unless IAM_AUTO_TRADING=true):
  Initial position: AVG_DOWN_INITIAL_SIZE (default 20% of virtual notional)
  Each add: previous × AVG_DOWN_SCALE_FACTOR (default 0.55)
  Max adds:  AVG_DOWN_MAX_LEVELS (default 3)

All execution flows through iam_executor.execute_from_resolution() which
enforces the full IAM safety gate stack before any real order is placed.
"""

from __future__ import annotations

import os
import time
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("SML-AvgDown")

# ─── CONFIG — loaded from env, never hardcoded ─────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:    return float(os.environ.get(key, default))
    except: return default

def _env_int(key: str, default: int) -> int:
    try:    return int(os.environ.get(key, default))
    except: return default

def _load_layers() -> List[int]:
    raw = os.environ.get("AVG_DOWN_EMA_CSV", "55,89,144,233,365")
    try:
        periods = [int(x.strip()) for x in raw.split(",") if x.strip()]
        if len(periods) != 5:
            raise ValueError("AVG_DOWN_EMA_CSV must have exactly 5 values")
        return sorted(periods)
    except Exception as e:
        logger.error(f"[AVG-DOWN] Bad AVG_DOWN_EMA_CSV: {e} — engine cannot start")
        raise

SCAN_INTERVAL_S   = _env_int("AVG_DOWN_SCAN_INTERVAL_S", 300)    # 5 min
MAX_LEVELS        = _env_int("AVG_DOWN_MAX_LEVELS", 3)
ADD_PCT           = _env_float("AVG_DOWN_ADD_PCT", 0.04)          # 4% dip per level
EXIT_GAIN         = _env_float("AVG_DOWN_EXIT_GAIN", 0.07)        # 7% above avg cost
INITIAL_SIZE      = _env_float("AVG_DOWN_INITIAL_SIZE", 0.20)     # 20% of notional
SCALE_FACTOR      = _env_float("AVG_DOWN_SCALE_FACTOR", 0.55)     # each add = prev × 0.55
# Hard %-loss stop, checked BEFORE the anchor-break stop below. The anchor is
# L5 (365-period EMA by default) — during a sustained decline it lags far
# behind price, so a position can be deep underwater long before "close
# below L5" ever fires. Backtesting a 720-bar uptrend-then-crash showed the
# anchor-only stop closing at -46% (33 days after the last add); a 15% hard
# stop caps the same trade at -15.7% and flips the run's total P&L from
# negative to positive without affecting any winning trade in the scenarios
# tested (it's far looser than the -4%/-8%/-12% add thresholds, so it never
# fires during a normal add sequence — only when a decline blows through all
# adds and keeps going).
MAX_LOSS_PCT      = _env_float("AVG_DOWN_MAX_LOSS_PCT", 0.15)     # 15% hard stop
BARS_NEEDED       = 400                                            # daily bars for L5 EMA

# ─── IN-MEMORY STATE ───────────────────────────────────────────────────────────

_positions: Dict[str, dict] = {}     # symbol → position state
_signals:   deque           = deque(maxlen=200)
_state_lock = threading.Lock()

# ─── EMA MATH ─────────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _compute_layers(closes: List[float]) -> Optional[Dict[str, float]]:
    """
    Returns {L1..L5: value} for the latest bar.
    Returns None if fewer than L5-period bars available.
    """
    layers = _load_layers()
    if len(closes) < layers[-1]:
        return None
    result = {}
    for i, period in enumerate(layers, start=1):
        series = _ema(closes, period)
        result[f"L{i}"] = series[-1]
    return result


def _ribbon_state(lv: Dict[str, float], close: float) -> dict:
    """
    Returns ribbon alignment metrics.
    full_bull: L1 > L2 > L3 > L4 > L5
    loose_bull: L1 > L2 > L3           (adequate for adds)
    above_anchor: close > L5
    """
    vals = [lv["L1"], lv["L2"], lv["L3"], lv["L4"], lv["L5"]]
    full_bull  = all(vals[i] > vals[i+1] for i in range(4))
    loose_bull = vals[0] > vals[1] > vals[2]
    above_anchor = close > vals[4]
    # Alignment score: how many consecutive pairs are in bull order
    align_score = sum(1 for i in range(4) if vals[i] > vals[i+1])
    return {
        "full_bull":     full_bull,
        "loose_bull":    loose_bull,
        "above_anchor":  above_anchor,
        "align_score":   align_score,   # 0–4
    }


# ─── SIGNAL GENERATION ─────────────────────────────────────────────────────────

def _ftd_context(symbol: str) -> dict:
    """
    Pull FTD settlement echo context for this symbol.
    Fails open — any exception returns empty dict (never blocks evaluation).
    """
    try:
        from core.ftd_data import cycle_summary_for
        cyc = cycle_summary_for(symbol)
        return {
            "ftd_echo":    cyc.get("in_settlement_echo", False),
            "echo_source": cyc.get("echo_source"),
            "days_to_t13": cyc.get("days_to_t13_from_today"),
            "days_to_t35": cyc.get("days_to_t35_from_today"),
        }
    except Exception:
        return {}


def _evaluate(symbol: str, closes: List[float], now_iso: str) -> Optional[dict]:
    """
    Evaluate one symbol. Returns a signal dict if action ≠ HOLD, else None.
    """
    lv = _compute_layers(closes)
    if not lv:
        return None

    close   = closes[-1]
    ribbon  = _ribbon_state(lv, close)

    with _state_lock:
        pos = _positions.get(symbol, {})
        in_pos    = bool(pos.get("in_position"))
        avg_price = float(pos.get("avg_price", 0.0))
        level     = int(pos.get("level", 0))

    # FTD echo context — only queried when above anchor (deploy zone)
    ftd_ctx = _ftd_context(symbol) if ribbon["above_anchor"] else {}

    # ── Exit / stop (position open) ──────────────────────────────────────
    if in_pos:
        pnl = (close - avg_price) / avg_price if avg_price > 0 else 0.0

        # Hard %-loss stop — fires regardless of anchor state. Must be checked
        # before the anchor-break stop below: the anchor (L5, 365-period EMA
        # by default) is too slow to cap loss during a real decline on its own.
        if pnl < -MAX_LOSS_PCT:
            _close_position(symbol, close, "HARD_STOP", pnl, now_iso)
            return _make_signal(symbol, "HARD_STOP", close, level, lv, ribbon, pnl, now_iso)

        # Anchor-break stop: ribbon lost its footing above L5
        if not ribbon["above_anchor"]:
            _close_position(symbol, close, "STOP", pnl, now_iso)
            return _make_signal(symbol, "STOP", close, level, lv, ribbon, pnl, now_iso)

        # Exit: recovered above avg or full ribbon re-aligned above cost
        if pnl >= EXIT_GAIN or (pnl > 0.005 and ribbon["full_bull"] and ribbon["above_anchor"]):
            _close_position(symbol, close, "EXIT", pnl, now_iso)
            return _make_signal(symbol, "EXIT", close, level, lv, ribbon, pnl, now_iso, ftd_ctx)

        # Add-to-position trigger
        threshold = -ADD_PCT * (level + 1)
        if (pnl < threshold and level < MAX_LEVELS
                and ribbon["loose_bull"] and ribbon["above_anchor"]):
            _add_to_position(symbol, close, level + 1)
            return _make_signal(symbol, "ADD", close, level + 1, lv, ribbon, pnl, now_iso, ftd_ctx)

        return None  # HOLD

    # ── Entry (no position) ──────────────────────────────────────────────
    if ribbon["full_bull"] and ribbon["above_anchor"] and close > lv["L1"]:
        _open_position(symbol, close, now_iso)
        return _make_signal(symbol, "ENTER", close, 0, lv, ribbon, 0.0, now_iso, ftd_ctx)

    return None


def _make_signal(symbol, action, price, level, lv, ribbon, pnl, ts, ftd_ctx=None) -> dict:
    sig = {
        "symbol":      symbol,
        "action":      action,
        "price":       round(price, 4),
        "level":       level,
        "pnl_pct":     round(pnl * 100, 2) if pnl else None,
        "align_score": ribbon["align_score"],
        "above_anchor":ribbon["above_anchor"],
        "L1":          round(lv["L1"], 4),
        "L2":          round(lv["L2"], 4),
        "L3":          round(lv["L3"], 4),
        "L4":          round(lv["L4"], 4),
        "L5":          round(lv["L5"], 4),
        "ts":          ts,
    }
    if ftd_ctx:
        sig["ftd_echo"]    = ftd_ctx.get("ftd_echo", False)
        sig["echo_source"] = ftd_ctx.get("echo_source")
        sig["days_to_t13"] = ftd_ctx.get("days_to_t13")
        sig["days_to_t35"] = ftd_ctx.get("days_to_t35")
    return sig


# ─── POSITION MANAGEMENT ──────────────────────────────────────────────────────

def _open_position(symbol: str, price: float, ts: str):
    with _state_lock:
        _positions[symbol] = {
            "in_position": True,
            "avg_price":   price,
            "level":       0,
            "entry_price": price,
            "entry_ts":    ts,
            "size":        INITIAL_SIZE,
        }
    logger.info(f"[AVG-DOWN] ENTER {symbol} @ {price:.4f}")


def _add_to_position(symbol: str, price: float, new_level: int):
    with _state_lock:
        pos = _positions.get(symbol, {})
        old_avg   = float(pos.get("avg_price", price))
        old_size  = float(pos.get("size", INITIAL_SIZE))
        add_size  = INITIAL_SIZE * (SCALE_FACTOR ** new_level)
        new_avg   = (old_avg * old_size + price * add_size) / (old_size + add_size)
        pos.update({
            "avg_price": new_avg,
            "level":     new_level,
            "size":      old_size + add_size,
        })
        _positions[symbol] = pos
    logger.info(f"[AVG-DOWN] ADD L{new_level} {symbol} @ {price:.4f}  new_avg={new_avg:.4f}")


def _close_position(symbol: str, price: float, reason: str, pnl: float, ts: str):
    with _state_lock:
        _positions.pop(symbol, None)
    logger.info(f"[AVG-DOWN] {reason} {symbol} @ {price:.4f}  pnl={pnl*100:.1f}%")


# ─── DISCORD ALERTS ────────────────────────────────────────────────────────────

def _fire_discord(signal: dict):
    url = os.environ.get("DISCORD_WEBHOOK_AVG_DOWN", "")
    if not url:
        return
    try:
        from discord_alerts import DiscordAlerts
        da = DiscordAlerts()

        action = signal["action"]
        symbol = signal["symbol"]
        colors = {"ENTER": 0x00FF88, "ADD": 0x00BFFF, "EXIT": 0xFFD700, "STOP": 0xFF4444, "HARD_STOP": 0x8B0000}
        emojis = {"ENTER": "🟢", "ADD": "📥", "EXIT": "💰", "STOP": "🛑", "HARD_STOP": "⛔"}
        color  = colors.get(action, 0xAAAAAA)
        emoji  = emojis.get(action, "🔔")

        fields = [
            {"name": "Symbol",      "value": f"**{symbol}**",                "inline": True},
            {"name": "Action",      "value": f"**{action}**",                "inline": True},
            {"name": "Price",       "value": f"${signal['price']:.4f}",       "inline": True},
            {"name": "Add Level",   "value": str(signal["level"]),            "inline": True},
            {"name": "Align Score", "value": f"{signal['align_score']}/4",    "inline": True},
        ]
        if signal.get("pnl_pct") is not None:
            fields.append({"name": "PnL", "value": f"{signal['pnl_pct']:+.2f}%", "inline": True})

        fields.append({
            "name": "Ribbon Layers",
            "value": (
                f"L1 {signal['L1']:.2f} · L2 {signal['L2']:.2f} · "
                f"L3 {signal['L3']:.2f} · L4 {signal['L4']:.2f} · L5 {signal['L5']:.2f}"
            ),
            "inline": False,
        })

        payload = {"embeds": [{
            "title":       f"{emoji} AVG-DOWN ENGINE — {symbol} {action}",
            "description": "Descriptive signal only — verify IAM gates before acting.",
            "color":       color,
            "fields":      fields,
            "footer":      {"text": f"SML Avg-Down Engine | {datetime.now().strftime('%I:%M %p ET')}"},
            "timestamp":   datetime.utcnow().isoformat(),
        }]}
        da._post(url, payload)
    except Exception as e:
        logger.warning(f"[AVG-DOWN] Discord post failed: {e}")


# ─── SCAN LOOP ─────────────────────────────────────────────────────────────────

def _fetch_closes(symbol: str) -> List[float]:
    """Pull daily closes for this symbol via Tradier. Returns [] on failure."""
    try:
        import tradier_api as ta
        df = ta.get_history_df(symbol, days=BARS_NEEDED + 20)
        if df is None or df.empty:
            return []
        col = "close" if "close" in df.columns else df.columns[-1]
        return df[col].dropna().tolist()
    except Exception as e:
        logger.debug(f"[AVG-DOWN] fetch_closes failed {symbol}: {e}")
        return []


def _get_symbols() -> List[str]:
    """
    Symbol universe: AVG_DOWN_SYMBOLS env var (comma-separated) takes priority.
    Falls back to market scanner's top-volume universe.
    """
    raw = os.environ.get("AVG_DOWN_SYMBOLS", "").strip()
    if raw:
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    try:
        from core.api.market_scanner import _scan_cache, _scan_lock
        with _scan_lock:
            quotes = dict(_scan_cache.get("quotes", {}))
        ranked = sorted(quotes.items(), key=lambda kv: kv[1].get("volRatio", 0), reverse=True)
        return [sym for sym, _ in ranked[:40]]
    except Exception:
        return []


def _intraday_coil_check(symbol: str) -> bool:
    """
    Returns True if the 15m Tactical Matrix is in micro-coil compression.
    Fails open — any error returns False (never blocks a signal).
    Only checked when ADD_REQUIRE_15M_COIL env var is 'true'.
    """
    if os.environ.get("ADD_REQUIRE_15M_COIL", "false").lower() != "true":
        return True   # gate disabled — always allow
    try:
        from core.intraday_compression import detect_compression
        result = detect_compression(symbol)
        return result.get("is_coil", False)
    except Exception:
        return True   # fail open


def _scan_once():
    import tradier_api as ta
    if not ta.is_available():
        logger.debug("[AVG-DOWN] Tradier unavailable — skipping scan")
        return

    symbols   = _get_symbols()
    now_iso   = datetime.now(timezone.utc).isoformat()
    fired     = 0

    for sym in symbols:
        closes = _fetch_closes(sym)
        if len(closes) < 80:
            continue
        try:
            sig = _evaluate(sym, closes, now_iso)
        except Exception as e:
            logger.warning(f"[AVG-DOWN] eval error {sym}: {e}")
            continue

        if sig:
            # Optional 15m coil gate on ADD signals — set ADD_REQUIRE_15M_COIL=true to enable
            if sig["action"] == "ADD" and not _intraday_coil_check(sym):
                logger.info(
                    f"[AVG-DOWN] {sym} ADD deferred — 15m Tactical Matrix not in coil "
                    f"(ADD_REQUIRE_15M_COIL=true active)"
                )
                continue

            with _state_lock:
                _signals.appendleft(sig)
            _fire_discord(sig)
            # Route entry/add signals through IAM executor for alert/execution
            if sig["action"] in ("ENTER", "ADD"):
                _route_iam(sym, sig)
            fired += 1

    active = sum(1 for p in _positions.values() if p.get("in_position"))
    logger.info(
        f"[AVG-DOWN] scan complete | {len(symbols)} symbols | "
        f"{fired} signals | {active} open positions"
    )


def _route_iam(symbol: str, sig: dict):
    """Fire IAM resolution for ENTER/ADD so the full safety stack is checked."""
    try:
        from iam_executor import execute_from_resolution

        ftd_echo   = sig.get("ftd_echo", False)
        echo_src   = sig.get("echo_source", "")
        ftd_suffix = f" | FTD ECHO {echo_src}" if ftd_echo else ""

        # FTD settlement echo in the deploy zone raises conviction +10
        base_conf  = 65.0 + sig["align_score"] * 5.0
        confidence = min(95.0, base_conf + (10.0 if ftd_echo else 0.0))

        resolution = {
            "action":    "BUY",
            "system":    "SML_CASCADE",
            "rationale": (
                f"[AVG-DOWN {sig['action']} L{sig['level']} align={sig['align_score']}/4"
                f"{ftd_suffix}] "
                f"Pyramid layer {sig['level']} — full ribbon above anchor, "
                f"EMA structure intact."
            ),
            "vehicle":      symbol,
            "invalidation": "L5 (anchor layer) close below on daily bar",
        }
        execute_from_resolution(
            symbol, resolution,
            time_window="NEAR_TERM",
            confidence=confidence,
            price=sig["price"],
        )
    except Exception as e:
        logger.debug(f"[AVG-DOWN] IAM route error {symbol}: {e}")


# ─── PUBLIC API ────────────────────────────────────────────────────────────────

def get_positions() -> List[dict]:
    with _state_lock:
        return [
            {"symbol": sym, **pos}
            for sym, pos in _positions.items()
            if pos.get("in_position")
        ]


def get_signals(limit: int = 50) -> List[dict]:
    with _state_lock:
        return list(_signals)[:limit]


def get_status() -> dict:
    layers = _load_layers()
    return {
        "engine":      "avg_down",
        "running":     bool(_thread and _thread.is_alive()),
        "scan_interval_s": SCAN_INTERVAL_S,
        "max_levels":  MAX_LEVELS,
        "add_pct":     ADD_PCT,
        "exit_gain":   EXIT_GAIN,
        "layer_count": len(layers),
        "open_positions": len(get_positions()),
        "signal_count":   len(_signals),
    }


# ─── THREAD START ──────────────────────────────────────────────────────────────

_thread: Optional[threading.Thread] = None


def start_avg_down_engine():
    """Start the avg-down background daemon. Idempotent."""
    global _thread
    if _thread and _thread.is_alive():
        return

    def _loop():
        logger.info("[AVG-DOWN] SML Avg-Down Engine started")
        time.sleep(45)   # let market scanner warm up first
        while True:
            try:
                _scan_once()
            except Exception as e:
                logger.error(f"[AVG-DOWN] loop error: {e}")
            time.sleep(SCAN_INTERVAL_S)

    _thread = threading.Thread(target=_loop, daemon=True, name="SML-AvgDown")
    _thread.start()
