"""
IAM — Inevitable Action Model API
====================================
Markets move not by belief, but by necessity.
IAM trades the necessity.

Endpoints:
  GET  /api/iam/<symbol>         — Full IAM resolution (PAID 0.05 RLUSD): obligation committee
                                   + Truth Layer + mandatory action. Internal AMM parameters redacted.
  GET  /api/iam/truth/<symbol>   — Truth Layer only: neutral obligation state, no action (FREE)
  POST /api/iam/stress-test      — Multi-symbol system stress survey (FREE, up to 5 symbols)

Proprietary boundary:
  _redact_obligation() strips raw_stress and detail from every analyst block
  before serialization. The AMM invariant curve and internal thresholds are
  never exposed to callers — only the output signals (pressure, direction, label).
"""

import sys
import os
import time
import logging
import threading
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
import core.signal_history as signal_history

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
# SML fix: was gated by x402_guard alone (Coinbase/USDC only) — the
# iam_resolve MCP tool description (mcp_bp.py:678) explicitly tells agents to
# pay via RLUSD/XRPL, which silently never worked here. dual_payment accepts
# both; the endpoint_id below matches mcp_bp.py:869 exactly since this route
# has a path param (request.path can't be a static ENDPOINTS dict key).
from proof402_integration import dual_payment
from discord_alerts import DiscordAlerts

IAM_ENDPOINT_ID = "a7f3d2b1-9e4c-4a8f-b5c6-d7e8f9a0b1c2"  # 0.05 RLUSD — matches mcp_bp.py:869

logger = logging.getLogger("IAM-BP")
iam_bp = Blueprint("iam", __name__)

_IAM_CACHE: dict = {}
_IAM_TTL = 45

_discord = DiscordAlerts()
_IAM_DISCORD_COOLDOWN: dict = {}
_IAM_DISCORD_COOLDOWN_SEC = 300  # 5-minute per-symbol cooldown

_ACTION_COLORS = {
    "BUY":  0x00FF88,
    "SELL": 0xFF4444,
    "HOLD": 0xFFAA00,
}
_URGENT_WINDOWS = {"IMMEDIATE", "NEAR_TERM"}


def _fire_iam_discord(sym: str, result: dict):
    """Post IAM resolution to Discord beast channel — fire-and-forget from daemon thread."""
    try:
        now = time.time()
        last = _IAM_DISCORD_COOLDOWN.get(sym, 0)
        if (now - last) < _IAM_DISCORD_COOLDOWN_SEC:
            return
        _IAM_DISCORD_COOLDOWN[sym] = now

        resolution = result.get("resolution", {})
        truth      = result.get("truth_layer", {})
        action     = resolution.get("action", "HOLD")
        window     = truth.get("time_window", "DORMANT")
        stress     = truth.get("total_system_stress", 0.0)
        confidence = resolution.get("resolution_confidence", 0.0)
        rationale  = resolution.get("rationale", "")
        vehicle    = resolution.get("vehicle", "")
        dominant   = truth.get("dominant_obligation", "")

        color = _ACTION_COLORS.get(action, 0xAAAAAA)

        payload = {
            "embeds": [{
                "title": f"⚡ IAM OBLIGATION RESOLVED — {sym}",
                "description": (
                    f"**The market is FORCED to act.**\n"
                    f"> {rationale}"
                ),
                "color": color,
                "fields": [
                    {"name": "Action",             "value": f"**{action}**",               "inline": True},
                    {"name": "Time Window",         "value": window,                        "inline": True},
                    {"name": "System Stress",       "value": f"{stress:.1f}%",              "inline": True},
                    {"name": "Dominant Obligation", "value": dominant or "—",               "inline": True},
                    {"name": "Vehicle",             "value": vehicle or "—",                "inline": True},
                    {"name": "Resolution Confidence", "value": f"{confidence:.0f}%",        "inline": True},
                ],
                "footer": {
                    "text": (
                        f"IAM v1 | Obligation Committee + Truth Layer + ARO | "
                        f"SqueezeOS — squeezeos-api.onrender.com"
                    )
                },
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }]
        }

        url = _discord.webhook_beast or _discord.webhook_all
        if url:
            _discord._post(url, payload)
    except Exception as e:
        logger.warning(f"[IAM-DISCORD] Alert failed for {sym}: {e}")


def _get_iam_engine():
    from iam_engine import IAMEngine
    services = {
        "dm":            get_service("dm"),
        "whale_stalker": get_service("whale_stalker"),
    }
    return IAMEngine(services)


def _redact_obligation(block: dict) -> dict:
    """Strip AMM curve inputs and calculation detail from analyst output at API boundary."""
    return {k: v for k, v in block.items() if k not in ("raw_stress", "detail")}


