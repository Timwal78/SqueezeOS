"""
SqueezeOS Signal Futures Market
══════════════════════════════════
Prediction market layered on top of SqueezeOS council verdicts.
Agents and humans stake RLUSD on what the NEXT council verdict will be.
When the real verdict publishes → auto-settle. Winner takes pot minus 5%.
Zero custody. World's first AI-signal prediction market.

  POST /api/futures/create             — open a futures position (predict + stake)
  POST /api/futures/take/<id>          — take the opposite side
  GET  /api/futures                    — browse open futures
  GET  /api/futures/<id>               — specific future detail
  POST /api/futures/settle/<id>        — force-settle against latest verdict
  GET  /api/futures/leaderboard        — top predictors by win rate
  GET  /api/futures/wallet/<wallet>    — wallet's full futures history

Flow:
  1. Creator predicts "IWM BULLISH at 09:35 session" → stakes 0.05 RLUSD
  2. Taker bets opposite (BEARISH/NEUTRAL) → stakes same amount
  3. SqueezeOS publishes COUNCIL_VERDICT for IWM
  4. Auto-settle: matching party wins (0.095 RLUSD), platform keeps 5% (0.005 RLUSD)
  5. Settlement proof published to SSE stream

Platform fee: 5% of total pot on settlement
"""

import time
import uuid
import logging
import threading
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-Futures")
futures_bp = Blueprint('futures', __name__)

# ── Storage ──────────────────────────────────────────────────────────────────────────────
_futures:       dict = {}       # future_id -> future dict
_leaderboard:   dict = {}       # wallet -> { wins, losses, total_staked, total_earned }
_lock = threading.Lock()

PLATFORM_FEE_PCT = 0.05        # 5% of total pot
MAX_FUTURES      = 2000
MAX_PER_WALLET   = 30

_VALID_BIASES   = frozenset({"BULLISH", "BEARISH", "NEUTRAL"})
_VALID_SYMBOLS  = frozenset({"IWM", "SPY", "QQQ", "GME", "AMC", "MSTR", "NVDA", "TSLA", "PLTR", "HOOD"})
_VALID_SESSIONS = frozenset({"PRE_MARKET", "OPEN", "MIDDAY", "POWER_HOUR", "CLOSE", "ANY"})


def _now() -> float:
    return time.time()


def _lb(wallet: str) -> dict:
    if wallet not in _leaderboard:
        _leaderboard[wallet] = {
            "wallet": wallet,
            "wins": 0, "losses": 0,
            "total_staked": 0.0,
            "total_earned": 0.0,
            "win_rate": 0.0,
        }
    return _leaderboard[wallet]


def _settle_future(future: dict, actual_bias: str, verdict_data: dict) -> dict:
    predicted = future["predicted_bias"]
    creator   = future["creator_wallet"]
    taker     = future["taker_wallet"]
    stake     = future["stake_rlusd"]
    pot       = stake * 2
    fee       = round(pot * PLATFORM_FEE_PCT, 6)
    net       = round(pot - fee, 6)

    winner = creator if actual_bias == predicted else taker
    loser  = taker   if actual_bias == predicted else creator

    proof = {
        "future_id":      future["id"],
        "settled_at":     _now(),
        "symbol":         future["symbol"],
        "predicted_bias": predicted,
        "actual_bias":    actual_bias,
        "creator":        creator,
        "taker":          taker,
        "winner":         winner,
        "loser":          loser,
        "stake_each":     stake,
        "pot":            pot,
        "platform_fee":   fee,
        "net_rlusd":      net,
        "verdict_data":   verdict_data,
    }

    future["status"]     = "SETTLED"
    future["proof"]      = proof
    future["settled_at"] = _now()

    for w, won in [(winner, True), (loser, False)]:
        if not w:
            continue
        lb = _lb(w)
        lb["total_staked"] = round(lb["total_staked"] + stake, 6)
        if won:
            lb["wins"]         += 1
            lb["total_earned"] = round(lb["total_earned"] + net, 6)
        else:
            lb["losses"] += 1
        total = lb["wins"] + lb["losses"]
        lb["win_rate"] = round(lb["wins"] / total, 3) if total else 0.0

    try:
        import core.app as _app
        broadcast = getattr(_app, '_broadcast_sse_global', None)
        if broadcast:
            broadcast({
                "type":      "FUTURES_SETTLED",
                "future_id": future["id"],
                "symbol":    future["symbol"],
                "winner":    winner,
                "net_rlusd": net,
                "actual_bias":    actual_bias,
                "predicted_bias": predicted,
                "ts":        _now(),
            })
    except Exception:
        pass

    logger.info(f"[FUTURES] {future['id'][:8]}… settled → {actual_bias} | winner={winner[:12]}… net={net} RLUSD")
    return proof


