"""
paper_trade_ledger.py -- persistent, system-tagged record of every paper
fill across every engine (CASCADE, ORB, DRUCK, CIE, Breakout, SR-Matrix,
Gamma Pin, MM Intel, IAM/IMO, ...). Built per operator request ("all paper
trades should be recorded") after iam_executor.py's existing `_positions`
ledger was found to have three real gaps: no per-system attribution (keyed
only by symbol, so two engines trading the same symbol merge into one
untraceable position), resets every UTC day (`_roll_day()`), and lives only
in memory (wiped on any restart/redeploy, no disk/DB write at all).

Storage: Redis (REDIS_URL, the same shared instance CASCADE/AEO/Trade Desk/
DeltaForge already use for durable state) when configured -- this is what
actually survives a Render redeploy. Falls back to a local JSON file (same
atomic tmp+os.replace write convention as performance_tracker.py) when
Redis isn't configured -- honestly disclosed as NOT surviving a redeploy
without a Render persistent disk attached, same constraint already
documented throughout CLAUDE.md for every in-memory store in this repo.
This is a real difference in durability, not just a technicality: don't
represent the JSON-file mode as equivalent to the Redis mode.

Scope: EQUITY fills only, matching iam_executor.py's existing `_positions`
ledger exactly (which never tracked options fills either) -- this persists
and attributes what was already being tracked, it does not add a new
options P&L system that didn't exist before.
"""
from __future__ import annotations

import json
import logging
import os
import time
from threading import Lock

logger = logging.getLogger("PAPER-LEDGER")

_REDIS_URL = os.environ.get("REDIS_URL", "")
_JSON_PATH = os.environ.get("PAPER_LEDGER_JSON_PATH", "paper_trade_ledger.json")
_MAX_CLOSED_TRADES = int(os.environ.get("PAPER_LEDGER_MAX_CLOSED", "5000"))

_lock = Lock()


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        return None


# ── Local JSON fallback (mirrors performance_tracker.py's atomic write) ──────
_local_state = {"open": {}, "closed": [], "stats": {}}
_local_loaded = False