@iam_bp.route("/<symbol>", methods=["GET"])
@dual_payment(
    price_usdc="0.05",
    description=(
        "IAM Full Resolution — mandatory action the market is forced to take. "
        "Obligation committee (5 independent analysts) + Truth Layer + Action Resolution Oracle. "
        "Returns: action BUY/SELL/HOLD, rationale, vehicle, invalidation, review trigger, "
        "per-analyst obligation pressure (0-100%), and total system stress. "
        "Internal AMM parameters redacted."
    ),
    rlusd_endpoint_id=IAM_ENDPOINT_ID,
)
def iam_resolve(symbol):
    """
    Full IAM resolution — PAID endpoint (0.05 RLUSD).

    Returns:
      - truth_layer: neutral obligation pressure vector (no direction)
      - obligation_committee: per-analyst pressure, direction, label (internals redacted)
      - resolution: mandatory action + rationale + vehicle + invalidation + review trigger
    """
    sym = symbol.upper().strip()
    now = time.time()

    cached = _IAM_CACHE.get(f"resolve_{sym}")
    if cached and (now - cached["ts"]) < _IAM_TTL:
        return jsonify({"status": "success", "cached": True, **cached["data"]})

    try:
        engine = _get_iam_engine()
        result = engine.resolve(sym)
    except Exception as e:
        logger.error(f"[IAM-BP] Resolve error for {sym}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    if "error" in result:
        return jsonify({"status": "error", **result}), 503

    # Redact proprietary internals at API boundary — only signals pass through
    redacted_committee = {
        name: _redact_obligation(block)
        for name, block in result.get("obligation_committee", {}).items()
    }

    try:
        signal_history.record(sym, "IAM_RESOLUTION", {
            "action":     result["resolution"]["action"],
            "stress":     result["truth_layer"]["total_system_stress"],
            "window":     result["truth_layer"]["time_window"],
            "confidence": result["resolution"]["resolution_confidence"],
        })
    except Exception:
        pass

    # Fire Discord alert + auto-execution for actionable resolutions
    try:
        action     = result["resolution"]["action"]
        window     = result["truth_layer"]["time_window"]
        confidence = result["resolution"]["resolution_confidence"]
        price      = float(result.get("price") or 0.0)

        if action in ("BUY", "SELL") and window in _URGENT_WINDOWS:
            # Discord beast-channel alert
            threading.Thread(
                target=_fire_iam_discord,
                args=(sym, result),
                daemon=True,
                name=f"iam-discord-{sym}",
            ).start()

            # Broker execution (Tradier + Robinhood alert) — gated by IAM_AUTO_TRADING
            from iam_executor import execute_async
            execute_async(sym, result["resolution"], window, confidence, price)
    except Exception:
        pass

    response = clean_data({
        "status":  "success",
        "cached":  False,
        "iam": {
            **{k: v for k, v in result.items() if k != "obligation_committee"},
            "obligation_committee": redacted_committee,
        },
    })

    _IAM_CACHE[f"resolve_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/truth/<symbol>", methods=["GET"])
def iam_truth(symbol):
    """
    Truth Layer only — FREE endpoint.

    Neutral obligation state: no action resolution, no internal parameters.

    Returns the canonical Truth Layer output from the IAM specification:
      NEXT REQUIRED ACTION:
      • Volatility Release: 0-100%
      • Liquidity Refill:   0-100%
      • Dealer Hedge:       0-100%
      • Mean Reversion Pull: 0-100%
      • Structural Pressure: 0-100%
      • Directional Bias:   NONE  ← always NONE at this stage
      • Time Window:        DORMANT / DEVELOPING / NEAR_TERM / IMMEDIATE
    """
    sym = symbol.upper().strip()
    now = time.time()

    cached = _IAM_CACHE.get(f"truth_{sym}")
    if cached and (now - cached["ts"]) < _IAM_TTL:
        return jsonify({"status": "success", "cached": True, **cached["data"]})

    try:
        engine = _get_iam_engine()
        result = engine.truth_only(sym)
    except Exception as e:
        logger.error(f"[IAM-BP] Truth error for {sym}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    response = clean_data({
        "status":    "success",
        "cached":    False,
        "iam_truth": result,
        "upgrade": {
            "full_resolution": f"/api/iam/{sym}",
            "price_rlusd":     "0.05",
            "includes":        [
                "mandatory action (BUY/SELL/HOLD)",
                "obligation committee breakdown",
                "rationale",
                "vehicle",
                "invalidation condition",
                "review trigger",
                "resolution confidence",
            ],
            "gateway": "https://four02proof.onrender.com",
        },
    })
    _IAM_CACHE[f"truth_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/autopilot/status", methods=["GET"])
