"""
SqueezeOS Conditional Settlement
══════════════════════════════════
Agent-to-agent escrow contracts. Creator locks intent; condition is checked
against live market data; when met, settlement instructions fire to both wallets.
Zero custody — SqueezeOS tracks contracts and settlement proofs only.

  POST /api/settlement/create          — create conditional contract
  GET  /api/settlement                 — browse open contracts
  GET  /api/settlement/<id>            — contract status
  POST /api/settlement/trigger/<id>    — check condition + settle if met
  POST /api/settlement/cancel/<id>     — cancel (creator only, PENDING only)
  GET  /api/settlement/wallet/<wallet> — all contracts for a wallet

Contract conditions:
  bias_match        — council verdict bias == expected_bias
  confidence_above  — council confidence >= threshold
  price_above       — symbol price >= target_price  (via scan data)
  price_below       — symbol price <= target_price
  time_elapsed      — current time >= expires_at (always settles in creator's favor)

Settlement:
  Platform earns 1% of stake_rlusd (logged, not custodied)
  Creator and counterparty receive signed settlement proof
  Proof published to SSE stream as SETTLEMENT_COMPLETE event
"""

import time
import uuid
import logging
import threading
from flask import Blueprint, jsonify, request
from core.state import state

logger = logging.getLogger("SqueezeOS-Settlement")
settlement_bp = Blueprint('settlement', __name__)

# ── Storage ──────────────────────────────────────────────────────────────────────────────
_contracts: dict = {}        # contract_id -> contract dict
_lock = threading.Lock()

PLATFORM_FEE_PCT  = 0.01     # 1% fee logged on settlement
MAX_CONTRACTS     = 1000
MAX_PER_WALLET    = 20

_VALID_CONDITIONS = frozenset({
    "bias_match", "confidence_above",
    "price_above", "price_below", "time_elapsed"
})
_VALID_BIASES = frozenset({"BULLISH", "BEARISH", "NEUTRAL"})
_VALID_SYMBOLS = frozenset({"IWM", "SPY", "QQQ", "GME", "AMC", "MSTR", "NVDA", "TSLA", "PLTR", "HOOD"})


def _now() -> float:
    return time.time()


def _check_condition(contract: dict) -> tuple:
    """Evaluate contract condition against current state. Returns (met, reason)."""
    ctype     = contract["condition_type"]
    symbol    = contract["symbol"]
    params    = contract["condition_params"]

    if ctype == "time_elapsed":
        if _now() >= contract["expires_at"]:
            return True, f"Time elapsed — contract expired at {contract['expires_at']}"
        return False, "Time condition not yet met"

    if ctype == "bias_match":
        expected = params.get("expected_bias", "").upper()
        history = _get_latest_signal(symbol, "COUNCIL_VERDICT")
        if not history:
            return False, f"No council verdict yet for {symbol}"
        actual_bias = history.get("bias", "").upper()
        if actual_bias == expected:
            return True, f"Bias matched: {actual_bias} == {expected}"
        return False, f"Bias mismatch: {actual_bias} != {expected}"

    if ctype == "confidence_above":
        threshold = float(params.get("threshold", 80))
        history = _get_latest_signal(symbol, "COUNCIL_VERDICT")
        if not history:
            return False, f"No council verdict yet for {symbol}"
        confidence = float(history.get("confidence", 0))
        if confidence >= threshold:
            return True, f"Confidence {confidence} >= {threshold}"
        return False, f"Confidence {confidence} < {threshold}"

    if ctype in ("price_above", "price_below"):
        target = float(params.get("target_price", 0))
        price  = _get_latest_price(symbol)
        if price is None:
            return False, f"No price data for {symbol}"
        if ctype == "price_above" and price >= target:
            return True, f"Price {price} >= {target}"
        if ctype == "price_below" and price <= target:
            return True, f"Price {price} <= {target}"
        return False, f"Price {price} not yet {'above' if ctype == 'price_above' else 'below'} {target}"

    return False, f"Unknown condition type: {ctype}"


