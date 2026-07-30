"""
Post-Earnings-Announcement Drift (PEAD) Backtest — real data only.
=====================================================================
PEAD is one of the most robustly published anomalies in finance (Bernard &
Thomas 1989, replicated for decades): stocks that beat earnings estimates
tend to keep drifting up for weeks after the initial reaction, and misses
tend to keep drifting down. Unlike the chart-pattern engines tested earlier
this session (TTM Squeeze, CVD Regime, DRUCK, etc.), this has real academic
literature behind it, not just a scanner's marketing claim.

Data: real EPS estimate/actual + report date/timing (get_earnings_results,
Robinhood MCP) and real daily bars (get_equity_historicals, same channel),
15 real liquid large caps, reported quarters since late 2024/early 2025 --
98 real earnings events. No synthetic/fabricated data anywhere in this file.

Method: for each REPORTED quarter (actual EPS not null), the entry is the
CLOSE of the first trading day the market could react (report date itself
if reported before-market "am", the next trading day if reported after-
market "pm") -- this deliberately measures DRIFT after the initial reaction
is already priced in, not the initial jump itself, matching how PEAD is
studied academically. Exit is N trading days later (default 30). Events
without enough real forward bars yet (too recent) are excluded, not
padded or estimated.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def load_bars(path: str) -> dict:
    with open(path) as f:
        d = json.load(f)
    out = {}
    for r in d["data"]["results"]:
        bars = [{"date": b["begins_at"], "close": float(b["close_price"])} for b in r["bars"]]
        out[r["symbol"]] = bars
    return out


def load_earnings(events: list) -> list:
    """events: list of (symbol, [raw get_earnings_results entries])."""
    out = []
    for symbol, entries in events:
        for e in entries:
            if e["eps"]["actual"] is None:
                continue
            est, act = float(e["eps"]["estimate"]), float(e["eps"]["actual"])
            surprise = (act - est) / abs(est) * 100.0 if est != 0 else None
            if surprise is None:
                continue
            out.append({
                "symbol": symbol, "date": e["report"]["date"],
                "timing": e["report"]["timing"], "surprise_pct": surprise,
            })
    return out


def find_entry_index(bar_dates: list, report_date: str, timing: str) -> int:
    """First trading-day index the market could react: the report day itself
    for 'am' (before-market) reports, the NEXT trading day for 'pm'
    (after-market) reports. Returns -1 if not found in range."""
    for i, d in enumerate(bar_dates):
        if d >= report_date:
            if timing == "am":
                return i
            return i + 1 if i + 1 < len(bar_dates) else -1
    return -1


def run(bars_by_symbol: dict, earnings_events: list, drift_days: int = 30) -> dict:
    beats, misses = [], []
    skipped_too_recent = 0

    for ev in earnings_events:
        sym = ev["symbol"]
        bars = bars_by_symbol.get(sym)
        if not bars:
            continue
        bar_dates = [b["date"][:10] for b in bars]
        entry_i = find_entry_index(bar_dates, ev["date"], ev["timing"])
        if entry_i < 0:
            continue
        exit_i = entry_i + drift_days
        if exit_i >= len(bars):
            skipped_too_recent += 1
            continue
        entry_px = bars[entry_i]["close"]
        exit_px = bars[exit_i]["close"]
        drift_pct = (exit_px - entry_px) / entry_px * 100.0
        record = {"symbol": sym, "date": ev["date"], "surprise_pct": ev["surprise_pct"], "drift_pct": drift_pct}
        (beats if ev["surprise_pct"] > 0 else misses).append(record)

    def stats(group):
        n = len(group)
        if n == 0:
            return {"n": 0, "avg_drift": 0.0, "win_rate": 0.0}
        avg = sum(g["drift_pct"] for g in group) / n
        wins = sum(1 for g in group if g["drift_pct"] > 0)
        return {"n": n, "avg_drift": avg, "win_rate": wins / n * 100}

    return {"beats": stats(beats), "misses": misses and stats(misses),
            "skipped_too_recent": skipped_too_recent,
            "beat_records": beats, "miss_records": misses}


if __name__ == "__main__":
    bars_path1, bars_path2, earnings_json_path, drift_days = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    bars_by_symbol = {**load_bars(bars_path1), **load_bars(bars_path2)}
    with open(earnings_json_path) as f:
        raw_events = json.load(f)
    earnings_events = load_earnings([(sym, entries) for sym, entries in raw_events.items()])

    out = run(bars_by_symbol, earnings_events, drift_days=drift_days)
    b, m = out["beats"], out["misses"]
    print(f"drift window: {drift_days} trading days post-reaction")
    print(f"BEATS (surprise > 0): n={b['n']}, avg_drift={b['avg_drift']:.3f}%, win_rate={b['win_rate']:.1f}%")
    if m:
        print(f"MISSES (surprise <= 0): n={m['n']}, avg_drift={m['avg_drift']:.3f}%, win_rate={m['win_rate']:.1f}%")
    print(f"skipped (too recent, no {drift_days}-day forward window yet): {out['skipped_too_recent']}")
