"""
/api/convergence/<symbol>   — Full 5-engine convergence read for one symbol
/api/beastmode              — Scan the universe, return all convergence hits
/api/settlement             — Engine 2 clock status (all active ignitions)
/api/settlement/<symbol>    — Engine 2 clock for one symbol
"""

import logging
import os
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.convergence_engine import ConvergenceEngine, scan_beastmode_universe
from core.counsel_agent import generate_ai_counsel
from core.engine2_settlement import get_clock, stamp_ignition, get_all_active
from core.discord_payload import fire_discord

logger = logging.getLogger("SML.Convergence.API")
convergence_bp = Blueprint("convergence", __name__)

# ── Execution config ─────────────────────────────────────────────────────────
_last_execution: dict = {}        # symbol → epoch of last executed trade
_pdt_day_trades: list = []        # epoch timestamps of day trades (5-day window)
_EXECUTION_COOLDOWN  = 300        # 5 min cooldown per symbol between executions
_PDT_BALANCE_LIMIT   = 2100.0     # enforce PDT rule when account balance below this
_PDT_MAX_DAY_TRADES  = 3          # max day trades in 5-day rolling window
_PDT_WINDOW_SECS     = 5 * 86400  # 5 days in seconds
_MIN_GOD_STACKED     = int(os.environ.get("MIN_GOD_STACKED", "5"))  # min SET9 configs stacked to execute (5 or 6)
_BEAST_MAX_SHARES    = int(os.environ.get("BEAST_MAX_SHARES", "5"))
_BEAST_MAX_PRICE     = float(os.environ.get("BEAST_MAX_PRICE", "500.0"))

# ── MASTER ARM SWITCH ────────────────────────────────────────────────────────
# Decouples live DATA (TRADIER_ENV=production) from live EXECUTION.
# Live trades ONLY fire when LIVE_TRADING_ENABLED is explicitly "true".
# Default is OFF (safe): production data feed still works, but no orders place.
# This is the kill switch — set the env var to "false" (or unset) to halt all
# autonomous execution instantly on next deploy, without touching data feeds.
def _live_trading_armed() -> bool:
    return (os.environ.get("LIVE_TRADING_ENABLED", "false").strip().lower() == "true")


def _pdt_check_and_record() -> bool:
    """
    Returns True if trade is allowed under PDT rules.
    Enforces PDT when Tradier balance < $2,100: max 3 day trades per 5 days.
    Always records the trade if allowed.
    """
    import tradier_api as _t
    now = time.time()

    # Prune trades older than 5 days
    cutoff = now - _PDT_WINDOW_SECS
    _pdt_day_trades[:] = [t for t in _pdt_day_trades if t > cutoff]

    # Check account balance
    balance = _t.get_account_balance()
    if balance is None:
        # FAIL-SAFE: if we can't confirm the balance, assume PDT applies.
        # An API hiccup must never widen permissions. Treat as restricted.
        if len(_pdt_day_trades) >= _PDT_MAX_DAY_TRADES:
            logger.warning("[PDT] BLOCKED — balance unknown (API error), enforcing PDT cap as precaution")
            return False
        logger.warning("[PDT] Balance unknown (API error) — treating as PDT-restricted (fail-safe)")
    elif balance < _PDT_BALANCE_LIMIT:
        if len(_pdt_day_trades) >= _PDT_MAX_DAY_TRADES:
            logger.warning(
                f"[PDT] BLOCKED — balance ${balance:.2f} < ${_PDT_BALANCE_LIMIT} "
                f"and {len(_pdt_day_trades)}/{_PDT_MAX_DAY_TRADES} day trades used in 5-day window"
            )
            return False
        logger.info(f"[PDT] Balance ${balance:.2f} < ${_PDT_BALANCE_LIMIT} — PDT active: {len(_pdt_day_trades)+1}/{_PDT_MAX_DAY_TRADES} used")
    else:
        logger.info(f"[PDT] Balance ${balance:.2f} — above PDT threshold, full trading allowed")

    _pdt_day_trades.append(now)
    return True