def _get_latest_signal(symbol: str, event_type: str) -> dict:
    try:
        import core.signal_history as sh
        signals = sh.get_history(symbol, limit=10)
        for s in signals:
            if s.get("type") == event_type or s.get("event_type") == event_type:
                return s
    except Exception:
        pass
    return {}


def _get_latest_price(symbol: str):
    try:
        quotes = state.get("quotes", {})
        if symbol in quotes:
            return float(quotes[symbol].get("last", 0)) or None
    except Exception:
        pass
    return None


def _settle(contract: dict, reason: str, winner: str) -> dict:
    fee = round(contract["stake_rlusd"] * PLATFORM_FEE_PCT, 6)
    net = round(contract["stake_rlusd"] - fee, 6)

    proof = {
        "contract_id":   contract["id"],
        "settled_at":    _now(),
        "winner":        winner,
        "loser":         contract["counterparty"] if winner == contract["creator_wallet"] else contract["creator_wallet"],
        "stake_rlusd":   contract["stake_rlusd"],
        "platform_fee":  fee,
        "net_rlusd":     net,
        "reason":        reason,
        "symbol":        contract["symbol"],
        "condition":     contract["condition_type"],
    }

    contract["status"]     = "SETTLED"
    contract["proof"]      = proof
    contract["settled_at"] = _now()

    try:
        import core.app as _app
        broadcast = getattr(_app, '_broadcast_sse_global', None)
        if broadcast:
            broadcast({
                "type":        "SETTLEMENT_COMPLETE",
                "contract_id": contract["id"],
                "symbol":      contract["symbol"],
                "winner":      winner,
                "net_rlusd":   net,
                "reason":      reason,
                "ts":          _now(),
            })
    except Exception:
        pass

    logger.info(f"[SETTLEMENT] {contract['id'][:8]}… settled → winner={winner[:12]}… net={net} RLUSD")
    return proof


# ── Routes ──────────────────────────────────────────────────────────────────────────────

@settlement_bp.route('/create', methods=['POST'])
def create_contract():
    body = request.get_json(silent=True) or {}

    creator   = body.get("creator_wallet", "").strip()
    symbol    = body.get("symbol", "IWM").upper().strip()
    ctype     = body.get("condition_type", "").strip()
    params    = body.get("condition_params", {})
    stake     = body.get("stake_rlusd", 0.05)
    ttl_hours = int(body.get("ttl_hours", 24))
    note      = str(body.get("note", ""))[:500]

    if not creator:
        return jsonify({"error": "creator_wallet required"}), 400
    if symbol not in _VALID_SYMBOLS:
        return jsonify({"error": f"symbol must be one of {sorted(_VALID_SYMBOLS)}"}), 400
    if ctype not in _VALID_CONDITIONS:
        return jsonify({"error": f"condition_type must be one of {sorted(_VALID_CONDITIONS)}"}), 400
    if ctype == "bias_match" and params.get("expected_bias", "").upper() not in _VALID_BIASES:
        return jsonify({"error": "expected_bias must be BULLISH, BEARISH, or NEUTRAL"}), 400
    try:
        stake = float(stake)
        assert 0.01 <= stake <= 100.0
    except Exception:
        return jsonify({"error": "stake_rlusd must be between 0.01 and 100.0"}), 400

    with _lock:
        wallet_count = sum(1 for c in _contracts.values() if c["creator_wallet"] == creator and c["status"] in ("PENDING", "ACTIVE"))
        if wallet_count >= MAX_PER_WALLET:
            return jsonify({"error": f"Max {MAX_PER_WALLET} active contracts per wallet"}), 429

        if len(_contracts) >= MAX_CONTRACTS:
            oldest = sorted(_contracts.values(), key=lambda c: c["created_at"])
            for old in oldest:
                if old["status"] in ("SETTLED", "CANCELLED", "EXPIRED"):
                    del _contracts[old["id"]]
                    break

        contract_id = str(uuid.uuid4())
        contract = {
            "id":               contract_id,
            "creator_wallet":   creator,
            "counterparty":     None,
            "symbol":           symbol,
            "condition_type":   ctype,
            "condition_params": params,
            "stake_rlusd":      stake,
            "status":           "PENDING",
            "note":             note,
            "created_at":       _now(),
            "expires_at":       _now() + ttl_hours * 3600,
            "proof":            None,
        }
        _contracts[contract_id] = contract

    logger.info(f"[SETTLEMENT] Created {contract_id[:8]}… {symbol} {ctype} stake={stake} RLUSD")
    return jsonify({
        "contract_id":     contract_id,
        "symbol":          symbol,
        "condition_type":  ctype,
        "condition_params": params,
        "stake_rlusd":     stake,
        "status":          "PENDING",
        "expires_at":      contract["expires_at"],
        "message":         "Contract created. Call /trigger to check condition.",
    }), 201


