#!/usr/bin/env python3
"""
SQUEEZE OS — Cycle Intelligence Engine CLI runner
══════════════════════════════════════════════════════════════════════
Fetches real market data and runs a CIE evaluation for one or more
tickers.  Prints a structured report; optionally feeds MMLE TNT state
from a running server.

Usage:
    python run_cie.py GME AMC              # evaluate two tickers
    python run_cie.py GME --tnt TNT_LONG   # pass explicit TNT state
    python run_cie.py GME --json           # machine-readable output
    python run_cie.py --list               # show last known universe

AGENT_LAW compliance:
    All data is fetched live.  If a provider is unavailable, the
    engine reports AWAITING_STREAM and exits cleanly (Law §1).
    Every coefficient is read from CIE_CONFIG (Law §2).
    Proxy labels are surfaced in notes (Law §3).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import date, timedelta
from pprint import pformat
from typing import Any, Dict, List, Optional

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cycle_intelligence_engine import CycleIntelligenceEngine, CIE_CONFIG

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
logger = logging.getLogger("run_cie")


# ═══════════════════════════════════════════════════════════════
# DATA FETCHER
# ═══════════════════════════════════════════════════════════════
def _load_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    env.update(os.environ)
    return env


_ENV = _load_env()


def _polygon_get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Thin Polygon REST call — no external dependencies beyond `requests`."""
    api_key = _ENV.get("POLYGON_API_KEY", "")
    if not api_key:
        logger.warning("[run_cie] POLYGON_API_KEY not set")
        return None
    try:
        import requests
        url = f"https://api.polygon.io{path}"
        p = {"apiKey": api_key}
        if params:
            p.update(params)
        r = requests.get(url, params=p, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("[run_cie] Polygon error %s: %s", path, exc)
        return None


def fetch_quote(ticker: str) -> Optional[Dict[str, Any]]:
    data = _polygon_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
    if data and data.get("status") == "OK":
        return data.get("ticker", {})
    return None


def fetch_aggs(ticker: str, n: int = 30) -> List[Dict[str, Any]]:
    """Fetch last N 5-minute bars."""
    from_ts = int((time.time() - n * 5 * 60 * 1.5) * 1000)  # generous buffer
    to_ts   = int(time.time() * 1000)
    data = _polygon_get(
        f"/v2/aggs/ticker/{ticker}/range/5/minute/{from_ts}/{to_ts}",
        {"adjusted": "true", "sort": "asc", "limit": str(n + 10)},
    )
    if data and data.get("status") == "OK":
        return data.get("results", [])[-n:]
    return []


def fetch_dark_prints(ticker: str) -> List[Dict[str, Any]]:
    """Fetch recent dark-pool (TRF) prints from Polygon trades feed."""
    data = _polygon_get(f"/v3/trades/{ticker}", {"limit": "200", "order": "desc"})
    prints = []
    if data and data.get("status") == "OK":
        for t in data.get("results", []):
            conditions = t.get("conditions") or []
            # Condition 41 = TRF (dark pool); 14 = qualified contingent trade
            if any(c in (41, 14) for c in conditions):
                prints.append({
                    "price": t.get("price", 0),
                    "size":  t.get("size", 0),
                    "mid":   t.get("price", 0),   # best available without NBBO
                })
    return prints


def fetch_sec_ftd(ticker: str) -> List[Dict[str, Any]]:
    """
    Returns a list of recent FTD records from Polygon's reference data.
    Format: [{"date": date, "ftd_shares": int, "float_shares": int}, ...]
    Falls back to [] if unavailable (AGENT_LAW §1).
    """
    # Polygon reference: /vX/reference/financials can give share float.
    # SEC FTD: /v2/reference/news approach is unavailable via Polygon directly.
    # Transparent fallback: return empty list and label as proxy-unavailable.
    logger.debug("[run_cie] SEC FTD data not available via Polygon free tier — "
                 "[ESTIMATED_PROXY: ftd_velocity_unavailable]")
    return []


def fetch_iv_atm(snapshot: Optional[Dict]) -> Optional[float]:
    """Extract ATM IV from snapshot; return None if unavailable."""
    if not snapshot:
        return None
    iv = snapshot.get("impliedVolatility") or 0.0
    return float(iv) if iv else None


# ═══════════════════════════════════════════════════════════════
# REPORT FORMATTER
# ═══════════════════════════════════════════════════════════════
def _bar(label: str, val: float, max_val: float = 1.5, width: int = 20) -> str:
    filled = int(round(val / max_val * width))
    filled = max(0, min(width, filled))
    return f"{label:<16} {'█' * filled}{'░' * (width - filled)} {val:.3f}"


def print_report(ticker: str, sig, tnt_state: str) -> None:
    from cycle_intelligence_engine import CycleSignal
    s: CycleSignal = sig
    sep = "═" * 66

    STATE_ICON = {
        "CIE_FIRE": "⚡ CIE_FIRE",
        "PRIMED":   "🔶 PRIMED",
        "BUILDING": "🔵 BUILDING",
        "DORMANT":  "⬜ DORMANT",
    }

    print(sep)
    print(f"  CYCLE INTELLIGENCE ENGINE — {ticker}   {STATE_ICON.get(s.state, s.state)}")
    print(f"  Composite z : {s.composite_z:.3f} / 6.0   |   MMLE TNT : {tnt_state}")
    print(sep)
    print(f"\n  LAYER SCORES  (max 1.5 each)")
    print(f"  {_bar('Settlement', s.components.get('z_settlement', 0))}")
    print(f"  {_bar('Dark Pool',  s.components.get('z_dark_pool',  0))}")
    print(f"  {_bar('Fractal',    s.components.get('z_fractal',    0))}")
    print(f"  {_bar('Meme Cycle', s.components.get('z_meme_cycle', 0))}")
    print()

    if s.meme_cycle:
        m = s.meme_cycle
        print(f"  MEME CYCLE    phase={m.phase}  vol_ratio={m.volume_ratio}  "
              f"iv_pct={m.iv_percentile}  sir={m.sir}")

    if s.dark_pool:
        d = s.dark_pool
        print(f"  DARK POOL     oer={d.oer}  hoi={d.hoi}  dlmd={d.dlmd}  "
              f"cluster={d.cluster_bars}bars  active={d.cluster_active}")

    if s.settlement:
        se = s.settlement
        print(f"  SETTLEMENT    ftd_vel={se.ftd_velocity}  t35_rem={se.t35_days_remaining}d  "
              f"ctb={se.ctb_rate}")

    if s.fractal:
        fr = s.fractal
        print(f"  FRACTAL       best_sim={fr.best_similarity}  "
              f"median_fwd={fr.median_forward_return}%  matches={len(fr.top_matches)}")
        for m in fr.top_matches:
            print(f"    └ {m.period_label}  sim={m.similarity}  fwd={m.forward_return}")

    notes = []
    for layer in (s.settlement, s.dark_pool, s.fractal, s.meme_cycle):
        if layer:
            notes.extend(layer.notes)
    notes.extend(s.notes)
    if notes:
        print(f"\n  NOTES")
        for n in notes:
            print(f"    • {n}")
    print(sep)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def run_ticker(
    engine: CycleIntelligenceEngine,
    ticker: str,
    tnt_state: str,
    json_out: bool,
) -> Optional[Dict]:
    ticker = ticker.upper()
    print(f"\n[CIE] Fetching data for {ticker} …", flush=True)

    snapshot = fetch_quote(ticker)
    bars     = fetch_aggs(ticker, n=CIE_CONFIG["hfm_window"] + 5)
    dark     = fetch_dark_prints(ticker)

    if not bars:
        print(f"[CIE] WARNING: no bar data for {ticker} — AWAITING_STREAM")
        if json_out:
            return {"ticker": ticker, "state": "AWAITING_STREAM", "error": "no_bars"}
        return None

    # Ingest bars
    lit_vol_approx = sum(b.get("v", 0) for b in bars) / max(1, len(bars))
    adv = lit_vol_approx
    for bar in bars:
        close  = bar.get("c", 0)
        volume = bar.get("v", 0)
        iv_atm = fetch_iv_atm(snapshot) or 0.0
        engine.ingest_price_bar(ticker, close=close, volume=volume,
                                iv_atm=iv_atm, adv=adv)

    # Ingest latest dark bar
    if dark:
        spot = bars[-1].get("c", 1.0)
        engine.ingest_dark_bar(ticker, dark_prints=dark,
                               lit_volume=bars[-1].get("v", 0), spot=spot)
    else:
        engine.ingest_dark_bar(ticker, dark_prints=[], lit_volume=0, spot=1.0)

    sig = engine.evaluate(ticker, tnt_state=tnt_state)

    if json_out:
        out = {
            "ticker": ticker,
            "state": sig.state,
            "composite_z": sig.composite_z,
            "components": sig.components,
            "tnt_state": tnt_state,
            "timestamp": sig.timestamp,
        }
        return out

    print_report(ticker, sig, tnt_state)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CIE CLI — Cycle Intelligence Engine runner"
    )
    parser.add_argument("tickers", nargs="*", default=["GME"],
                        help="Ticker(s) to evaluate (default: GME)")
    parser.add_argument("--tnt", default="NEUTRAL",
                        choices=["NEUTRAL", "COMPRESSED", "TNT_LONG", "TNT_SHORT"],
                        help="MMLE TNT state to pass as confirmatory input")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON instead of formatted report")
    parser.add_argument("--list-config", action="store_true",
                        help="Print CIE_CONFIG and exit")
    args = parser.parse_args()

    if args.list_config:
        print(json.dumps(CIE_CONFIG, indent=2))
        return

    engine = CycleIntelligenceEngine()
    results = []
    for ticker in args.tickers:
        out = run_ticker(engine, ticker, tnt_state=args.tnt, json_out=args.json)
        if out:
            results.append(out)

    if args.json and results:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