def _fire_execution(symbol: str, result: dict, dm=None) -> None:
    """
    Fires live trades when GOD MODE confirmed with god_stacked >= MIN_GOD_STACKED (default 5).
    Routes to:
      1. Tradier (cloud, 24/7) — equity market order
      2. Robinhood Windows executor — webhook POST (if ROBINHOOD_EXECUTOR_URL set)
    PDT shield active when Tradier balance < $2,100.
    """
    import tradier_api as _t

    # ── MASTER ARM SWITCH — first gate, before anything else ─────────────────
    # Even with GOD MODE stacked and production data live, NO order places
    # unless live trading is explicitly armed. This is the kill switch.
    if not _live_trading_armed():
        logger.info(
            f"[EXEC] {symbol} signal qualified but LIVE_TRADING_ENABLED is OFF — "
            f"logging only, no order placed. (Set LIVE_TRADING_ENABLED=true to arm.)"
        )
        return

    sml        = result.get("sml_matrix") or {}
    god_count  = sml.get("god_stacked", 0)

    # ── Tiered execution gate: require MIN_GOD_STACKED (default 5 or 6 of 6) ─
    if god_count < _MIN_GOD_STACKED:
        logger.info(f"[EXEC] {symbol} god_stacked={god_count} < {_MIN_GOD_STACKED} — not executing")
        return

    # ── Per-symbol cooldown ──────────────────────────────────────────────────
    now  = time.time()
    last = _last_execution.get(symbol, 0)
    if now - last < _EXECUTION_COOLDOWN:
        logger.info(f"[EXEC] {symbol} cooldown — {int(_EXECUTION_COOLDOWN-(now-last))}s remaining")
        return
    _last_execution[symbol] = now

    # ── PDT shield ──────────────────────────────────────────────────────────
    if not _pdt_check_and_record():
        return

    signal = result.get("signal", "")
    side   = "buy" if "BULL" in signal or signal in ("BEASTMODE", "GOD_MODE", "DUAL_GRID_LOCK") else "sell"

    # ── Live price ───────────────────────────────────────────────────────────
    try:
        q     = _t.get_quote(symbol)
        price = float(q.get("last") or q.get("ask") or 0) if q else 0.0
    except Exception:
        price = 0.0

    if price <= 0:
        logger.warning(f"[EXEC] {symbol} no live price — aborting")
        return

    quantity = max(1, int(_BEAST_MAX_PRICE // price))
    quantity = min(quantity, _BEAST_MAX_SHARES)

    logger.info(
        f"[EXEC] 🚀 GOD MODE FIRE — {side.upper()} {quantity}x {symbol} @ ${price:.2f} "
        f"| SET9:{god_count}/6 | signal:{signal}"
    )

    # ── 1. Tradier cloud execution ───────────────────────────────────────────
    try:
        tradier_result = _t.place_equity_order(symbol, quantity, side)
        logger.info(f"[EXEC] Tradier → {tradier_result.get('status')} order_id={tradier_result.get('order_id','')}")
    except Exception as e:
        logger.error(f"[EXEC] Tradier error: {e}")

    # ── 2. Robinhood Windows executor webhook ────────────────────────────────
    rh_url = os.environ.get("ROBINHOOD_EXECUTOR_URL", "")
    if rh_url:
        try:
            import json, urllib.request as _ul, hmac as _hmac, hashlib as _hl
            secret  = os.environ.get("WEBHOOK_SECRET", "squeezeos-webhook-default-secret")
            payload = json.dumps({
                "ticker":         symbol,
                "action":         side.upper(),
                "mode":           "equity",
                "sml_matrix":     sml,
                "harmonic_score": sml.get("harmonic_score", 0),
            }).encode()
            sig = "sha256=" + _hmac.new(secret.encode(), payload, _hl.sha256).hexdigest()
            req = _ul.Request(rh_url, data=payload,
                              headers={"Content-Type": "application/json",
                                       "X-SqueezeOS-Signature": sig})
            with _ul.urlopen(req, timeout=5) as resp:
                logger.info(f"[EXEC] Robinhood webhook → {resp.status}")
        except Exception as e:
            logger.warning(f"[EXEC] Robinhood webhook failed: {e}")


@convergence_bp.route("/market/scan", methods=["GET"])
def market_scan():
    """Live ticker rotation — reads directly from the state quotes feed (Polygon/Alpaca)."""
    from core.state import state
    with state.lock:
        quotes = dict(state.quotes)
    if not quotes:
        return jsonify({"status": "awaiting_data", "quotes": {},
                        "message": "Live market feed initializing — no data yet"}), 202
    return jsonify({"status": "ok", "quotes": quotes})

_cache: dict = {}
_CACHE_TTL   = 45   # seconds — convergence is expensive (5 engines + sniper)


def _fetch_bars(dm, symbol: str, limit: int = 400, tf: str = "1D"):
    """Fetch live bars from DataManager. Never falls back to fake data."""
    try:
        bars = dm.get_bars(symbol, timeframe=tf, limit=limit) or []
        if not bars and tf == "1D":
            bars = dm.get_bars(symbol, timeframe="1Min", limit=limit) or []
        closes  = [float(b.get("c") or b.get("close",  0)) for b in bars if b.get("c") or b.get("close")]
        volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]
        return closes, volumes, bars
    except Exception as e:
        logger.warning(f"[Convergence] Bar fetch failed {symbol}: {e}")
        return [], [], []


@convergence_bp.route("/convergence/<symbol>", methods=["GET"])
def convergence_signal(symbol):
    symbol  = symbol.upper().strip()
    run_sniper = request.args.get("sniper", "false").lower() == "true"
    tf = request.args.get("tf", "1D").upper()
    
    # 1. Check Cache
    cache_key = f"{symbol}_{tf}"
    cached = _cache.get(cache_key)
    now = time.time()
    if cached and (now - cached["ts"] < _CACHE_TTL):
        return jsonify(cached["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503

    closes, volumes, bars = _fetch_bars(dm, symbol, tf=tf)
    if len(closes) < 11:
        return jsonify({
            "status": "error", "symbol": symbol,
            "message": f"Insufficient data ({len(closes)} bars)",
        }), 422

    engine = ConvergenceEngine()
    result = engine.analyze(symbol, closes, volumes,
                            bars_with_dates=bars, run_sniper=run_sniper)

    # Add AI Counsel string
    result["ai_counsel"] = generate_ai_counsel(result)

    # Fire Discord on any signal above NEUTRAL
    if result.get("signal") not in ("NEUTRAL", "INSUFFICIENT_DATA"):
        sniper_data = result.get("options_sniper") or {}
        trade_type  = sniper_data.get("type", "CALL").lower()
        fire_discord(result, trade_type=trade_type)

    # ── GOD MODE EXECUTION GATE ──────────────────────────────────────────────
    # Only fires live orders when tier=GOD_MODE AND execute_gate=True.
    # Routes to Tradier (cloud, 24/7) + Robinhood webhook (Windows executor).
    sml = result.get("sml_matrix") or {}
    if sml.get("execute_gate") and sml.get("tier") == "GOD_MODE":
        _fire_execution(symbol, result, dm)


    payload = {
        "status": "success",
        "symbol": symbol,
        "result": result
    }
    _cache[cache_key] = {"ts": now, "data": clean_data(payload)}
    return jsonify(clean_data(payload))


@convergence_bp.route("/beastmode", methods=["GET"])
def beastmode_scan():
    """Scan the full universe. Only returns HIGH_CONVERGENCE+ signals."""
    tf = request.args.get("tf", "1D").upper()
    
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    hits = scan_beastmode_universe({"dm": dm}, tf=tf)

    # Fire Discord + execution for every convergence hit
    for hit in hits:
        sniper_data = hit.get("options_sniper") or {}
        fire_discord(hit, trade_type=sniper_data.get("type", "CALL").lower())

        # ── Market-wide execution gate ────────────────────────────────────
        # Executes on GOD_MODE tier with god_stacked >= MIN_GOD_STACKED (default 5)
        # Skips god_stacked ≤ 4 per operator config
        sml = hit.get("sml_matrix") or {}
        if sml.get("execute_gate") and sml.get("tier") == "GOD_MODE":
            sym = hit.get("symbol", "")
            if sym:
                _fire_execution(sym, hit)

    return jsonify(clean_data({
        "status":        "success",
        "universe":      "DYNAMIC",
        "hits":          len(hits),
        "signals":       hits,
        "timestamp":     time.time(),
    }))


@convergence_bp.route("/settlement/stamp/<symbol>", methods=["POST"])
def stamp_symbol(symbol):
    """Manually stamp T+0 for a symbol (for testing / manual override)."""
    symbol = symbol.upper().strip()
    clock  = stamp_ignition(symbol)
    return jsonify(clean_data({"status": "success", "clock": clock}))


@convergence_bp.route("/settlement/clocks", methods=["GET"])
def all_clocks():
    """All active Engine 2 clocks."""
    return jsonify(clean_data({
        "status": "success",
        "clocks": get_all_active(),
        "ts":     time.time(),
    }))


@convergence_bp.route("/exec/status", methods=["GET"])
def exec_status():
    """
    Live-execution safety status. Check this anytime to see if real money
    is armed. GREEN = safe (no autonomous trading), RED = live trades active.
    """
    import tradier_api as _t
    armed = _live_trading_armed()
    tradier_env = (os.environ.get("TRADIER_ENV") or "sandbox").strip().lower()
    rh_url = os.environ.get("ROBINHOOD_EXECUTOR_URL", "")
    try:
        from flask import jsonify
        try:
            from core.api import auto_exec
            pipeline = auto_exec.status()
        except Exception:
            pipeline = {"error": "auto_exec unavailable"}
        return jsonify({
            "execution_mode": os.environ.get("EXECUTION_MODE", "alert"),
            "live_trading_armed": armed,
            "status": "LIVE — real orders WILL place on GOD MODE" if armed else "SAFE — no autonomous orders (logging only)",
            "tradier_env": tradier_env,
            "tradier_data_live": tradier_env == "production",
            "robinhood_executor_connected": bool(rh_url),
            "auto_execution_pipeline": pipeline,
            "safety_rails": {
                "min_god_stacked": _MIN_GOD_STACKED,
                "max_shares": _BEAST_MAX_SHARES,
                "max_price_per_share": _BEAST_MAX_PRICE,
                "cooldown_secs": _EXECUTION_COOLDOWN,
                "pdt_shield_below": _PDT_BALANCE_LIMIT,
            },
            "kill_switch": "Set LIVE_TRADING_ENABLED=false (or unset) and redeploy to halt all execution.",
        })
    except Exception as e:
        return {"error": str(e)}, 500


@convergence_bp.route("/exec/dry-run", methods=["GET"])
def exec_dry_run():
    """
    Runs the full auto-execution analysis on current top candidates but places
    NO orders. Shows exactly what the system WOULD trade right now. Safe anytime.
    """
    from flask import jsonify
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        from core.api import auto_exec
        from core.api.market_scanner import _scan_cache
        quotes = _scan_cache.get("quotes", {}) or {}
        if not quotes:
            return jsonify({"status": "warming_up", "message": "Scanner cache empty — try again in ~30s (or market closed)."})
        sorted_syms = sorted(quotes.keys(), key=lambda s: quotes[s].get("volRatio", 0), reverse=True)
        report = auto_exec.dry_run(quotes, sorted_syms, dm)
        return jsonify(report)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@convergence_bp.route("/exec/test-alert", methods=["GET"])
def exec_test_alert():
    """
    Fires a SAMPLE GOD MODE manual alert to Discord so you can confirm the
    alert pipe works + see the format. Uses realistic placeholder data.
    Trades nothing. Safe anytime.
    """
    from flask import jsonify
    try:
        from core.api.manual_alert import fire_manual_alert
        sample = {
            "symbol": "AMC",
            "signal": "DUAL_GRID_LOCK",
            "price": 3.42,
            "sml_matrix": {
                "tier": "GOD_MODE",
                "execute_gate": True,
                "god_stacked": 6,
                "harmonic_score": 98.7,
                "price": 3.42,
            },
            "options_sniper": {
                "symbol": "AMC",
                "type": "CALL",
                "strike": 3.50,
                "expiration": "2026-06-12",
                "delta": 0.42,
                "gamma": 0.18,
                "theta": -0.03,
                "iv": 0.95,
                "premium": 0.28,
                "bid": 0.26,
                "ask": 0.30,
                "volume": 1240,
                "open_interest": 8800,
                "description": "AMC Jun 12 2026 $3.50 Call",
            },
        }
        ok = fire_manual_alert(sample)
        return jsonify({
            "test": "manual_alert",
            "fired": ok,
            "message": "Sample GOD MODE alert sent to Discord — check your channel." if ok
                       else "Alert NOT sent — no Discord webhook configured (set DISCORD_WEBHOOK_BEAST or DISCORD_WEBHOOK_ALL).",
        })
    except Exception as e:
        return jsonify({"test": "manual_alert", "fired": False, "error": str(e)}), 500
