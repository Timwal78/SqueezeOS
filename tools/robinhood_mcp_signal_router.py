"""
SqueezeOS Robinhood MCP Signal Router — decision logic ONLY
═══════════════════════════════════════════════════════════
Purpose: decide whether a GOD_MODE / oracle signal from squeezeos-api
warrants a trade proposal for the Robinhood Agentic account, using the
same direction gates as the existing tools/robinhood_executor_sml.py
(741 macro regime, 365-day EMA anchor, Proprietary 5-EMA stack, 321
dark-pool volume) plus its own independent cooldown / daily-notional /
daily-loss / order-count circuit breaker.

This module does NOT place orders and does NOT talk to Robinhood at
all. It can't: Robinhood's official Trading MCP
(agent.robinhood.com/mcp/trading) is only reachable through a live
Claude session that has completed Robinhood's own OAuth connection —
there is no portable bearer token this standalone script could use
(confirmed by testing the actual connection; no guessing here). So the
architecture is split in two:

  1. THIS script — pure decision logic, runs anywhere, fully testable,
     produces a JSON list of proposed trades. Safe to run repeatedly;
     changes nothing on Robinhood.
  2. A live Claude session with the Robinhood MCP connector attached —
     reads this script's `propose` output, calls the real
     `review_equity_order` then `place_equity_order` tools for each
     proposal that still passes a live buying-power check, and then
     calls `record-execution` on this script so cooldown/circuit-
     breaker state persists across runs.

Every dollar-figure limit below (RH_MCP_MAX_ORDER_USD,
RH_MCP_MAX_DAILY_NOTIONAL_USD, RH_MCP_MAX_DAILY_LOSS_USD,
RH_MCP_MAX_ORDERS_PER_DAY) has NO built-in default. Money limits on a
real account are the operator's call, not something to assume — if any
of them is unset, `propose` refuses to propose anything and says why.

Master switch: RH_MCP_ENABLED=true. Circuit breaker: RH_MCP_KILL_SWITCH=true
halts everything immediately (mirrors the existing scraper's KILL_SWITCH).

CLI:
    python tools/robinhood_mcp_signal_router.py propose
    python tools/robinhood_mcp_signal_router.py record-execution \
        --symbol NVDA --side buy --qty 3 --price 181.42
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import zoneinfo
from datetime import datetime, time as dtime

SQUEEZEOS_API_URL = os.environ.get("SQUEEZEOS_API_URL", "https://squeezeos-api.onrender.com")

RH_MCP_ENABLED = os.environ.get("RH_MCP_ENABLED", "false").lower() == "true"
RH_MCP_KILL_SWITCH = os.environ.get("RH_MCP_KILL_SWITCH", "false").lower() == "true"
RH_MCP_MIN_GOD_STACKED = int(os.environ.get("RH_MCP_MIN_GOD_STACKED", "3"))
RH_MCP_ORACLE_MIN_CONFIDENCE = float(os.environ.get("RH_MCP_ORACLE_MIN_CONFIDENCE", "60.0"))
RH_MCP_COOLDOWN_S = int(os.environ.get("RH_MCP_COOLDOWN_S", "900"))  # not a money figure — safe default

# Money limits — intentionally NO default. None means "not configured".
def _optional_float(name: str):
    val = os.environ.get(name, "").strip()
    return float(val) if val else None

def _optional_int(name: str):
    val = os.environ.get(name, "").strip()
    return int(val) if val else None

RH_MCP_MAX_ORDER_USD = _optional_float("RH_MCP_MAX_ORDER_USD")
RH_MCP_MAX_DAILY_NOTIONAL_USD = _optional_float("RH_MCP_MAX_DAILY_NOTIONAL_USD")
RH_MCP_MAX_DAILY_LOSS_USD = _optional_float("RH_MCP_MAX_DAILY_LOSS_USD")
RH_MCP_MAX_ORDERS_PER_DAY = _optional_int("RH_MCP_MAX_ORDERS_PER_DAY")

_BLOCKLIST = {
    "AMCX", "FXST", "CODA", "NKLA",
    "ZXZZT", "ZVZZT", "ZAZZT", "ZBZZT",
}

_STATE_DIR = os.environ.get(
    "RH_MCP_STATE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rh_mcp_state"),
)
_STATE_FILE = os.path.join(_STATE_DIR, "state.json")
_ET = zoneinfo.ZoneInfo("America/New_York")


def _load_state() -> dict:
    try:
        with open(_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"last_execution": {}, "trading_day": "", "orders_today": 0,
                "daily_notional_usd": 0.0, "daily_loss_usd": 0.0}


def _save_state(state: dict) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _reset_daily_if_new_day(state: dict) -> dict:
    today = datetime.now(_ET).strftime("%Y-%m-%d")
    if state.get("trading_day") != today:
        state["trading_day"] = today
        state["orders_today"] = 0
        state["daily_notional_usd"] = 0.0
        state["daily_loss_usd"] = 0.0
    return state


def _get(url: str, headers: dict, timeout: int = 20):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_macro_regime(symbol: str) -> str:
    secret = os.environ.get("MACRO_GATE_SECRET", "")
    if not secret:
        return "UNKNOWN"
    try:
        data = _get(f"{SQUEEZEOS_API_URL}/api/macro/{symbol}",
                     {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0", "X-Macro-Secret": secret}, timeout=10)
        return data.get("regime", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def _get_365_anchor(symbol: str) -> str:
    secret = os.environ.get("MACRO_GATE_SECRET", "")
    if not secret:
        return "UNKNOWN"
    try:
        data = _get(f"{SQUEEZEOS_API_URL}/api/anchor365/{symbol}",
                     {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0", "X-Macro-Secret": secret}, timeout=10)
        return data.get("signal", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def _direction_gates_pass(symbol: str, side: str) -> tuple[bool, str]:
    """Same gates as robinhood_executor_sml._direction_gates_pass. Fails open
    (never blocks) on missing secrets or fetch errors. Returns (ok, reason)."""
    if side == "buy":
        macro = _get_macro_regime(symbol)
        if macro == "PERFECT_BEARISH_REGIME":
            return False, f"741 macro regime is PERFECT_BEARISH_REGIME"
        anchor365 = _get_365_anchor(symbol)
        if anchor365 == "BELOW":
            return False, "price is BELOW the 365-day EMA anchor"

    try:
        ema_data = _get(f"{SQUEEZEOS_API_URL}/api/ema/{symbol}",
                         {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0"}, timeout=10)
        if ema_data.get("status") == "success":
            suite = ema_data.get("ema_suite", {})
            e5_signal = suite.get("engine_5", {}).get("signal", "")
            if side == "buy" and e5_signal == "BEAR_STACK_5EMA":
                return False, "Proprietary 5-EMA stack is BEARISH"
            if side == "sell" and e5_signal == "BULL_STACK_5EMA":
                return False, "Proprietary 5-EMA stack is BULLISH"
            e3 = suite.get("engine_3", {})
            if side == "buy" and (e3.get("mirror_lock_bear") or e3.get("signal") == "DISTRIBUTION"):
                return False, "dark-pool volume (321) shows DISTRIBUTION"
            if side == "sell" and e3.get("signal") in ("DARK_POOL_CEILING_BREACH", "DARK_POOL_ACCUMULATION"):
                return False, "dark-pool volume (321) shows active ACCUMULATION"
    except Exception:
        pass  # fail open, same as existing scraper

    return True, "ok"


def _market_open() -> bool:
    now_et = datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return dtime(4, 0) <= t < dtime(20, 0)


def _fetch_beastmode_signals() -> list:
    try:
        data = _get(f"{SQUEEZEOS_API_URL}/api/beastmode", {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0"}, timeout=30)
    except Exception as e:
        return []
    if data.get("status") != "success":
        return []
    out = []
    for hit in data.get("signals") or []:
        sml = hit.get("sml_matrix") or {}
        tier = sml.get("tier", "")
        signal = sml.get("signal", "")
        if tier not in ("GOD_MODE", "DUAL_GRID_LOCK", "GRID_LOCK"):
            if "DUAL" in signal.upper():
                tier = "DUAL_GRID_LOCK"
            elif "GRID" in signal.upper():
                tier = "GRID_LOCK"
        if tier not in ("GOD_MODE", "DUAL_GRID_LOCK", "GRID_LOCK"):
            continue
        min_stack = RH_MCP_MIN_GOD_STACKED if tier != "GRID_LOCK" else max(2, RH_MCP_MIN_GOD_STACKED - 1)
        stacked = sml.get("god_stacked", 0)
        if stacked < min_stack:
            continue
        symbol = (hit.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        side = "sell" if "BEAR" in signal else "buy"
        out.append({"symbol": symbol, "side": side, "source": f"beastmode:{tier}",
                     "god_stacked": stacked, "confidence": None})
    return out


def _fetch_tv_pending_signals() -> list:
    """Pine script alerts (any SML_* system — Sniper, MMLE Beast, Base4 Fractal
    Grid, Sovereign Stack, Apex Sonar, Triple Lock Beastmode+, Proprietary EMA
    Suite, etc.) queued via core/api/tradingview_webhook_bp.py's generic
    /api/webhooks/tradingview endpoint. Any script's alert lands here as long
    as its TradingView alert POSTs the expected payload — that wiring happens
    on the TradingView side, per chart, not in this script."""
    out = []
    try:
        data = _get(f"{SQUEEZEOS_API_URL}/api/webhooks/tv_pending",
                     {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0"}, timeout=30)
        for sig in data.get("signals") or []:
            symbol = (sig.get("symbol") or "").upper().strip()
            direction = (sig.get("action") or "").upper().strip()
            if not symbol or direction not in ("BUY", "SELL"):
                continue
            out.append({
                "symbol": symbol, "side": "buy" if direction == "BUY" else "sell",
                "source": f"pine:{sig.get('system', 'unknown')}",
                "god_stacked": None, "confidence": sig.get("confidence"),
            })
    except Exception:
        pass
    return out


def _fetch_oracle_signals() -> list:
    out = []
    try:
        data = _get(f"{SQUEEZEOS_API_URL}/api/oracle", {"User-Agent": "SqueezeOS-RH-MCP-Router/1.0"}, timeout=20)
        for sym, info in (data.get("symbols") or {}).items():
            if not isinstance(info, dict):
                continue
            directive = (info.get("directive") or "").upper()
            confidence = float(info.get("confidence") or 0)
            if directive in ("BUY", "BUY (IGNITION)", "SELL") and confidence > 0:
                side = "sell" if directive == "SELL" else "buy"
                out.append({"symbol": sym.upper(), "side": side, "source": f"oracle:{directive}",
                             "god_stacked": None, "confidence": confidence})
    except Exception:
        pass
    return out


def propose() -> dict:
    """Pure decision function. Returns a dict with 'proposals' (list) and
    'blocked_reason' (str or None) — never places or attempts a trade."""
    if not RH_MCP_ENABLED:
        return {"proposals": [], "blocked_reason": "RH_MCP_ENABLED is not 'true'"}
    if RH_MCP_KILL_SWITCH:
        return {"proposals": [], "blocked_reason": "RH_MCP_KILL_SWITCH is 'true'"}
    missing = [n for n, v in [
        ("RH_MCP_MAX_ORDER_USD", RH_MCP_MAX_ORDER_USD),
        ("RH_MCP_MAX_DAILY_NOTIONAL_USD", RH_MCP_MAX_DAILY_NOTIONAL_USD),
        ("RH_MCP_MAX_DAILY_LOSS_USD", RH_MCP_MAX_DAILY_LOSS_USD),
        ("RH_MCP_MAX_ORDERS_PER_DAY", RH_MCP_MAX_ORDERS_PER_DAY),
    ] if v is None]
    if missing:
        return {"proposals": [], "blocked_reason": f"risk limits not configured: {', '.join(missing)}"}
    if not _market_open():
        return {"proposals": [], "blocked_reason": "market closed (4:00 AM - 8:00 PM ET, Mon-Fri only)"}

    state = _reset_daily_if_new_day(_load_state())

    if state["daily_loss_usd"] >= RH_MCP_MAX_DAILY_LOSS_USD:
        return {"proposals": [], "blocked_reason": f"daily loss ${state['daily_loss_usd']:.2f} >= limit ${RH_MCP_MAX_DAILY_LOSS_USD}"}
    if state["orders_today"] >= RH_MCP_MAX_ORDERS_PER_DAY:
        return {"proposals": [], "blocked_reason": f"daily order cap reached: {state['orders_today']}/{RH_MCP_MAX_ORDERS_PER_DAY}"}
    remaining_notional = RH_MCP_MAX_DAILY_NOTIONAL_USD - state["daily_notional_usd"]
    if remaining_notional <= 0:
        return {"proposals": [], "blocked_reason": f"daily notional cap reached: ${state['daily_notional_usd']:.2f}/${RH_MCP_MAX_DAILY_NOTIONAL_USD}"}

    now = time.time()
    signals = _fetch_beastmode_signals() + _fetch_tv_pending_signals() + _fetch_oracle_signals()
    proposals = []
    seen_symbols = set()

    for sig in signals:
        symbol, side = sig["symbol"], sig["side"]
        if symbol in seen_symbols or symbol in _BLOCKLIST:
            continue
        if sig.get("confidence") is not None and sig["confidence"] < RH_MCP_ORACLE_MIN_CONFIDENCE:
            continue
        last = state["last_execution"].get(symbol, 0)
        if side == "buy" and now - last < RH_MCP_COOLDOWN_S:
            continue
        ok, reason = _direction_gates_pass(symbol, side)
        if not ok:
            continue
        proposals.append({
            "symbol": symbol, "side": side, "source": sig["source"],
            "god_stacked": sig.get("god_stacked"), "confidence": sig.get("confidence"),
            "max_order_usd": min(RH_MCP_MAX_ORDER_USD, remaining_notional),
            "note": "qty must be computed by the executing session from a LIVE quote "
                    "(get_equity_quotes) and current buying_power (get_portfolio) — "
                    "this script has no live price/account access.",
        })
        seen_symbols.add(symbol)

    return {"proposals": proposals, "blocked_reason": None}


def record_execution(symbol: str, side: str, qty: int, price: float, realized_pnl: float = 0.0) -> None:
    """Call this after a real order is actually placed via the live Robinhood
    MCP session, so cooldown / daily caps persist across router runs."""
    state = _reset_daily_if_new_day(_load_state())
    if side == "buy":
        state["last_execution"][symbol.upper()] = time.time()
        state["orders_today"] += 1
        state["daily_notional_usd"] += qty * price
    if realized_pnl < 0:
        state["daily_loss_usd"] += abs(realized_pnl)
    _save_state(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose", help="Print JSON list of trade proposals (no execution).")
    rec = sub.add_parser("record-execution", help="Record a trade that was actually placed elsewhere.")
    rec.add_argument("--symbol", required=True)
    rec.add_argument("--side", required=True, choices=["buy", "sell"])
    rec.add_argument("--qty", required=True, type=int)
    rec.add_argument("--price", required=True, type=float)
    rec.add_argument("--realized-pnl", type=float, default=0.0)

    args = parser.parse_args()
    if args.cmd == "propose":
        print(json.dumps(propose(), indent=2))
    elif args.cmd == "record-execution":
        record_execution(args.symbol, args.side, args.qty, args.price, args.realized_pnl)
        print(json.dumps({"recorded": True}, indent=2))


if __name__ == "__main__":
    main()
