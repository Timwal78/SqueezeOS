"""
Engine 2 — FTD Settlement Clock (Reg SHO Chronometer)
=======================================================
An autonomous timer. No moving averages. Pure boolean date-array logic.

T+0:  Stamped when Engine 3 detects volume crossing 123/321 baselines
      while Engine 1 shows price suppressed. Cannot be gamed.

T+13: 13 consecutive TRADING days from ignition.
      SEC Reg SHO — threshold-list stocks must close FTDs after 13
      consecutive settlement failures. Skips weekends + NYSE holidays.

C+35: 35 CALENDAR days from ignition.
      Bona fide market maker exemption deadline. Straight calendar count.

Kill Zone: The 72-hour (3-day) window immediately preceding each deadline.
           MMs typically start covering before the final hour to avoid
           a price spike — this is where the trap closes.
"""

import time
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger("SML.E2.Settlement")

# ── NYSE Holiday Calendar 2024-2027 ──────────────────────────────────────────
_NYSE_HOLIDAYS: set = {
    # 2024
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29),
    date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2),
    date(2024, 11, 28), date(2024, 12, 25),
    # 2025
    date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
    date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _NYSE_HOLIDAYS


def _add_trading_days(start: date, n: int) -> date:
    """Add n trading days, skipping weekends and NYSE holidays."""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if _is_trading_day(d):
            added += 1
    return d


def _trading_days_between(a: date, b: date) -> int:
    """Count trading days from a (exclusive) to b (inclusive)."""
    if b <= a:
        return 0
    d, count = a, 0
    while d < b:
        d += timedelta(days=1)
        if _is_trading_day(d):
            count += 1
    return count


# ── In-memory ignition store ─────────────────────────────────────────────────
# One clock per symbol. Cleared after C+35 window expires.
_ignitions: dict = {}
_CLOCK_TTL_SECS = 36 * 86400   # auto-expire after 36 days


def stamp_ignition(symbol: str, ts: Optional[float] = None) -> dict:
    """
    Stamp T+0 for a symbol. Called automatically by the Convergence Engine
    when Engine 3 fires (volume crossing 123/321) + Engine 1 suppressed.
    Idempotent — returns existing clock if already active.
    """
    symbol = symbol.upper()
    existing = _ignitions.get(symbol)
    if existing and (time.time() - existing["ts"]) < _CLOCK_TTL_SECS:
        return get_clock(symbol)

    ts    = ts or time.time()
    t0    = date.fromtimestamp(ts)
    t13   = _add_trading_days(t0, 13)
    c35   = t0 + timedelta(days=35)

    _ignitions[symbol] = {
        "ts":       ts,
        "t0":       t0.isoformat(),
        "t13":      t13.isoformat(),
        "c35":      c35.isoformat(),
    }
    logger.info(f"[E2] {symbol} — T+0 stamped {t0} | T+13={t13} | C+35={c35}")
    return get_clock(symbol)


def get_clock(symbol: str) -> dict:
    """Return live countdown state for a symbol."""
    symbol = symbol.upper()
    entry  = _ignitions.get(symbol)

    if not entry:
        return {"engine": 2, "symbol": symbol, "status": "NO_IGNITION", "in_kill_zone": False}

    if time.time() - entry["ts"] > _CLOCK_TTL_SECS:
        _ignitions.pop(symbol, None)
        return {"engine": 2, "symbol": symbol, "status": "EXPIRED", "in_kill_zone": False}

    today = date.today()
    t0    = date.fromisoformat(entry["t0"])
    t13   = date.fromisoformat(entry["t13"])
    c35   = date.fromisoformat(entry["c35"])

    t13_td_left  = max(0, _trading_days_between(today, t13))
    c35_cal_left = max(0, (c35 - today).days)

    t13_kill     = 0 <= t13_td_left <= 3
    c35_kill     = 0 <= c35_cal_left <= 3
    in_kill_zone = t13_kill or c35_kill

    if today > c35 and today > t13:
        status = "WINDOW_CLOSED"
    elif in_kill_zone:
        status = "KILL_ZONE"
    else:
        status = "COUNTING"

    return {
        "engine":                2,
        "name":                  "FTD Settlement Clock",
        "symbol":                symbol,
        "status":                status,
        "in_kill_zone":          in_kill_zone,
        "t0_ignition":           entry["t0"],
        "t13_target":            entry["t13"],
        "c35_target":            entry["c35"],
        "t13_trading_days_left": t13_td_left,
        "c35_calendar_days_left": c35_cal_left,
        "t13_kill_zone":         t13_kill,
        "c35_kill_zone":         c35_kill,
        "score_contrib":         25 if in_kill_zone else 5 if status == "COUNTING" else 0,
    }


def get_all_active() -> list:
    """Return all symbols with active ignition clocks, sorted by urgency."""
    result = []
    for sym in list(_ignitions.keys()):
        c = get_clock(sym)
        if c.get("status") not in ("NO_IGNITION", "EXPIRED", "WINDOW_CLOSED"):
            result.append(c)
    return sorted(result, key=lambda x: x.get("c35_calendar_days_left", 999))
