"""
x402 Settlement Router — multi-agent task orchestration hook.
═══════════════════════════════════════════════════════════════
Off-chain bookkeeping for multi-agent tasks (N agents, a payment graph
between them) that settle in one netted transaction on Base via the
non-custodial x402 Settlement Router smart contracts
(mcp-x402-xrpl/asc-contracts/contracts/settlement-router/). This
blueprint does NOT reimplement the netting algorithm or hold any signing
key — it accumulates the payment graph locally (an audit trail, same
in-memory pattern as _jobs/_contracts/_futures elsewhere in this repo)
and forwards it to the already-deployed mcp-x402-xrpl Node service,
which nets the graph (src/settlement-router/netting.ts) and submits the
actual on-chain settlement transaction.

This is deliberately a NEW blueprint rather than an extension of
hiring_bp.py or settlement_bp.py: both of those model a single
poster/executor pair settling XRPL wallet-to-wallet, by design
(hiring_bp's own docstring: "Zero custody... Pay bounty directly to
executor's XRPL wallet"). A multi-agent Base/USDC payment graph is a
different shape of problem, not a variant of either existing one.

  POST /api/settlement-router/tasks              — register a task + create its on-chain escrow
  GET  /api/settlement-router/tasks               — browse tasks (free)
  GET  /api/settlement-router/tasks/<id>           — task detail incl. accumulated edges (free)
  POST /api/settlement-router/tasks/<id>/edges     — record a sub-task payment edge (agent -> agent)
  POST /api/settlement-router/tasks/<id>/settle    — net accumulated edges + submit on-chain settlement

Status machine: PENDING -> ONCHAIN -> SETTLED (or FAILED if the on-chain call errors)

Env:
  SETTLEMENT_ROUTER_API_BASE       — base URL of the mcp-x402-xrpl vending-router
                                      Node service (src/vending-router-server.ts)
                                      that actually holds the orchestrator signing
                                      key and talks to Base. Unset => 503, same
                                      graceful-degradation pattern as aeo_treasury_bp.
  SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET — shared secret sent as X-Orchestrator-Secret
                                      to that Node service (matches its own env var
                                      of the same name).

In-memory store — resets on restart. Same MVP pattern as _futures/_contracts/
_listings/_jobs/_queue elsewhere in this codebase.
"""

import os
import time
import uuid
import logging
import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-SettlementRouter")
settlement_router_bp = Blueprint("settlement_router", __name__)

_API_BASE = os.environ.get("SETTLEMENT_ROUTER_API_BASE", "").rstrip("/")
_SECRET = os.environ.get("SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET", "")
_HTTP_TIMEOUT_S = 20

_tasks: dict = {}  # local_task_id -> task dict
_MAX_TASKS = 500
_MAX_EDGES_PER_TASK = 200


def _configured() -> bool:
    return bool(_API_BASE and _SECRET)


def _not_configured():
    return jsonify({
        "error": "settlement_router_not_configured",
        "message": (
            "SETTLEMENT_ROUTER_API_BASE and/or SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET are unset. "
            "The on-chain x402 Settlement Router has not been deployed to any network yet — "
            "see mcp-x402-xrpl/asc-contracts/README.md."
        ),
    }), 503


def _summary(t: dict) -> dict:
    return {
        "task_id": t["task_id"],
        "onchain_task_id": t.get("onchain_task_id"),
        "escrow_address": t.get("escrow_address"),
        "agents": t["agents"],
        "expected_payouts": t["expected_payouts"],
        "deadline": t["deadline"],
        "status": t["status"],
        "edge_count": len(t["edges"]),
        "created_at": t["created_at"],
    }


@settlement_router_bp.route("/tasks", methods=["GET"])
def browse():
    status = request.args.get("status", "").upper()
    results = list(_tasks.values())
    if status:
        results = [t for t in results if t["status"] == status]
    results.sort(key=lambda t: -t["created_at"])
    return jsonify({"count": len(results), "tasks": [_summary(t) for t in results[:100]]})


@settlement_router_bp.route("/tasks/<task_id>", methods=["GET"])
def task_detail(task_id):
    t = _tasks.get(task_id)
    if not t:
        return jsonify({"error": "ERR_TASK_NOT_FOUND"}), 404
    return jsonify(t)


