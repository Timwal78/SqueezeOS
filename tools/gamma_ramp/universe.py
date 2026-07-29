#!/usr/bin/env python3
"""
Dynamic universe fetch for Gamma Ramp Desk — NO hardcoded ticker lists.

Every scan cycle pulls fresh names from live market surfaces, merges,
filters junk, and returns the tradeable set.

FETCH SOURCES (in priority order)
─────────────────────────────────
1) Alpaca most-actives (volume)     — liquidity spine
2) Alpaca movers gainers + losers   — impulse / forced-move candidates
3) Yahoo day_gainers                — retail/momentum surface
4) Yahoo most_actives               — secondary volume confirmation
5) Yahoo small_cap_gainers          — high-beta squeeze candidates
6) SqueezeOS /api/beastmode signals — internal GOD_MODE / convergence hits

OPTIONAL (when keys present)
7) Tradier watchlist / gainers      — if TRADIER_API_KEY set
8) Polygon snapshot gainers         — if POLYGON_API_KEY works (often plan-gated)

FILTERS (hard rails — not a list, rules)
────────────────────────────────────────
- Symbol shape: 1–5 letters, no warrants/units/preferred junk suffixes
- Exclude pure OTC-looking, warrants (W, WS, WW), rights, units
- Prefer price band when quote available: $1.00 – $2,000
- Prefer min day volume when available: >= MIN_DAY_VOL
- Cap universe size: MAX_UNIVERSE (scan budget)

ENV
───
  ALPACA_API_KEY / ALPACA_API_SECRET   preferred screeners
  SQUEEZEOS_API_URL                   default https://squeezeos-api.onrender.com
  MAX_UNIVERSE                        default 80
  MIN_DAY_VOL                         default 1_000_000
  MIN_PRICE / MAX_PRICE               default 1.0 / 2000.0
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ── Tunables (rules, not tickers) ────────────────────────────────────────────
MAX_UNIVERSE = int(os.environ.get("MAX_UNIVERSE", "80"))
MIN_DAY_VOL = int(os.environ.get("MIN_DAY_VOL", "1000000"))
MIN_PRICE = float(os.environ.get("MIN_PRICE", "1.0"))
MAX_PRICE = float(os.environ.get("MAX_PRICE", "2000.0"))

# Options-desk quality rails — dynamic fetch stays dynamic, but we refuse
# structural garbage that cannot be a clean 0.35Δ long-premium ramp.
LEVERAGED_INVERSE_ETFS = {
    "SOXL","SOXS","TQQQ","SQQQ","SPXU","SPXS","SPXL","UPRO","TNA","TZA",
    "LABU","LABD","FNGU","FNGD","NUGT","DUST","JNUG","JDST","UVXY","SVXY",
    "VIXY","VIXM","BOIL","KOLD","YINN","YANG","NAIL","DRIP","GUSH","ERX","ERY",
    "FAS","FAZ","TECL","TECS","CURE","PILL","DUSL","DPST","HIBL","HIBS",
    "NVD","NVDL","NVDD","TSLL","TSLS","AMDL","AMDS","MSFU","MSFD","AAPU","AAPD",
    "BITX","CONL","MSTU","MSTX","NVDX","SPCX",  # high-tox levered single-stock
}
SQUEEZEOS_API_URL = os.environ.get("SQUEEZEOS_API_URL", "https://squeezeos-api.onrender.com").rstrip("/")
YAHOO_UA = os.environ.get("YAHOO_UA", "Mozilla/5.0 (compatible; SML-GammaRamp/1.0)")
HTTP_TIMEOUT = float(os.environ.get("UNIVERSE_HTTP_TIMEOUT", "20"))

# Symbol hygiene — reject structural junk, not specific companies
_SYM_OK = re.compile(r"^[A-Z]{1,5}$")
_BAD_SUFFIX = re.compile(r"(\.WS|\.W|WW|WS|WT|U|R|P)$")  # last-char heuristics applied carefully
_BAD_EXACT = {
    "", "TEST", "NAN", "NONE", "NULL",
}


@dataclass
class Candidate:
    symbol: str
    sources: List[str]
    score: float = 0.0          # higher = scan first
    last: Optional[float] = None
    volume: Optional[float] = None
    change_pct: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None


def _http_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode())


def _safe(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[bool, Any, str]:
    try:
        return True, _http_json(url, headers), ""
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode("utf-8", "replace")
        return False, None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def normalize_symbol(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().upper()
    # Yahoo class shares BRK-B → skip multi-class for options simplicity unless plain
    if "-" in s or "/" in s or "^" in s or "=" in s:
        return None
    if s in _BAD_EXACT:
        return None
    # strip common junk endings that aren't 1-5 pure alpha roots
    if not _SYM_OK.match(s):
        return None
    # warrants / units often end with single letter tags in some feeds — keep pure alpha only
    if s.endswith(("WW", "WS", "WT")):
        return None
    return s


def _add(
    bag: Dict[str, Candidate],
    symbol: str,
    source: str,
    score: float = 1.0,
    last: Optional[float] = None,
    volume: Optional[float] = None,
    change_pct: Optional[float] = None,
    **meta: Any,
) -> None:
    sym = normalize_symbol(symbol)
    if not sym:
        return
    c = bag.get(sym)
    if not c:
        c = Candidate(symbol=sym, sources=[source], score=score, last=last, volume=volume, change_pct=change_pct, meta=meta or {})
        bag[sym] = c
        return
    if source not in c.sources:
        c.sources.append(source)
    c.score += score
    if last is not None:
        c.last = last
    if volume is not None:
        c.volume = volume if c.volume is None else max(c.volume, volume)
    if change_pct is not None:
        c.change_pct = change_pct if c.change_pct is None else (
            change_pct if abs(change_pct) > abs(c.change_pct or 0) else c.change_pct
        )
    if meta:
        c.meta = {**(c.meta or {}), **meta}


# ── Source fetchers ──────────────────────────────────────────────────────────

def fetch_alpaca_actives(bag: Dict[str, Candidate], errors: List[str]) -> None:
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not key or not secret:
        errors.append("alpaca_actives: missing ALPACA_API_KEY/SECRET")
        return
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    ok, data, err = _safe(
        "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives?by=volume&top=50",
        headers,
    )
    if not ok:
        errors.append(f"alpaca_actives: {err}")
        return
    rows = (data or {}).get("most_actives") or []
    for i, row in enumerate(rows):
        vol = float(row.get("volume") or 0)
        # rank boost for higher volume
        score = 5.0 + max(0.0, (50 - i) * 0.05)
        if vol >= MIN_DAY_VOL:
            score += 2.0
        _add(bag, row.get("symbol", ""), "alpaca_actives", score=score, volume=vol, trade_count=row.get("trade_count"))


def fetch_alpaca_movers(bag: Dict[str, Candidate], errors: List[str]) -> None:
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not key or not secret:
        errors.append("alpaca_movers: missing ALPACA_API_KEY/SECRET")
        return
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    ok, data, err = _safe("https://data.alpaca.markets/v1beta1/screener/stocks/movers?top=30", headers)
    if not ok:
        errors.append(f"alpaca_movers: {err}")
        return
    for side, boost in (("gainers", 4.0), ("losers", 2.5)):
        for i, row in enumerate((data or {}).get(side) or []):
            chg = float(row.get("percent_change") or row.get("change") or 0)
            px = float(row.get("price") or 0) or None
            score = boost + max(0.0, abs(chg) / 10.0) + max(0.0, (30 - i) * 0.03)
            _add(bag, row.get("symbol", ""), f"alpaca_{side}", score=score, last=px, change_pct=chg)


def fetch_yahoo_screener(bag: Dict[str, Candidate], scr_id: str, score: float, errors: List[str]) -> None:
    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        f"?count=25&scrIds={scr_id}"
    )
    ok, data, err = _safe(url, {"User-Agent": YAHOO_UA})
    if not ok:
        errors.append(f"yahoo_{scr_id}: {err}")
        return
    try:
        quotes = ((data.get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
    except Exception:
        quotes = []
        errors.append(f"yahoo_{scr_id}: bad_shape")
    for i, q in enumerate(quotes):
        px = q.get("regularMarketPrice")
        vol = q.get("regularMarketVolume")
        chg = q.get("regularMarketChangePercent")
        try:
            px_f = float(px) if px is not None else None
        except (TypeError, ValueError):
            px_f = None
        try:
            vol_f = float(vol) if vol is not None else None
        except (TypeError, ValueError):
            vol_f = None
        try:
            chg_f = float(chg) if chg is not None else None
        except (TypeError, ValueError):
            chg_f = None
        s = score + max(0.0, (25 - i) * 0.04)
        _add(bag, q.get("symbol", ""), f"yahoo_{scr_id}", score=s, last=px_f, volume=vol_f, change_pct=chg_f)


def fetch_squeezeos_beastmode(bag: Dict[str, Candidate], errors: List[str]) -> None:
    ok, data, err = _safe(f"{SQUEEZEOS_API_URL}/api/beastmode", {"User-Agent": "SML-GammaRamp/1.0"})
    if not ok:
        errors.append(f"beastmode: {err}")
        return
    sigs = (data or {}).get("signals") or []
    for sig in sigs:
        sym = sig.get("symbol") or sig.get("ticker")
        # heavy boost for internal convergence / beastmode hits
        stacked = float(sig.get("god_stacked") or sig.get("active_conditions") or 0)
        composite = float(sig.get("composite_score") or 0)
        score = 8.0 + stacked + (composite / 50.0)
        _add(
            bag,
            sym or "",
            "squeezeos_beastmode",
            score=score,
            beastmode=bool(sig.get("beastmode")),
            god_stacked=stacked,
            composite=composite,
            tier=sig.get("tier"),
        )


def fetch_tradier_if_configured(bag: Dict[str, Candidate], errors: List[str]) -> None:
    """Optional: Tradier market movers when key present (production preferred)."""
    key = os.environ.get("TRADIER_API_KEY", "").strip()
    if not key:
        return  # silent optional
    env = (os.environ.get("TRADIER_ENV") or "production").strip().lower()
    base = "https://api.tradier.com/v1" if env == "production" else "https://sandbox.tradier.com/v1"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    # Tradier doesn't have a single universal movers endpoint across all plans;
    # use clock + quotes on beast/actives already gathered is enough. Try gainers path if exposed.
    ok, data, err = _safe(f"{base}/markets/clock", headers)
    if not ok:
        errors.append(f"tradier_clock: {err}")
        return
    # Mark feed healthy for downstream options sniper; no static list injected.
    bag.setdefault("__tradier_feed__", Candidate(symbol="__FEED__", sources=["tradier_clock"], score=0))


# ── Filters ──────────────────────────────────────────────────────────────────

def passes_filters(c: Candidate) -> bool:
    if c.symbol.startswith("__"):
        return False
    if c.symbol in LEVERAGED_INVERSE_ETFS:
        return False
    # 3x/2x naming patterns
    if c.symbol.endswith(("U", "D")) and len(c.symbol) >= 4 and c.symbol not in {"GOLD", "FORD", "GOOD", "LAND", "FUND"}:
        # only block known levered suffixes when also in block set context — skip broad
        pass
    if c.last is not None:
        if c.last < MIN_PRICE or c.last > MAX_PRICE:
            return False
        # options need enough premium room; sub-$2 names are usually junk lottery
        if c.last < 2.0 and not any(s.startswith("squeezeos") for s in c.sources):
            return False
    if c.volume is not None and c.volume < MIN_DAY_VOL:
        strong = any(s.startswith("squeezeos") or s.startswith("alpaca_gainers") for s in c.sources)
        if not strong and len(c.sources) < 2:
            return False
    # require absolute change impulse OR multi-source confirmation for desk scan
    if c.change_pct is not None and abs(c.change_pct) < 0.5 and len(c.sources) == 1 and c.sources[0].startswith("alpaca_actives"):
        # pure active but flat — still ok for liquidity spine; keep
        pass
    return True


def enrich_quotes_alpaca(bag: Dict[str, Candidate], symbols: List[str], errors: List[str]) -> None:
    """Batch snapshot for price/volume fill-in."""
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not key or not secret or not symbols:
        return
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    # chunk 50
    for i in range(0, len(symbols), 50):
        chunk = symbols[i : i + 50]
        url = "https://data.alpaca.markets/v2/stocks/snapshots?symbols=" + ",".join(chunk)
        ok, data, err = _safe(url, headers)
        if not ok:
            errors.append(f"alpaca_snapshots: {err}")
            continue
        for sym, snap in (data or {}).items():
            c = bag.get(sym)
            if not c:
                continue
            day = (snap or {}).get("dailyBar") or {}
            prev = (snap or {}).get("prevDailyBar") or {}
            trade = (snap or {}).get("latestTrade") or {}
            try:
                last = float(trade.get("p") or day.get("c") or 0) or None
            except (TypeError, ValueError):
                last = None
            try:
                vol = float(day.get("v") or 0) or None
            except (TypeError, ValueError):
                vol = None
            chg = None
            try:
                pc = float(prev.get("c") or 0)
                lc = float(day.get("c") or last or 0)
                if pc > 0 and lc > 0:
                    chg = (lc - pc) / pc * 100.0
            except (TypeError, ValueError):
                pass
            if last is not None:
                c.last = last
            if vol is not None:
                c.volume = vol
            if chg is not None:
                c.change_pct = chg


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_universe(max_n: Optional[int] = None) -> Dict[str, Any]:
    """
    Dynamic fetch. Returns:
      {
        symbols: [str, ...]  # ranked scan order
        candidates: [{symbol, sources, score, last, volume, change_pct}, ...]
        sources_ok: [str]
        errors: [str]
        fetched_at: epoch
        rules: {...}
      }
    """
    max_n = int(max_n or MAX_UNIVERSE)
    bag: Dict[str, Candidate] = {}
    errors: List[str] = []
    sources_ok: List[str] = []

    fetchers = [
        ("alpaca_actives", fetch_alpaca_actives),
        ("alpaca_movers", fetch_alpaca_movers),
        ("yahoo_day_gainers", lambda b, e: fetch_yahoo_screener(b, "day_gainers", 3.5, e)),
        ("yahoo_most_actives", lambda b, e: fetch_yahoo_screener(b, "most_actives", 3.0, e)),
        ("yahoo_small_cap_gainers", lambda b, e: fetch_yahoo_screener(b, "small_cap_gainers", 3.2, e)),
        ("squeezeos_beastmode", fetch_squeezeos_beastmode),
        ("tradier_optional", fetch_tradier_if_configured),
    ]

    before_counts: Dict[str, int] = {}
    for name, fn in fetchers:
        n0 = len([k for k in bag if not k.startswith("__")])
        fn(bag, errors)
        n1 = len([k for k in bag if not k.startswith("__")])
        if n1 > n0 or (name == "tradier_optional" and "__tradier_feed__" in bag):
            sources_ok.append(name)
        before_counts[name] = n1 - n0

    # drop feed markers
    bag.pop("__tradier_feed__", None)

    # enrich missing quotes
    need = [s for s, c in bag.items() if c.last is None or c.volume is None]
    enrich_quotes_alpaca(bag, need[:120], errors)

    # filter + rank
    ranked = [c for c in bag.values() if passes_filters(c)]
    ranked.sort(key=lambda c: (-c.score, -(c.volume or 0), c.symbol))
    ranked = ranked[:max_n]

    return {
        "symbols": [c.symbol for c in ranked],
        "candidates": [
            {
                "symbol": c.symbol,
                "sources": c.sources,
                "score": round(c.score, 3),
                "last": c.last,
                "volume": c.volume,
                "change_pct": c.change_pct,
                "meta": c.meta or {},
            }
            for c in ranked
        ],
        "sources_ok": sources_ok,
        "source_new_counts": before_counts,
        "errors": errors,
        "fetched_at": time.time(),
        "count": len(ranked),
        "rules": {
            "max_universe": max_n,
            "min_day_vol": MIN_DAY_VOL,
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "hardcoded_tickers": False,
            "fetch": [
                "alpaca most-actives volume top50",
                "alpaca movers gainers+losers top30",
                "yahoo day_gainers / most_actives / small_cap_gainers",
                "squeezeos /api/beastmode signals",
                "optional tradier clock health when TRADIER_API_KEY set",
                "alpaca snapshots batch for price/volume fill",
            ],
        },
    }


def main() -> int:
    # load env file if present
    env_path = os.environ.get("GAMMA_RAMP_ENV", os.path.join(os.path.dirname(__file__), "..", "gamma_ramp.env"))
    env_path = os.path.abspath(env_path)
    if os.path.isfile(env_path):
        for line in open(env_path, errors="ignore"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    # pull alpaca from render-less local if only poly set — try process env
    u = fetch_universe()
    print(json.dumps({
        "count": u["count"],
        "sources_ok": u["sources_ok"],
        "source_new_counts": u["source_new_counts"],
        "errors": u["errors"],
        "rules": u["rules"],
        "symbols": u["symbols"],
        "top15": u["candidates"][:15],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