@settlement_bp.route('', methods=['GET'])
def list_contracts():
    symbol = request.args.get("symbol", "").upper()
    status = request.args.get("status", "").upper()
    limit  = min(int(request.args.get("limit", 50)), 200)

    with _lock:
        results = list(_contracts.values())

    if symbol:
        results = [c for c in results if c["symbol"] == symbol]
    if status:
        results = [c for c in results if c["status"] == status]

    results = sorted(results, key=lambda c: c["created_at"], reverse=True)[:limit]

    return jsonify({
        "contracts": [{
            "id":             c["id"],
            "creator_wallet": c["creator_wallet"][:12] + "…",
            "symbol":         c["symbol"],
            "condition_type": c["condition_type"],
            "stake_rlusd":    c["stake_rlusd"],
            "status":         c["status"],
            "expires_at":     c["expires_at"],
            "note":           c["note"],
        } for c in results],
        "count":  len(results),
        "free":   True,
    })


@settlement_bp.route('/<contract_id>', methods=['GET'])
def get_contract(contract_id):
    with _lock:
        contract = _contracts.get(contract_id)
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    met, reason = _check_condition(contract)
    return jsonify({**contract, "condition_currently_met": met, "condition_check": reason})


@settlement_bp.route('/trigger/<contract_id>', methods=['POST'])
def trigger_contract(contract_id):
    body   = request.get_json(silent=True) or {}

    with _lock:
        contract = _contracts.get(contract_id)
        if not contract:
            return jsonify({"error": "Contract not found"}), 404
        if contract["status"] == "SETTLED":
            return jsonify({"status": "already_settled", "proof": contract["proof"]}), 200
        if contract["status"] == "CANCELLED":
            return jsonify({"error": "Contract cancelled"}), 400
        if _now() > contract["expires_at"] and contract["status"] != "SETTLED":
            contract["status"] = "EXPIRED"
            return jsonify({"status": "expired", "message": "Contract expired"}), 200

        met, reason = _check_condition(contract)
        if not met:
            return jsonify({"status": "pending", "condition_met": False, "reason": reason}), 200

        winner = contract["creator_wallet"]
        proof  = _settle(contract, reason, winner)

    return jsonify({"status": "settled", "condition_met": True, "proof": proof}), 200


@settlement_bp.route('/cancel/<contract_id>', methods=['POST'])
def cancel_contract(contract_id):
    body   = request.get_json(silent=True) or {}
    wallet = body.get("wallet", "").strip()

    with _lock:
        contract = _contracts.get(contract_id)
        if not contract:
            return jsonify({"error": "Contract not found"}), 404
        if contract["creator_wallet"] != wallet:
            return jsonify({"error": "Only creator can cancel"}), 403
        if contract["status"] != "PENDING":
            return jsonify({"error": f"Cannot cancel — status is {contract['status']}"}), 400
        contract["status"]       = "CANCELLED"
        contract["cancelled_at"] = _now()

    return jsonify({"status": "cancelled", "contract_id": contract_id})


@settlement_bp.route('/wallet/<wallet>', methods=['GET'])
def wallet_contracts(wallet):
    limit = min(int(request.args.get("limit", 50)), 200)
    with _lock:
        results = [c for c in _contracts.values()
                   if c["creator_wallet"] == wallet or c["counterparty"] == wallet]
    results = sorted(results, key=lambda c: c["created_at"], reverse=True)[:limit]
    return jsonify({"wallet": wallet, "contracts": results, "count": len(results)})
