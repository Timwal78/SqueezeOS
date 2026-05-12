"""
SML Alignment Hub — FTD Monitor
Fetches SEC Fail-to-Deliver data via FMP and computes T+35 settlement clusters.
"""

import json
import os
import time
import datetime
import requests
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

# ─── FTD Fetch ───────────────────────────────────────────────────────────────

def fetch_ftd_data(ticker: str, api_key: str, limit: int = 60) -> list[dict]:
    """
    Fetches FTD records for a given ticker from Financial Modeling Prep.
    Returns a list of FTD records sorted by date descending.
    """
    url = (
        f"https://api.financialmodelingprep.com/api/v4/fail_to_deliver"
        f"?symbol={ticker}&apikey={api_key}&limit={limit}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        print(f"[FTD] Unexpected response format: {data}")
        return []
    except Exception as e:
        print(f"[FTD] Error fetching {ticker}: {e}")
        return []

# ─── T+35 Math ───────────────────────────────────────────────────────────────

def compute_t35(ftd_date_str: str) -> datetime.date:
    """Given an FTD date string (YYYY-MM-DD), returns the T+35 settlement date."""
    ftd = datetime.date.fromisoformat(ftd_date_str)
    return ftd + datetime.timedelta(days=35)

def detect_clusters(ftd_records: list[dict], window_days: int = 3) -> list[dict]:
    """
    Identifies FTD dates whose T+35 settlement window overlaps with today ± window_days.
    Returns a list of cluster events.
    """
    today = datetime.date.today()
    clusters = []

    for rec in ftd_records:
        raw_date = rec.get("date") or rec.get("settlementDate") or rec.get("failDate")
        if not raw_date:
            continue
        try:
            t35 = compute_t35(raw_date[:10])
            delta = (t35 - today).days
            if abs(delta) <= window_days:
                quantity = rec.get("quantity") or rec.get("failQuantity") or 0
                clusters.append({
                    "ftd_date": raw_date[:10],
                    "t35_date": t35.isoformat(),
                    "days_out": delta,
                    "quantity": quantity,
                    "status": (
                        "SETTLEMENT_DAY" if delta == 0
                        else f"T+35 IN {delta}d" if delta > 0
                        else f"{abs(delta)}d OVERDUE"
                    )
                })
        except Exception as e:
            print(f"[FTD] Date parse error for '{raw_date}': {e}")

    clusters.sort(key=lambda x: x["days_out"])
    return clusters

# ─── 666-Day Cycle Check ─────────────────────────────────────────────────────

ANCHOR_DATE = datetime.date(2020, 10, 14)  # GME/AMC ignition anchor

def check_cycle():
    today = datetime.date.today()
    days = (today - ANCHOR_DATE).days
    cycle_num = days // 666
    remainder = days % 666
    next_days = 666 - remainder
    next_date = today + datetime.timedelta(days=next_days)
    return {
        "total_days": days,
        "cycle_number": cycle_num,
        "remainder": remainder,
        "status": "IGNITION" if remainder == 0 else "COILING",
        "days_to_ignition": next_days,
        "next_ignition_date": next_date.isoformat()
    }

# ─── Julian Offset ───────────────────────────────────────────────────────────

def get_julian_date(gregorian: datetime.date = None) -> datetime.date:
    if gregorian is None:
        gregorian = datetime.date.today()
    return gregorian - datetime.timedelta(days=13)

# ─── Pre-Market Window ────────────────────────────────────────────────────────

def is_premarket_window() -> bool:
    """Returns True if current ET time is 4:00–5:30 AM (pre-market news window)."""
    import zoneinfo
    et = datetime.datetime.now(tz=zoneinfo.ZoneInfo("America/New_York"))
    total_min = et.hour * 60 + et.minute
    return 240 <= total_min <= 330

# ─── Main Monitor Loop ────────────────────────────────────────────────────────

def run_monitor(tickers: list[str] = None, interval_seconds: int = 300):
    """
    Runs the FTD monitor in a loop. Polls every `interval_seconds`.
    Prints cluster alerts and beast mode status.
    """
    config = load_config()
    api_key = config.get("fmp_api_key", "")
    if not api_key:
        print("[ERROR] No FMP API key found in config.json")
        return

    tickers = tickers or config.get("tickers", ["GME", "AMC"])

    print(f"\n{'='*60}")
    print("  SML ALIGNMENT HUB — FTD Monitor ONLINE")
    print(f"  Tickers : {', '.join(tickers)}")
    print(f"  Interval: {interval_seconds}s")
    print(f"  Anchor  : {ANCHOR_DATE.isoformat()}")
    print(f"{'='*60}\n")

    while True:
        now = datetime.datetime.now()
        today = datetime.date.today()
        julian = get_julian_date(today)
        cycle = check_cycle()
        premarket = is_premarket_window()

        print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] ── SCAN ──")
        print(f"  Gregorian : {today.isoformat()}")
        print(f"  Julian    : {julian.isoformat()} (−13 days)")
        print(f"  666-Cycle : {cycle['status']} | Day {cycle['total_days']} | "
              f"Cycle #{cycle['cycle_number']} | "
              f"Next ignition in {cycle['days_to_ignition']}d ({cycle['next_ignition_date']})")
        print(f"  Pre-Market: {'⚡ ACTIVE (4AM WINDOW)' if premarket else 'closed'}")

        any_cluster = False
        for ticker in tickers:
            records = fetch_ftd_data(ticker, api_key)
            clusters = detect_clusters(records, window_days=3)
            if clusters:
                any_cluster = True
                print(f"\n  ⚠️  T+35 CLUSTER — {ticker} ({len(clusters)} event(s))")
                for c in clusters:
                    print(f"      FTD {c['ftd_date']} → T+35 {c['t35_date']} | "
                          f"{c['status']} | qty={c['quantity']:,}")
            else:
                print(f"  [{ticker}] No T+35 cluster in ±3-day window")

        # Beast mode status
        beast = "ENGAGED" if (cycle["status"] == "IGNITION" or any_cluster) else "MONITORING"
        print(f"\n  BEAST MODE: {beast}")
        print(f"{'─'*60}")

        # Write state to JSON for dashboard
        state = {
            "timestamp": now.isoformat(),
            "gregorian": today.isoformat(),
            "julian": julian.isoformat(),
            "cycle": cycle,
            "premarket": premarket,
            "beast_mode": beast,
            "tickers": {}
        }
        for ticker in tickers:
            records = fetch_ftd_data(ticker, api_key)
            state["tickers"][ticker] = detect_clusters(records, 3)

        state_path = Path(__file__).parent / "ftd_state.json"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        time.sleep(interval_seconds)

# ─── Entry ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_monitor()
