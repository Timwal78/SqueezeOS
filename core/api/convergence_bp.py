"""
/api/convergence/<symbol>   — Full 5-engine convergence read for one symbol
/api/beastmode              — Scan the universe, return all convergence hits
/api/settlement             — Engine 2 clock status (all active ignitions)
/api/settlement/<symbol>    — Engine 2 clock for one symbol
"""

import logging
import os
import threading
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.convergence_engine import ConvergenceEngine, scan_beastmode_universe
from core.counsel_agent import generate_ai_counsel
from core.engine2_settlement import get_clock, stamp_ignition, get_all_active
from core.discord_payload import fire_discord

logger = logging.getLogger("SML.Convergence.API")
convergence_bp = Blueprint("convergence", __name__)

# ── Beastmode background cache ────────────────────────────────────────────
# scan_beastmode_universe() is a full-universe convergence scan — expensive
# (~thousands of tickers post Law-2 discovery). Running it synchronously per
# HTTP request caused 30s+ hangs and Render health-check crash loops.
# Instead, a background thread refreshes this cache on an interval and the
# /beastmode route returns it instantly.
_beast_cache = {"hits": [], "ts": 0, "tf": "1D", "progress": {"done": 0, "total": 0}}
_beast_last_good = {"hits": [], "ts": 0}   # last scan that produced ≥1 hit — never wiped
_beast_lock = threading.Lock()
_BEAST_REFRESH_S = int(os.environ.get("BEASTMODE_REFRESH_S", "45"))
_beast_thread_started = False

def _beastmode_refresh_loop():
    logger.info("[BEASTMODE] Background refresh thread active (every %ss)", _BEAST_REFRESH_S)
    time.sleep(8)  # let services init
    while True:
        try:
            dm = get_service("dm")
            if dm:
                tf = _beast_cache.get("tf", "1D")

                def _on_progress(hits_so_far, done, total, _tf=tf):
                    with _beast_lock:
                        _beast_cache["hits"] = hits_so_far
                        _beast_cache["ts"] = time.time()
                        _beast_cache["progress"] = {"done": done, "total": total}

                hits = scan_beastmode_universe({"dm": dm}, tf=tf, on_progress=_on_progress)

                for hit in hits:
                    sniper_data = hit.get("options_sniper") or {}
                    try:
                        fire_discord(hit, trade_type=sniper_data.get("type", "CALL").lower())
                    except Exception as _de:
                        logger.warning(f"[BEASTMODE] discord fire failed: {_de}")

                    sml = hit.get("sml_matrix") or {}
                    bull_gate = sml.get("execute_gate") and sml.get("tier") == "GOD_MODE"
                    bear_gate = sml.get("bear_execute_gate") and sml.get("bear_tier") == "GOD_MODE"
                    if bull_gate or bear_gate:
                        sym = hit.get("symbol", "")
                        if sym:
                            try:
                                _fire_execution(sym, hit, dm)
                            except Exception as _ee:
                                logger.warning(f"[BEASTMODE] exec failed for {sym}: {_ee}")

                with _beast_lock:
                    _beast_cache["hits"] = hits
                    _beast_cache["ts"] = time.time()
                    if hits:
                        _beast_last_good["hits"] = hits
                        _beast_last_good["ts"] = time.time()
                logger.info(f"[BEASTMODE] cache refreshed — {len(hits)} hits")
        except Exception as e:
            logger.error(f"[BEASTMODE] refresh error: {e}")
        time.sleep(_BEAST_REFRESH_S)