def auto_settle_for_symbol(symbol: str, actual_bias: str, confidence: int, verdict_data: dict):
    """Called by signal_history.record on every COUNCIL_VERDICT."""
    settled = []
    with _lock:
        for f in list(_futures.values()):
            if (f["symbol"] == symbol
                    and f["status"] == "ACTIVE"
                    and f["taker_wallet"]):
                proof = _settle_future(f, actual_bias, verdict_data)
                settled.append(proof)
    if settled:
        logger.info(f"[FUTURES] Auto-settled {len(settled)} futures for {symbol} → {actual_bias}")
    return settled


# ── Routes ──────────────────────────────────────────────────────────────────────────────

@futures_bp.route('/create', methods=['POST'])
def create_future():
    body = request.get_json(silent=True) or {}

    creator   = body.get("creator_wallet", "").strip()
    symbol    = body.get("symbol", "IWM").upper().strip()
    bias      = body.get("predicted_bias", "").upper().strip()
    session   = body.get("session", "ANY").upper().strip()
    stake     = body.get("stake_rlusd", 0.05)
    ttl_hours = int(body.get("ttl_hours", 8))
    note      = str(body.get("note", ""))[:300]

    if not creator:
        return jsonify({"error": "creator_wallet required"}), 400
    if symbol not in _VALID_SYMBOLS:
        return jsonify({"error": f"symbol must be one of {sorted(_VALID_SYMBOLS)}"}), 400
    if bias not in _VALID_BIASES:
        return jsonify({"error": "predicted_bias must be BULLISH, BEARISH, or NEUTRAL"}), 400
    if session not in _VALID_SESSIONS:
        return jsonify({"error": f"session must be one of {sorted(_VALID_SESSIONS)}"}), 400
    try:
        stake = round(float(stake), 6)
        assert 0.01 <= stake <= 50.0
    except Exception:
        return jsonify({"error": "stake_rlusd must be between 0.01 and 50.0"}), 400

    with _lock:
        active = sum(1 for f in _futures.values()
                     if f["creator_wallet"] == creator and f["status"] in ("OPEN", "ACTIVE"))
        if active >= MAX_PER_WALLET:
            return jsonify({"error": f"Max {MAX_PER_WALLET} active futures per wallet"}), 429

        if len(_futures) >= MAX_FUTURES:
            oldest = sorted(_futures.values(), key=lambda f: f["created_at"])
            for old in oldest:
                if old["status"] in ("SETTLED", "EXPIRED", "CANCELLED"):
                    del _futures[old["id"]]
                    break

        future_id = str(uuid.uuid4())
        future = {
            "id":              future_id,
            "creator_wallet":  creator,
            "taker_wallet":    None,
            "symbol":          symbol,
            "predicted_bias":  bias,
            "session":         session,
            "stake_rlusd":     stake,
            "status":          "OPEN",
            "note":            note,
            "created_at":      _now(),
            "expires_at":      _now() + ttl_hours * 3600,
            "settled_at":      None,
            "proof":           None,
        }
        _futures[future_id] = future
        _lb(creator)["total_staked"] = round(_lb(creator)["total_staked"] + stake, 6)

    logger.info(f"[FUTURES] Created {future_id[:8]}… {symbol} {bias} stake={stake} RLUSD")
    return jsonify({
        "future_id":      future_id,
        "symbol":         symbol,
        "predicted_bias": bias,
        "session":        session,
        "stake_rlusd":    stake,
        "status":         "OPEN",
        "expires_at":     future["expires_at"],
        "message":        f"Future open. Taker stakes {stake} RLUSD on opposite side. Settles on next {symbol} council verdict.",
    }), 201


@futures_bp.route('/take/<future_id>', methods=['POST'])
def take_future(future_id):
    body  = request.get_json(silent=True) or {}
    taker = body.get("taker_wallet", "").strip()

    if not taker:
        return jsonify({"error": "taker_wallet required"}), 400

    with _lock:
        future = _futures.get(future_id)
        if not future:
            return jsonify({"error": "Future not found"}), 404
        if future["status"] != "OPEN":
            return jsonify({"error": f"Future is {future['status']} — cannot take"}), 400
        if future["creator_wallet"] == taker:
            return jsonify({"error": "Cannot take your own future"}), 400
        if _now() > future["expires_at"]:
            future["status"] = "EXPIRED"
            return jsonify({"error": "Future expired"}), 400

        future["taker_wallet"] = taker
        future["status"]       = "ACTIVE"
        future["activated_at"] = _now()
        _lb(taker)["total_staked"] = round(_lb(taker)["total_staked"] + future["stake_rlusd"], 6)

    opposite = {b for b in _VALID_BIASES if b != future["predicted_bias"]}
    logger.info(f"[FUTURES] {future_id[:8]}… taken by {taker[:12]}…")
    return jsonify({
        "future_id":        future_id,
        "symbol":           future["symbol"],
        "your_position":    f"NOT {future['predicted_bias']} — you win if verdict is {opposite}",
        "creator_predicts": future["predicted_bias"],
        "stake_rlusd":      future["stake_rlusd"],
        "status":           "ACTIVE",
        "message":          f"Position taken. Settles on next {future['symbol']} council verdict.",
    })