@settlement_router_bp.route("/tasks", methods=["POST"])
def create_task():
    if not _configured():
        return _not_configured()

    body = request.get_json(silent=True) or {}
    agents = body.get("agents")
    expected_payouts = body.get("expected_payouts")
    deadline_hours = body.get("deadline_hours", 24)

    if not isinstance(agents, list) or len(agents) == 0:
        return jsonify({"error": "ERR_INVALID_AGENTS", "message": "agents must be a non-empty list of 0x addresses"}), 400
    if not isinstance(expected_payouts, list) or len(expected_payouts) != len(agents):
        return jsonify({"error": "ERR_INVALID_PAYOUTS", "message": "expected_payouts must match agents length"}), 400
    for a in agents:
        if not isinstance(a, str) or not a.startswith("0x") or len(a) != 42:
            return jsonify({"error": "ERR_INVALID_AGENT_ADDRESS", "message": f"not a Base address: {a}"}), 400

    if len(_tasks) >= _MAX_TASKS:
        oldest = min(_tasks.keys(), key=lambda k: _tasks[k]["created_at"])
        _tasks.pop(oldest, None)

    task_id = str(uuid.uuid4())
    deadline = int(time.time() + float(deadline_hours) * 3600)

    try:
        resp = requests.post(
            f"{_API_BASE}/settlement-router/tasks",
            json={
                "agents": agents,
                "expectedPayouts": expected_payouts,
                "deadline": deadline,
            },
            headers={"X-Orchestrator-Secret": _SECRET},
            timeout=_HTTP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.error(f"[SETTLEMENT-ROUTER] create_task HTTP call failed: {exc}")
        return jsonify({"error": "ERR_ONCHAIN_CALL_FAILED", "message": str(exc)}), 502

    if resp.status_code >= 400:
        return jsonify({"error": "ERR_ONCHAIN_CREATE_FAILED", "upstream_status": resp.status_code, "upstream_body": resp.text[:1000]}), 502

    onchain = resp.json()

    _tasks[task_id] = {
        "task_id": task_id,
        "onchain_task_id": onchain.get("taskId"),
        "escrow_address": onchain.get("escrow"),
        "agents": agents,
        "expected_payouts": expected_payouts,
        "deadline": deadline,
        "status": "ONCHAIN",
        "edges": [],
        "created_at": time.time(),
        "settle_result": None,
    }

    logger.info(f"[SETTLEMENT-ROUTER] Task {task_id[:8]} created on-chain — escrow={onchain.get('escrow')}")

    return jsonify(_summary(_tasks[task_id])), 201


@settlement_router_bp.route("/tasks/<task_id>/edges", methods=["POST"])
def add_edge(task_id):
    t = _tasks.get(task_id)
    if not t:
        return jsonify({"error": "ERR_TASK_NOT_FOUND"}), 404
    if t["status"] != "ONCHAIN":
        return jsonify({"error": "ERR_TASK_NOT_ONCHAIN", "current_status": t["status"]}), 409

    body = request.get_json(silent=True) or {}
    from_addr = (body.get("from") or "").strip()
    to_addr = (body.get("to") or "").strip()
    amount = body.get("amount")

    if not from_addr.startswith("0x") or not to_addr.startswith("0x"):
        return jsonify({"error": "ERR_INVALID_ADDRESS"}), 400
    if from_addr.lower() == to_addr.lower():
        return jsonify({"error": "ERR_SELF_PAYMENT"}), 400
    try:
        amount_int = int(amount)
        assert amount_int > 0
    except (TypeError, ValueError, AssertionError):
        return jsonify({"error": "ERR_INVALID_AMOUNT", "message": "amount must be a positive integer (token base units)"}), 400

    if len(t["edges"]) >= _MAX_EDGES_PER_TASK:
        return jsonify({"error": "ERR_EDGE_LIMIT", "message": f"Max {_MAX_EDGES_PER_TASK} edges per task"}), 429

    t["edges"].append({"from": from_addr, "to": to_addr, "amount": str(amount_int), "recorded_at": time.time()})

    return jsonify({"task_id": task_id, "edge_count": len(t["edges"])}), 201


@settlement_router_bp.route("/tasks/<task_id>/settle", methods=["POST"])
def settle_task(task_id):
    if not _configured():
        return _not_configured()

    t = _tasks.get(task_id)
    if not t:
        return jsonify({"error": "ERR_TASK_NOT_FOUND"}), 404
    if t["status"] != "ONCHAIN":
        return jsonify({"error": "ERR_TASK_NOT_ONCHAIN", "current_status": t["status"]}), 409
    if not t["edges"]:
        return jsonify({"error": "ERR_NO_EDGES", "message": "No payment-graph edges recorded for this task yet"}), 400

    try:
        resp = requests.post(
            f"{_API_BASE}/settlement-router/tasks/{t['onchain_task_id']}/settle",
            json={"edges": [{"from": e["from"], "to": e["to"], "amount": e["amount"]} for e in t["edges"]]},
            headers={"X-Orchestrator-Secret": _SECRET},
            timeout=_HTTP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.error(f"[SETTLEMENT-ROUTER] settle_task HTTP call failed: {exc}")
        return jsonify({"error": "ERR_ONCHAIN_CALL_FAILED", "message": str(exc)}), 502

    if resp.status_code >= 400:
        t["status"] = "FAILED"
        return jsonify({"error": "ERR_ONCHAIN_SETTLE_FAILED", "upstream_status": resp.status_code, "upstream_body": resp.text[:1000]}), 502

    result = resp.json()
    t["status"] = "SETTLED"
    t["settle_result"] = result

    logger.info(f"[SETTLEMENT-ROUTER] Task {task_id[:8]} settled on-chain — tx={result.get('txHash')}")

    try:
        import core.signal_history as signal_history
        signal_history.record("SETTLEMENT-ROUTER", "TASK_SETTLED", {
            "task_id": task_id,
            "onchain_task_id": t["onchain_task_id"],
            "tx_hash": result.get("txHash"),
            "total_flow": result.get("totalFlow"),
            "protocol_fee": result.get("protocolFee"),
        })
    except Exception:
        pass

    return jsonify({"task_id": task_id, "status": "SETTLED", "result": result})