def start_beastmode_scanner():
    global _beast_thread_started
    if _beast_thread_started:
        return
    _beast_thread_started = True
    threading.Thread(target=_beastmode_refresh_loop, daemon=True, name="SML-Beastmode-Scanner").start()


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

    sml         = result.get("sml_matrix") or {}
    god_count   = sml.get("god_stacked", 0)
    bear_count  = sml.get("bear_god_stacked", 0)

    # ── Bidirectional gate — bull (open long) vs bear (protect gains + puts) ─
    # core/harmonic_matrix_engine.py now emits a mirrored bearish ladder
    # (bear_execute_gate/bear_tier/bear_god_stacked) alongside the original
    # bull-only fields. Bear takes priority: if we're holding a long and a
    # GOD-tier bearish reversal fires, closing to protect gains matters more
    # than a fresh entry firing the same tick.
    bear_fired = sml.get("bear_execute_gate") and sml.get("bear_tier") == "GOD_MODE" and bear_count >= _MIN_GOD_STACKED
    bull_fired = sml.get("execute_gate") and sml.get("tier") == "GOD_MODE" and god_count >= _MIN_GOD_STACKED

    if not bear_fired and not bull_fired:
        logger.info(
            f"[EXEC] {symbol} god_stacked={god_count} bear_god_stacked={bear_count} "
            f"< {_MIN_GOD_STACKED} — not executing"
        )
        return

    side = "sell" if bear_fired else "buy"

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

    # ── Live price ───────────────────────────────────────────────────────────
    try:
        q     = _t.get_quote(symbol)
        price = float(q.get("last") or q.get("ask") or 0) if q else 0.0
    except Exception:
        price = 0.0

    if price <= 0:
        logger.warning(f"[EXEC] {symbol} no live price — aborting")
        return

    if bear_fired:
        # ── Bearish GOD signal: protect any existing long first, then treat
        # the reversal as a fresh PUT-buying opportunity (never a naked short —
        # this bot only ever holds long equity or long option positions).
        try:
            position = _t.get_position(symbol)
        except Exception as e:
            logger.error(f"[EXEC] {symbol} position lookup failed: {e}")
            position = None

        if position and position.get("quantity", 0) > 0:
            close_qty = int(position["quantity"])
            logger.info(
                f"[EXEC] 🔻 GOD MODE BEAR — closing existing long to protect gains: "
                f"SELL {close_qty}x {symbol} @ ${price:.2f} | SET9(bear):{bear_count}/6"
            )
            try:
                tradier_result = _t.place_equity_order(symbol, close_qty, "sell")
                logger.info(f"[EXEC] Tradier close → {tradier_result.get('status')} order_id={tradier_result.get('order_id','')}")
            except Exception as e:
                logger.error(f"[EXEC] Tradier close error: {e}")
        else:
            logger.info(f"[EXEC] {symbol} GOD MODE BEAR fired but no existing long to close — skipping close leg")

        # ── Opportunistic PUT buy on the bearish signal ──────────────────────
        try:
            from core.convergence_engine import scan_options
            contract = scan_options(symbol, trade_type="put", current_price=price)
        except Exception as e:
            logger.error(f"[EXEC] {symbol} PUT scan error: {e}")
            contract = {"error": str(e)}

        if contract.get("error"):
            logger.warning(f"[EXEC] {symbol} PUT scan failed — {contract['error']}")
        else:
            option_symbol = contract.get("description") or contract.get("symbol")
            ask = contract.get("ask") or contract.get("premium") or 0
            try:
                ask = float(ask or 0)
            except (TypeError, ValueError):
                ask = 0.0
            if option_symbol and ask > 0:
                logger.info(
                    f"[EXEC] 🚀 GOD MODE BEAR — buying PUT {option_symbol} "
                    f"strike={contract.get('strike')} delta={contract.get('delta')} @ ${ask:.2f}"
                )
                try:
                    opt_result = _t.place_option_order(option_symbol, 1, "buy_to_open")
                    logger.info(f"[EXEC] Tradier PUT → {opt_result.get('status')} order_id={opt_result.get('order_id','')}")
                except Exception as e:
                    logger.error(f"[EXEC] Tradier PUT error: {e}")
            else:
                logger.warning(f"[EXEC] {symbol} PUT contract missing symbol/ask — skipping")

        _fire_robinhood_webhook(symbol, "SELL", sml, {"mode": "protect_and_put"})
        return

    # ── bull_fired: open/add long equity position ────────────────────────────
    quantity = max(1, int(_BEAST_MAX_PRICE // price))
    quantity = min(quantity, _BEAST_MAX_SHARES)

    logger.info(
        f"[EXEC] 🚀 GOD MODE FIRE — {side.upper()} {quantity}x {symbol} @ ${price:.2f} "
        f"| SET9:{god_count}/6 | signal:{result.get('signal', '')}"
    )

    # ── 1. Tradier cloud execution ───────────────────────────────────────────
    try:
        tradier_result = _t.place_equity_order(symbol, quantity, side)
        logger.info(f"[EXEC] Tradier → {tradier_result.get('status')} order_id={tradier_result.get('order_id','')}")
    except Exception as e:
        logger.error(f"[EXEC] Tradier error: {e}")

    # ── 2. Robinhood Windows executor webhook ────────────────────────────────
    _fire_robinhood_webhook(symbol, side.upper(), sml, {"mode": "equity"})


def _fire_robinhood_webhook(symbol: str, action: str, sml: dict, extra: dict) -> None:
    """POST the trade intent to the Windows Robinhood executor, if configured."""
    rh_url = os.environ.get("ROBINHOOD_EXECUTOR_URL", "")
    if not rh_url:
        return
    try:
        import json, urllib.request as _ul, hmac as _hmac, hashlib as _hl
        secret  = os.environ.get("WEBHOOK_SECRET", "squeezeos-webhook-default-secret")
        payload = json.dumps({
            "ticker":         symbol,
            "action":         action,
            "sml_matrix":     sml,
            "harmonic_score": sml.get("harmonic_score", 0),
            **extra,
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
    bull_gate = sml.get("execute_gate") and sml.get("tier") == "GOD_MODE"
    bear_gate = sml.get("bear_execute_gate") and sml.get("bear_tier") == "GOD_MODE"
    if bull_gate or bear_gate:
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
    """Return cached full-universe convergence hits (refreshed by background thread)."""
    tf = request.args.get("tf", "1D").upper()

    with _beast_lock:
        _beast_cache["tf"] = tf
        hits = list(_beast_cache["hits"])
        ts = _beast_cache["ts"]
        progress = dict(_beast_cache.get("progress", {}))
        stale = False
        if not hits and _beast_last_good["hits"]:
            hits = list(_beast_last_good["hits"])
            ts = _beast_last_good["ts"]
            stale = True

    return jsonify(clean_data({
        "status":       "success",
        "hits":         len(hits),
        "signals":      hits,
        "universe":     "dynamic",
        "scan_progress": progress,
        "cache_age_s":  round(time.time() - ts, 1) if ts else None,
        "stale":        stale,
        "timestamp":    time.time(),
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
        import threading as _th
        webhook_set = bool(os.environ.get("DISCORD_WEBHOOK_MANUAL") or os.environ.get("DISCORD_WEBHOOK_BEAST") or os.environ.get("DISCORD_WEBHOOK_ALL"))
        # fire on a background thread so the HTTP response returns instantly
        _th.Thread(target=lambda: fire_manual_alert(sample), daemon=True, name="test-alert").start()
        return jsonify({
            "test": "manual_alert",
            "dispatched": True,
            "webhook_configured": webhook_set,
            "message": ("Alert dispatched to Discord — check your channel in a few seconds." if webhook_set
                        else "No Discord webhook configured. Set DISCORD_WEBHOOK_BEAST (or _ALL) on Render, then retry."),
        })
    except Exception as e:
        return jsonify({"test": "manual_alert", "fired": False, "error": str(e)}), 500