@futures_bp.route('', methods=['GET'])
def list_futures():
    symbol = request.args.get("symbol", "").upper()
    status = request.args.get("status", "OPEN").upper()
    bias   = request.args.get("bias", "").upper()
    limit  = min(int(request.args.get("limit", 50)), 200)

    with _lock:
        results = list(_futures.values())

    now = _now()
    for f in results:
        if f["status"] == "OPEN" and now > f["expires_at"]:
            f["status"] = "EXPIRED"

    if symbol:
        results = [f for f in results if f["symbol"] == symbol]
    if status:
        results = [f for f in results if f["status"] == status]
    if bias:
        results = [f for f in results if f["predicted_bias"] == bias]

    results = sorted(results, key=lambda f: f["created_at"], reverse=True)[:limit]

    return jsonify({
        "futures": [{
            "id":              f["id"],
            "symbol":          f["symbol"],
            "predicted_bias":  f["predicted_bias"],
            "session":         f["session"],
            "stake_rlusd":     f["stake_rlusd"],
            "pot_rlusd":       round(f["stake_rlusd"] * 2, 6),
            "status":          f["status"],
            "has_taker":       f["taker_wallet"] is not None,
            "expires_at":      f["expires_at"],
            "note":            f["note"],
        } for f in results],
        "count":   len(results),
        "free":    True,
        "message": "Take the opposite side: POST /api/futures/take/<id>",
    })


@futures_bp.route('/<future_id>', methods=['GET'])
def get_future(future_id):
    with _lock:
        future = _futures.get(future_id)
    if not future:
        return jsonify({"error": "Future not found"}), 404
    now = _now()
    if future["status"] == "OPEN" and now > future["expires_at"]:
        future["status"] = "EXPIRED"
    return jsonify({**future,
        "pot_rlusd":      round(future["stake_rlusd"] * 2, 6),
        "time_remaining": max(0, future["expires_at"] - now),
    })


@futures_bp.route('/settle/<future_id>', methods=['POST'])
def settle_future(future_id):
    with _lock:
        future = _futures.get(future_id)
        if not future:
            return jsonify({"error": "Future not found"}), 404
        if future["status"] == "SETTLED":
            return jsonify({"status": "already_settled", "proof": future["proof"]}), 200
        if future["status"] != "ACTIVE":
            return jsonify({"error": f"Future must be ACTIVE to settle (status: {future['status']})"}), 400

        latest = _get_latest_verdict(future["symbol"])
        if not latest:
            return jsonify({"error": f"No council verdict found for {future['symbol']}"}), 400

        actual_bias = latest.get("bias", "").upper()
        if actual_bias not in _VALID_BIASES:
            return jsonify({"error": f"Invalid bias in verdict: {actual_bias}"}), 400

        proof = _settle_future(future, actual_bias, latest)

    return jsonify({"status": "settled", "proof": proof})


def _get_latest_verdict(symbol: str) -> dict:
    try:
        import core.signal_history as sh
        signals = sh.get_history(symbol, limit=20)
        for s in signals:
            if s.get("type") == "COUNCIL_VERDICT" or s.get("event_type") == "COUNCIL_VERDICT":
                return s
    except Exception:
        pass
    return {}


@futures_bp.route('/leaderboard', methods=['GET'])
def leaderboard():
    limit = min(int(request.args.get("limit", 20)), 100)
    with _lock:
        board = sorted(_leaderboard.values(), key=lambda x: x["wins"], reverse=True)[:limit]
    return jsonify({
        "leaderboard": [{
            "wallet":       lb["wallet"][:12] + "…",
            "wins":         lb["wins"],
            "losses":       lb["losses"],
            "win_rate":     f"{lb['win_rate']*100:.1f}%",
            "total_staked": lb["total_staked"],
            "total_earned": lb["total_earned"],
            "pnl":          round(lb["total_earned"] - lb["total_staked"], 6),
        } for lb in board],
        "count": len(board),
        "free":  True,
    })


@futures_bp.route('/wallet/<wallet>', methods=['GET'])
def wallet_futures(wallet):
    limit = min(int(request.args.get("limit", 50)), 200)
    with _lock:
        results = [f for f in _futures.values()
                   if f["creator_wallet"] == wallet or f["taker_wallet"] == wallet]
    results = sorted(results, key=lambda f: f["created_at"], reverse=True)[:limit]
    lb = _leaderboard.get(wallet, {})
    return jsonify({"wallet": wallet, "futures": results, "count": len(results), "stats": lb})
