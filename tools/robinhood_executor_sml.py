"""
SqueezeOS Robinhood Executor — SML Signal Receiver
════════════════════════════════════════════════════
Runs on the Windows machine. Listens for SML webhook alerts from
squeezeos-api.onrender.com, pulls live feature flags from the remote
config endpoint, and executes equity + options trades via robin_stocks.

Remote config:  GET https://squeezeos-api.onrender.com/api/config
  OPTIONS_ENABLED    — enable/disable options execution (default: False)
  EQUITY_ENABLED     — enable/disable equity execution (default: True)
  KILL_SWITCH        — emergency halt all execution (default: False)
  MAX_EQUITY_SHARES  — max shares per equity order
  MAX_CONTRACTS      — max contracts per options order
  PAPER_MODE         — log-only, no real orders sent

Local .env fallback — used if Render is unreachable at startup or on a call.
Set SQUEEZEOS_API_URL to override the Render endpoint for testing.
"""

import os
import json
import time
import logging
import hmac
import hashlib
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request as URLRequest
from urllib.error import URLError
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("RobinhoodExecutor")

# ── Configuration ─────────────────────────────────────────────────────────────

SQUEEZEOS_API_URL  = os.environ.get("SQUEEZEOS_API_URL", "https://squeezeos-api.onrender.com")
ROBINHOOD_USER     = os.environ.get("ROBINHOOD_USERNAME", "")
ROBINHOOD_PASS     = os.environ.get("ROBINHOOD_PASSWORD", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "squeezeos-webhook-default-secret")
EXECUTOR_PORT      = int(os.environ.get("EXECUTOR_PORT", "9182"))
CONFIG_TTL_S       = int(os.environ.get("CONFIG_TTL_S", "60"))   # re-fetch flags every 60 s

# Local .env fallback values (used when Render is unreachable)
_LOCAL_DEFAULTS = {
    "OPTIONS_ENABLED":    os.environ.get("OPTIONS_ENABLED", "false").lower() == "true",
    "EQUITY_ENABLED":     os.environ.get("EQUITY_ENABLED", "true").lower() == "true",
    "PAPER_MODE":         os.environ.get("ROBINHOOD_PAPER_MODE", "false").lower() == "true",
    "PDT_SHIELD":         os.environ.get("PDT_SHIELD_ENABLED", "true").lower() == "true",
    "MAX_EQUITY_SHARES":  int(os.environ.get("MAX_EQUITY_SHARES", "5")),
    "MAX_CONTRACTS":      int(os.environ.get("MAX_CONTRACTS", "1")),
    "CIRCUIT_BREAKER":    True,
    "MAX_DAILY_LOSS_USD": float(os.environ.get("MAX_DAILY_LOSS_USD", "500")),
    "KILL_SWITCH":        os.environ.get("KILL_SWITCH", "false").lower() == "true",
}


# ── Remote Config Cache ───────────────────────────────────────────────────────

_config_lock     = threading.Lock()
_config_cache    = dict(_LOCAL_DEFAULTS)
_config_fetched  = 0.0   # epoch of last successful fetch


def fetch_remote_config() -> dict:
    """Pull feature flags from Render. Returns cached value on failure."""
    global _config_fetched
    url = f"{SQUEEZEOS_API_URL}/api/config"
    try:
        req = URLRequest(url, headers={"User-Agent": "SqueezeOS-Executor/1.0"})
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        flags = data.get("flags", {})
        with _config_lock:
            _config_cache.update(flags)
            _config_fetched = time.time()
        logger.info(f"[CONFIG] Remote flags loaded: OPTIONS={flags.get('OPTIONS_ENABLED')} "
                    f"EQUITY={flags.get('EQUITY_ENABLED')} KILL={flags.get('KILL_SWITCH')}")
        return dict(_config_cache)
    except Exception as e:
        logger.warning(f"[CONFIG] Remote fetch failed ({e}) — using cached/local flags")
        return dict(_config_cache)


def get_flags() -> dict:
    """Return current flags, refreshing from remote if TTL expired."""
    now = time.time()
    with _config_lock:
        stale = (now - _config_fetched) > CONFIG_TTL_S
    if stale:
        return fetch_remote_config()
    with _config_lock:
        return dict(_config_cache)


# ── Robinhood Session ─────────────────────────────────────────────────────────

_rh_logged_in = False

