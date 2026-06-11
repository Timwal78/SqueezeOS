"""smithery_bp.py — /.well-known/mcp/server-card.json for Smithery skip-scan."""
from flask import Blueprint, jsonify
smithery_bp = Blueprint("smithery", __name__)

CARD = {
    "name": "SqueezeOS",
    "description": "33-tool institutional market intelligence MCP server. Council verdicts, squeeze scanner, options flow, oracle data, futures, settlement, x402 micropayments via USDC on Base or RLUSD on XRPL.",
    "version": "7.0.0",
    "url": "https://squeezeos-api.onrender.com/mcp",
    "protocol": "MCP JSON-RPC 2.0",
    "homepage": "https://www.scriptmasterlabs.com/stack",
    "payment": {"protocol": "x402", "networks": ["base", "xrpl", "xahau"], "asset": "USDC / RLUSD"},
    "tools_count": 33
}

@smithery_bp.route("/smithery-ping")
def smithery_ping():
    return jsonify({"ok": True, "name": "smithery_bp"})

@smithery_bp.route("/.well-known/mcp/server-card.json")
def server_card():
    return jsonify(CARD)