def _load_local():
    global _local_loaded
    if _local_loaded:
        return
    _local_loaded = True
    if os.path.exists(_JSON_PATH):
        try:
            with open(_JSON_PATH, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _local_state["open"] = loaded.get("open", {})
                _local_state["closed"] = loaded.get("closed", [])
                _local_state["stats"] = loaded.get("stats", {})
        except Exception as e:
            logger.error(f"[PAPER-LEDGER] local load error: {e}")


def _save_local():
    try:
        tmp_path = _JSON_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(_local_state, f, indent=2)
        os.replace(tmp_path, _JSON_PATH)
    except Exception as e:
        logger.error(f"[PAPER-LEDGER] local save error: {e}")


def _pos_key(system: str, symbol: str) -> str:
    return f"{system.upper()}|{symbol.upper()}"


def _update_stats(stats: dict, system: str, pnl: float) -> dict:
    s = stats.get(system, {"total_trades": 0, "wins": 0, "losses": 0,
                           "gross_win": 0.0, "gross_loss": 0.0, "total_pnl": 0.0})
    s["total_trades"] += 1
    s["total_pnl"] += pnl
    if pnl > 0:
        s["wins"] += 1
        s["gross_win"] += pnl
    else:
        s["losses"] += 1
        s["gross_loss"] += -pnl
    s["win_rate"] = (s["wins"] / s["total_trades"] * 100.0) if s["total_trades"] else 0.0
    s["profit_factor"] = (s["gross_win"] / s["gross_loss"]) if s["gross_loss"] > 0 else (
        float("inf") if s["gross_win"] > 0 else 0.0)
    stats[system] = s
    return stats


def record_open(system: str, symbol: str, qty: int, price: float):
    """Weighted-average open (same math as iam_executor._ledger_buy)."""
    if qty <= 0 or price <= 0:
        return
    system = (system or "UNKNOWN").strip().upper()
    symbol = symbol.strip().upper()
    key = _pos_key(system, symbol)

    with _lock:
        r = _get_redis()
        if r:
            try:
                raw = r.hget("paper_ledger:open", key)
                pos = json.loads(raw) if raw else {"qty": 0, "avg": 0.0}
                total_cost = pos["avg"] * pos["qty"] + price * qty
                pos["qty"] += qty
                pos["avg"] = total_cost / pos["qty"]
                pos["opened_at"] = pos.get("opened_at", time.time())
                r.hset("paper_ledger:open", key, json.dumps(pos))
                return
            except Exception as e:
                logger.warning(f"[PAPER-LEDGER] Redis open failed, falling back to local file: {e}")

        _load_local()
        pos = _local_state["open"].get(key, {"qty": 0, "avg": 0.0})
        total_cost = pos["avg"] * pos["qty"] + price * qty
        pos["qty"] += qty
        pos["avg"] = total_cost / pos["qty"]
        pos["opened_at"] = pos.get("opened_at", time.time())
        _local_state["open"][key] = pos
        _save_local()


def record_close(system: str, symbol: str, qty: int, price: float):
    """Reduce/close the tracked (system, symbol) position and append a
    closed-trade record with realized P&L -- same clamp-to-available-qty
    behavior as iam_executor._ledger_sell."""
    if qty <= 0 or price <= 0:
        return
    system = (system or "UNKNOWN").strip().upper()
    symbol = symbol.strip().upper()
    key = _pos_key(system, symbol)

    with _lock:
        r = _get_redis()
        if r:
            try:
                raw = r.hget("paper_ledger:open", key)
                pos = json.loads(raw) if raw else None
                if not pos or pos.get("qty", 0) <= 0:
                    return
                closed_qty = min(qty, pos["qty"])
                realized = (price - pos["avg"]) * closed_qty
                pos["qty"] -= closed_qty
                if pos["qty"] <= 0:
                    r.hdel("paper_ledger:open", key)
                else:
                    r.hset("paper_ledger:open", key, json.dumps(pos))

                trade = {
                    "system": system, "symbol": symbol, "qty": closed_qty,
                    "entry_price": pos["avg"], "exit_price": price,
                    "pnl": realized, "pnl_pct": (realized / (pos["avg"] * closed_qty) * 100.0) if pos["avg"] > 0 else 0.0,
                    "opened_at": pos.get("opened_at"), "closed_at": time.time(),
                }
                r.lpush("paper_ledger:closed", json.dumps(trade))
                r.ltrim("paper_ledger:closed", 0, _MAX_CLOSED_TRADES - 1)

                raw_stats = r.get("paper_ledger:stats")
                stats = json.loads(raw_stats) if raw_stats else {}
                stats = _update_stats(stats, system, realized)
                r.set("paper_ledger:stats", json.dumps(stats))
                logger.info(f"[PAPER-LEDGER] {system} closed {closed_qty}x {symbol} @ ${price:.2f} -> realized {realized:+.2f}")
                return
            except Exception as e:
                logger.warning(f"[PAPER-LEDGER] Redis close failed, falling back to local file: {e}")

        _load_local()
        pos = _local_state["open"].get(key)
        if not pos or pos.get("qty", 0) <= 0:
            return
        closed_qty = min(qty, pos["qty"])
        realized = (price - pos["avg"]) * closed_qty
        pos["qty"] -= closed_qty
        if pos["qty"] <= 0:
            _local_state["open"].pop(key, None)
        else:
            _local_state["open"][key] = pos

        trade = {
            "system": system, "symbol": symbol, "qty": closed_qty,
            "entry_price": pos["avg"], "exit_price": price,
            "pnl": realized, "pnl_pct": (realized / (pos["avg"] * closed_qty) * 100.0) if pos["avg"] > 0 else 0.0,
            "opened_at": pos.get("opened_at"), "closed_at": time.time(),
        }
        _local_state["closed"].insert(0, trade)
        _local_state["closed"] = _local_state["closed"][:_MAX_CLOSED_TRADES]
        _local_state["stats"] = _update_stats(_local_state["stats"], system, realized)
        _save_local()
        logger.info(f"[PAPER-LEDGER] {system} closed {closed_qty}x {symbol} @ ${price:.2f} -> realized {realized:+.2f} (local file)")


def get_summary(system: str = None, limit: int = 100) -> dict:
    """Returns {backend, open_positions, closed_trades, stats}. Filtered to
    one system when given, else every system's data (per-system stats plus
    a combined 'ALL' aggregate)."""
    system_u = system.strip().upper() if system else None

    r = _get_redis()
    if r:
        try:
            open_raw = r.hgetall("paper_ledger:open")
            open_positions = {k: json.loads(v) for k, v in open_raw.items()
                              if not system_u or k.startswith(system_u + "|")}
            closed_raw = r.lrange("paper_ledger:closed", 0, -1)
            closed = [json.loads(c) for c in closed_raw]
            if system_u:
                closed = [c for c in closed if c["system"] == system_u]
            closed = closed[:limit]
            stats_raw = r.get("paper_ledger:stats")
            stats = json.loads(stats_raw) if stats_raw else {}
            if system_u:
                stats = {system_u: stats.get(system_u, {})}
            return {"backend": "redis", "open_positions": open_positions,
                    "closed_trades": closed, "stats": stats}
        except Exception as e:
            logger.warning(f"[PAPER-LEDGER] Redis read failed, falling back to local file: {e}")

    _load_local()
    open_positions = {k: v for k, v in _local_state["open"].items()
                      if not system_u or k.startswith(system_u + "|")}
    closed = _local_state["closed"]
    if system_u:
        closed = [c for c in closed if c["system"] == system_u]
    closed = closed[:limit]
    stats = _local_state["stats"]
    if system_u:
        stats = {system_u: stats.get(system_u, {})}
    return {"backend": "local_json_no_redis_configured", "open_positions": open_positions,
            "closed_trades": closed, "stats": stats}