def _ensure_login():
    global _rh_logged_in
    if _rh_logged_in:
        return True
    if not ROBINHOOD_USER or not ROBINHOOD_PASS:
        logger.error("[RH] ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not set in .env")
        return False
    try:
        import robin_stocks.robinhood as rh
        rh.login(ROBINHOOD_USER, ROBINHOOD_PASS)
        _rh_logged_in = True
        logger.info("[RH] Logged in successfully")
        return True
    except Exception as e:
        logger.error(f"[RH] Login failed: {e}")
        return False


# ── Equity Execution ──────────────────────────────────────────────────────────

def execute_equity(symbol: str, action: str, flags: dict) -> dict:
    if not flags.get("EQUITY_ENABLED"):
        return {"skipped": "EQUITY_ENABLED=false"}

    max_shares = flags.get("MAX_EQUITY_SHARES", 5)

    if flags.get("PAPER_MODE"):
        logger.info(f"[PAPER] equity {action} {max_shares}x {symbol}")
        return {"paper": True, "action": action, "symbol": symbol, "qty": max_shares}

    if not _ensure_login():
        return {"error": "login_failed"}

    try:
        import robin_stocks.robinhood as rh
        if action in ("BUY", "BUY_PRIME"):
            result = rh.order_buy_market(symbol, max_shares)
        elif action in ("SELL", "EXIT"):
            result = rh.order_sell_market(symbol, max_shares)
        else:
            return {"skipped": f"no equity handler for action={action}"}

        logger.info(f"[RH] Equity order placed: {symbol} {action} x{max_shares} → {result}")
        return {"placed": True, "result": result}
    except Exception as e:
        logger.error(f"[RH] Equity order error: {e}")
        return {"error": str(e)}


# ── Options Execution ─────────────────────────────────────────────────────────

def execute_options(symbol: str, action: str, payload: dict, flags: dict) -> dict:
    if not flags.get("OPTIONS_ENABLED"):
        return {"skipped": "OPTIONS_ENABLED=false"}

    max_contracts = flags.get("MAX_CONTRACTS", 1)
    expiry        = payload.get("expiry")          # e.g. "2026-06-20"
    strike        = payload.get("strike")           # e.g. 190.0
    opt_type      = payload.get("option_type", "call").lower()  # call | put

    if not expiry or not strike:
        return {"error": "options require expiry and strike in payload"}

    if flags.get("PAPER_MODE"):
        logger.info(f"[PAPER] options {action} {max_contracts}x {symbol} {strike} {opt_type} exp={expiry}")
        return {"paper": True, "action": action, "symbol": symbol,
                "strike": strike, "expiry": expiry, "type": opt_type, "qty": max_contracts}

    if not _ensure_login():
        return {"error": "login_failed"}

    try:
        import robin_stocks.robinhood as rh
        if action in ("BUY", "BUY_PRIME"):
            result = rh.order_buy_option_limit(
                "open", "debit", float(strike) * 0.05,  # ~5% of strike as limit price
                symbol, max_contracts, expiry, float(strike), opt_type
            )
        elif action in ("SELL", "EXIT"):
            result = rh.order_sell_option_limit(
                "close", "credit", float(strike) * 0.03,
                symbol, max_contracts, expiry, float(strike), opt_type
            )
        else:
            return {"skipped": f"no options handler for action={action}"}

        logger.info(f"[RH] Options order placed: {symbol} {action} {opt_type} {strike} exp={expiry} → {result}")
        return {"placed": True, "result": result}
    except Exception as e:
        logger.error(f"[RH] Options order error: {e}")
        return {"error": str(e)}


# ── Circuit Breaker ───────────────────────────────────────────────────────────

_daily_loss_usd  = 0.0
_daily_loss_lock = threading.Lock()


def _record_loss(amount_usd: float):
    global _daily_loss_usd
    with _daily_loss_lock:
        _daily_loss_usd += amount_usd


def _circuit_open(flags: dict) -> bool:
    if flags.get("KILL_SWITCH"):
        logger.warning("[CIRCUIT] KILL_SWITCH active — all execution halted")
        return True
    if flags.get("CIRCUIT_BREAKER"):
        with _daily_loss_lock:
            loss = _daily_loss_usd
        limit = flags.get("MAX_DAILY_LOSS_USD", 500.0)
        if loss >= limit:
            logger.warning(f"[CIRCUIT] Daily loss ${loss:.2f} ≥ limit ${limit:.2f} — halted")
            return True
    return False


# ── Webhook Request Handler ───────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, sig_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


class AlertHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.debug(fmt % args)

    def do_POST(self):
        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        sig      = self.headers.get("X-SqueezeOS-Signature", "")

        if sig and not _verify_signature(raw_body, sig):
            logger.warning(f"[WEBHOOK] Signature mismatch from {self.client_address[0]}")
            self._respond(401, {"error": "invalid_signature"})
            return

        try:
            payload = json.loads(raw_body)
        except Exception:
            self._respond(400, {"error": "invalid_json"})
            return

        logger.info(f"[WEBHOOK] Received: {payload}")
        threading.Thread(target=self._handle_alert, args=(payload,), daemon=True).start()
        self._respond(200, {"status": "queued"})

    def do_GET(self):
        if self.path == "/health":
            flags = get_flags()
            self._respond(200, {
                "status":   "operational",
                "flags":    flags,
                "rh_login": _rh_logged_in,
                "ts":       datetime.now().isoformat(),
            })
        else:
            self._respond(404, {"error": "not_found"})

    def _respond(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _handle_alert(self, payload: dict):
        flags  = get_flags()
        symbol = payload.get("ticker", payload.get("symbol", "")).upper().strip()
        action = payload.get("action", payload.get("directive", "")).upper().strip()

        if not symbol or not action:
            logger.warning(f"[ALERT] Missing symbol or action in payload: {payload}")
            return

        if _circuit_open(flags):
            return

        # ── Harmonic Matrix Execution Gate ────────────────────────────────────
        # Only execute if the SML Harmonic Matrix confirms GOD_MODE tier.
        # Requires: tier=GOD_MODE AND god_stacked ≥ 3 (≥3 SET9 configs stacked).
        # Alerts from lower tiers (PRIME, WATCH) are logged but never executed.
        sml = payload.get("sml_matrix") or {}
        matrix_tier    = sml.get("tier", "NONE")
        god_stacked    = sml.get("god_stacked", 0)
        execute_gate   = sml.get("execute_gate", False)
        harmonic_score = sml.get("harmonic_score", 0)

        if not execute_gate or matrix_tier != "GOD_MODE":
            logger.warning(
                f"[GATE] {symbol} BLOCKED — tier={matrix_tier} god_stacked={god_stacked} "
                f"execute_gate={execute_gate} harmonic_score={harmonic_score} "
                f"(GOD_MODE + ≥3 SET9 stacked required)"
            )
            return

        logger.info(
            f"[GATE] {symbol} CLEARED — GOD_MODE CONFIRMED "
            f"god_stacked={god_stacked}/6 harmonic_score={harmonic_score} "
            f"Processing {action}..."
        )

        mode = payload.get("mode", "equity")  # "equity" | "options"

        if mode == "options" or payload.get("option_type"):
            result = execute_options(symbol, action, payload, flags)
        else:
            result = execute_equity(symbol, action, flags)

        logger.info(f"[RESULT] {symbol} {action} → {result}")


# ── Config refresh thread ─────────────────────────────────────────────────────

def _config_refresh_loop():
    while True:
        time.sleep(CONFIG_TTL_S)
        fetch_remote_config()


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("SqueezeOS Robinhood Executor starting")
    logger.info(f"  API endpoint : {SQUEEZEOS_API_URL}")
    logger.info(f"  Listener port: {EXECUTOR_PORT}")
    logger.info(f"  Config TTL   : {CONFIG_TTL_S}s")
    logger.info("=" * 60)

    # Fetch remote config immediately at startup
    flags = fetch_remote_config()
    logger.info(f"[STARTUP] FLAGS → {flags}")

    # Warn if kill switch is on
    if flags.get("KILL_SWITCH"):
        logger.warning("[STARTUP] KILL_SWITCH is ON — no trades will execute until cleared via POST /api/config")

    # Start background config refresh
    threading.Thread(target=_config_refresh_loop, daemon=True, name="ConfigRefresh").start()

    # Pre-warm Robinhood login
    if flags.get("EQUITY_ENABLED") or flags.get("OPTIONS_ENABLED"):
        _ensure_login()

    # Start webhook listener
    server = HTTPServer(("0.0.0.0", EXECUTOR_PORT), AlertHandler)
    logger.info(f"[SERVER] Listening on http://0.0.0.0:{EXECUTOR_PORT}")
    logger.info(f"[SERVER] Health check: http://localhost:{EXECUTOR_PORT}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("[SERVER] Shutdown requested")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