def iam_autopilot_status():
    """
    IAM Autopilot status — FREE endpoint.

    Returns the current state of the IAM auto-execution layer:
    arm switch, execution mode, daily counters, safety gate state.
    """
    try:
        from iam_executor import status as exec_status
        s = exec_status()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify(clean_data({
        "status":    "success",
        "autopilot": s,
        "brokers": {
            "tradier":    "POST /accounts/{id}/orders — equity + options",
            "robinhood":  "tools/robinhood_executor_sml.py — Windows polling service",
        },
        "env_vars": {
            "IAM_AUTO_TRADING":         "false (master arm switch)",
            "IAM_EXECUTION_MODE":       "alert | tradier | both",
            "IAM_INSTRUMENT":           "equity | options | auto",
            "IAM_PAPER_MODE":           "true (default safe)",
            "IAM_MIN_CONFIDENCE":       "70 (minimum % to execute)",
            "IAM_MAX_ORDERS_PER_DAY":   "5",
            "IAM_MAX_ORDER_USD":        "500",
            "IAM_DAILY_LOSS_LIMIT":     "300",
        },
    }))


@iam_bp.route("/autopilot/dry-run/<symbol>", methods=["GET"])
def iam_autopilot_dry_run(symbol):
    """
    IAM Autopilot dry-run — FREE endpoint.

    Resolves the current obligation state and shows what the autopilot
    WOULD do without placing any orders or requiring payment.
    """
    sym = symbol.upper().strip()
    try:
        from iam_executor import status as exec_status, _gate_check, REQUIRED_WINDOWS
        engine = _get_iam_engine()
        truth  = engine.truth_only(sym)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    nra      = truth.get("next_required_action", {})
    window   = nra.get("time_window", "DORMANT")
    stress   = nra.get("total_system_stress", 0.0)

    # Simulate what resolution would look like (no payment, use truth layer only)
    would_execute = window in REQUIRED_WINDOWS and stress >= 55
    gate_reason   = None
    if would_execute:
        gate_reason = _gate_check(sym, {}, window, 75.0)  # test gates with hypothetical 75% confidence

    return jsonify(clean_data({
        "status":          "success",
        "symbol":          sym,
        "truth_layer":     truth,
        "autopilot_preview": {
            "would_trigger":   would_execute,
            "blocked_by":      gate_reason,
            "time_window":     window,
            "total_stress":    stress,
            "note": (
                "This uses Truth Layer only. Full autopilot uses paid resolution "
                "(resolution_confidence must be ≥ IAM_MIN_CONFIDENCE)."
                if would_execute else
                f"Window={window} not in {list(REQUIRED_WINDOWS)} or stress too low — autopilot would not trigger."
            ),
        },
        "exec_status": exec_status(),
    }))


@iam_bp.route("/stress-test", methods=["POST"])
def iam_stress_test():
    """
    Multi-symbol system stress survey — FREE endpoint.

    POST body: {"symbols": ["IWM", "SPY", "GME"]}  (max 5)
    Returns obligation stress ranked by total system stress descending.
    """
    body    = request.get_json(silent=True) or {}
    symbols = body.get("symbols", [])

    if not symbols or not isinstance(symbols, list):
        return jsonify({"status": "error", "message": "symbols array required"}), 400

    symbols = [s.upper().strip() for s in symbols[:5]]

    engine  = _get_iam_engine()
    results = []

    for sym in symbols:
        try:
            r = engine.truth_only(sym)
            results.append({
                "symbol":               sym,
                "total_system_stress":  r["next_required_action"]["total_system_stress"],
                "time_window":          r["next_required_action"]["time_window"],
                "volatility_release":   r["next_required_action"]["volatility_release"],
                "liquidity_refill":     r["next_required_action"]["liquidity_refill"],
                "dealer_hedge":         r["next_required_action"]["dealer_hedge"],
                "mean_reversion_pull":  r["next_required_action"]["mean_reversion_pull"],
                "structural_pressure":  r["next_required_action"]["structural_pressure"],
                "data_quality":         r["next_required_action"]["data_quality"],
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    results.sort(key=lambda x: x.get("total_system_stress", 0), reverse=True)

    return jsonify(clean_data({
        "status":    "success",
        "symbols":   results,
        "ranked_by": "total_system_stress",
        "timestamp": time.time(),
        "upgrade": {
            "full_resolution": "/api/iam/<symbol>",
            "price_rlusd":     "0.05",
            "gateway":         "https://four02proof.onrender.com",
        },
    }))
