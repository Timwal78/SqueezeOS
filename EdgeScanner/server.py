"""
EdgeScanner — Flask API Server
════════════════════════════════
Endpoints:
  GET  /api/scan          — Run full scan on provided symbols
  GET  /api/setups        — Return last cached scan results
  POST /api/scan/custom   — Scan a user-specified symbol list
  GET  /api/health        — Health check
"""

import os
import json
import time
import logging
import threading
from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

from scanner import EdgeScanner
from risk_engine import RiskEngine
from ai_analyst import AIAnalyst

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SERVER")

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# ── Config ────────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 5050))
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL_MINUTES", 5)) * 60
MIN_PRICE = float(os.environ.get("MIN_PRICE", 1.0))
MAX_PRICE = float(os.environ.get("MAX_PRICE", 500.0))
MIN_VOLUME = int(os.environ.get("MIN_VOLUME", 500_000))

# ── Default scan universe ─────────────────────────────────────────────────────
# Broad liquid US equities — high-volume, diverse sectors.
# Users can override via POST /api/scan/custom.
DEFAULT_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD",
    # Finance
    "JPM", "BAC", "GS", "MS", "C", "WFC",
    # Energy
    "XOM", "CVX", "SLB", "HAL",
    # Healthcare
    "JNJ", "UNH", "PFE", "MRNA", "ABBV",
    # Consumer
    "COST", "WMT", "TGT", "HD", "MCD",
    # Industrials
    "CAT", "DE", "GE", "BA",
    # High-beta / retail favorites
    "PLTR", "SOFI", "RIVN", "LCID", "F", "GM",
    # ETFs (liquid, rules-based)
    "SPY", "QQQ", "IWM", "GLD", "TLT",
]

# ── Shared state ──────────────────────────────────────────────────────────────

_state = {
    "setups": [],
    "last_scan": None,
    "scan_count": 0,
    "status": "idle",
}
_lock = threading.Lock()

scanner = EdgeScanner(min_price=MIN_PRICE, max_price=MAX_PRICE, min_volume=MIN_VOLUME)
risk = RiskEngine()

_ai_enabled = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
analyst: AIAnalyst | None = None
if _ai_enabled:
    try:
        analyst = AIAnalyst()
        logger.info("[SERVER] AI analyst loaded (claude-opus-4-7)")
    except RuntimeError as e:
        logger.warning(f"[SERVER] AI analyst disabled: {e}")
        _ai_enabled = False
else:
    logger.warning("[SERVER] ANTHROPIC_API_KEY not set — AI analysis disabled")


# ── Background scan worker ────────────────────────────────────────────────────

def _run_scan(symbols: list[str]) -> list[dict]:
    logger.info(f"[SCAN] Starting scan on {len(symbols)} symbols")
    raw = scanner.scan(symbols)
    logger.info(f"[SCAN] {len(raw)} setups detected pre-risk-filter")
    enriched = risk.enrich(raw)
    logger.info(f"[SCAN] {len(enriched)} setups after R:R filter")

    if analyst and enriched:
        enriched = analyst.analyze_batch(enriched, max_per_cycle=20)
        logger.info(f"[SCAN] AI analysis complete")

    return enriched


def _background_worker():
    while True:
        with _lock:
            _state["status"] = "scanning"
        try:
            results = _run_scan(DEFAULT_UNIVERSE)
            with _lock:
                _state["setups"] = results
                _state["last_scan"] = datetime.utcnow().isoformat() + "Z"
                _state["scan_count"] += 1
                _state["status"] = "idle"
            logger.info(f"[SCAN] Cycle #{_state['scan_count']} complete — {len(results)} setups")
        except Exception as e:
            logger.error(f"[SCAN] Worker error: {e}")
            with _lock:
                _state["status"] = "error"
        time.sleep(SCAN_INTERVAL)


# Start background worker
_worker_thread = threading.Thread(target=_background_worker, daemon=True)
_worker_thread.start()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/health")
def health():
    with _lock:
        return jsonify({
            "status": "ok",
            "scan_status": _state["status"],
            "last_scan": _state["last_scan"],
            "scan_count": _state["scan_count"],
            "setup_count": len(_state["setups"]),
            "ai_enabled": _ai_enabled,
        })


@app.route("/api/setups")
def get_setups():
    min_score = float(request.args.get("min_score", 0))
    direction = request.args.get("direction", "all")
    pattern = request.args.get("pattern", "all")
    limit = int(request.args.get("limit", 50))

    with _lock:
        setups = list(_state["setups"])
        last_scan = _state["last_scan"]
        status = _state["status"]

    if min_score > 0:
        setups = [s for s in setups if s.get("edge_score", 0) >= min_score]
    if direction != "all":
        setups = [s for s in setups if s.get("direction") == direction]
    if pattern != "all":
        setups = [s for s in setups if pattern.lower() in s.get("pattern", "").lower()]

    setups = setups[:limit]

    return jsonify({
        "setups": setups,
        "count": len(setups),
        "last_scan": last_scan,
        "status": status,
    })


@app.route("/api/scan", methods=["GET"])
def trigger_scan():
    """Trigger an immediate scan on the default universe (non-blocking)."""
    with _lock:
        if _state["status"] == "scanning":
            return jsonify({"message": "Scan already in progress"}), 202

    def run():
        with _lock:
            _state["status"] = "scanning"
        try:
            results = _run_scan(DEFAULT_UNIVERSE)
            with _lock:
                _state["setups"] = results
                _state["last_scan"] = datetime.utcnow().isoformat() + "Z"
                _state["scan_count"] += 1
                _state["status"] = "idle"
        except Exception as e:
            logger.error(f"[SCAN] On-demand error: {e}")
            with _lock:
                _state["status"] = "error"

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"message": "Scan started"}), 202


@app.route("/api/scan/custom", methods=["POST"])
def custom_scan():
    """Scan a user-provided list of symbols synchronously (blocks until done)."""
    body = request.get_json(silent=True) or {}
    symbols = body.get("symbols", [])

    if not symbols or not isinstance(symbols, list):
        return jsonify({"error": "Provide a JSON body: {\"symbols\": [\"AAPL\", ...]}"}), 400

    symbols = [str(s).upper().strip() for s in symbols if s][:100]

    try:
        results = _run_scan(symbols)
        return jsonify({
            "setups": results,
            "count": len(results),
            "symbols_scanned": len(symbols),
        })
    except Exception as e:
        logger.error(f"[CUSTOM_SCAN] Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    logger.info(f"[SERVER] EdgeScanner starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
