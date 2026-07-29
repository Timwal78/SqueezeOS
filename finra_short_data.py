"""
FINRA Daily Short Sale Volume — real, free, official regulatory data.
======================================================================
Source: https://cdn.finra.org/equity/regsho/daily/{GROUP}shvol{YYYYMMDD}.txt
FINRA publishes this file every trading day, no login/API key required —
it's the same public feed every free "short volume" tracker site
(chartexchange, wsj's short-interest widgets, etc.) republishes. Format is
pipe-delimited: "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"
— confirmed against FINRA's own published file-layout documentation.

Group "CNMS" (Consolidated NMS — FINRA/Nasdaq TRF Carteret) is used here;
it's the standard consolidated tape most public short-volume trackers use,
covering the large majority of off-exchange NMS Tier 1/2 volume.

IMPORTANT — WHAT THIS IS AND IS NOT:
  This is SHORT VOLUME (shares sold short on a given day), NOT SHORT
  INTEREST (total shares currently held short, outstanding). A high
  short-volume ratio (ShortVolume / TotalVolume) means a lot of THAT DAY's
  trading was executed via a short sale — which includes ordinary
  market-maker/HFT short selling required for liquidity provision, not
  just directional bearish conviction. It is a real, legitimate, free
  proxy for shorting *pressure*, and this module never claims it's
  anything more than that.

  The classic "short squeeze fuel" number everyone actually means —
  Short Interest as % of Float, Days-to-Cover, and real-time
  Cost-to-Borrow / Utilization Rate — is NOT available from any free,
  no-account public source at the fidelity needed here. FINRA's true
  bi-monthly short-interest-in-shares report is distributed through the
  exchanges and, at usable granularity, generally requires a paid data
  provider (Ortex, S3 Partners, Fintel) or a live IBKR TWS connection for
  borrow fee/utilization. None of those exist in this codebase. This gap
  is disclosed, not papered over — same convention as CIE's unfed
  dark-pool axis and Gamma Pin's no-backtest-evidence disclosure.

NETWORK NOTE: this sandbox's egress policy blocks cdn.finra.org (confirmed
2026-07-29, same 403-at-proxy pattern already documented for
api.tradier.com/sec.gov/nasdaqtrader.com elsewhere in this codebase) — so
the live fetch path here could not be verified end-to-end from this
environment. The URL pattern and file format are drawn from FINRA's own
published documentation and match what public short-volume trackers
report, and the parser is defensive (tolerates header variants, skips
malformed lines) — but this should be confirmed against a real response
once running somewhere with real network access (e.g. Render), the same
caveat already flagged for the Solidity compiler in the x402 Settlement
Router section of CLAUDE.md.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger("FINRA-SHORT-VOL")

FINRA_GROUP = os.environ.get("FINRA_SHORT_VOL_GROUP", "CNMS")
FINRA_BASE_URL = "https://cdn.finra.org/equity/regsho/daily"
FINRA_HDRS = {"User-Agent": "SqueezeOS/1.0 (research; contact via scriptmasterlabs.com)"}
WINDOW_DAYS = int(os.environ.get("FINRA_SHORT_VOL_WINDOW_DAYS", "60"))
REFRESH_INTERVAL_S = int(os.environ.get("FINRA_SHORT_VOL_REFRESH_INTERVAL_S", str(6 * 3600)))
BACKFILL_DAYS = int(os.environ.get("FINRA_SHORT_VOL_BACKFILL_DAYS", "10"))


@dataclass(frozen=True)
class ShortVolRecord:
    trade_date: date
    symbol: str
    short_volume: int
    short_exempt_volume: int
    total_volume: int

    @property
    def short_volume_ratio(self) -> float:
        if self.total_volume <= 0:
            return 0.0
        return self.short_volume / self.total_volume

    def as_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "symbol": self.symbol,
            "short_volume": self.short_volume,
            "short_exempt_volume": self.short_exempt_volume,
            "total_volume": self.total_volume,
            "short_volume_ratio": round(self.short_volume_ratio, 4),
        }


def _file_url(d: date) -> str:
    return f"{FINRA_BASE_URL}/{FINRA_GROUP}shvol{d.strftime('%Y%m%d')}.txt"


def _parse_short_vol_txt(raw_bytes: bytes, expected_date: Optional[date] = None) -> List[ShortVolRecord]:
    """
    Defensive parser for FINRA's pipe-delimited daily short volume file.
    Header row: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
    Tolerates a missing/reordered header by falling back to positional
    columns, and skips any line that doesn't parse cleanly rather than
    raising — a malformed row must never take down the whole file.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    header = [h.strip().lower() for h in lines[0].split("|")]
    col_idx = {name: i for i, name in enumerate(header)}
    # Fallback to the documented positional layout if headers look unrecognized
    if "symbol" not in col_idx or "shortvolume" not in col_idx:
        col_idx = {"date": 0, "symbol": 1, "shortvolume": 2, "shortexemptvolume": 3, "totalvolume": 4}
        body = lines
    else:
        body = lines[1:]

    records: List[ShortVolRecord] = []
    for ln in body:
        parts = ln.split("|")
        try:
            date_raw = parts[col_idx.get("date", 0)].strip()
            if expected_date is not None:
                d = expected_date
            elif len(date_raw) == 8 and date_raw.isdigit():
                d = date(int(date_raw[:4]), int(date_raw[4:6]), int(date_raw[6:8]))
            else:
                d = date.fromisoformat(date_raw)
            symbol = parts[col_idx["symbol"]].strip().upper()
            if not symbol:
                continue
            short_vol = int(float(parts[col_idx["shortvolume"]].strip() or 0))
            short_exempt = int(float(parts[col_idx.get("shortexemptvolume", -1)].strip() or 0)) \
                if col_idx.get("shortexemptvolume", -1) >= 0 and len(parts) > col_idx["shortexemptvolume"] else 0
            total_vol = int(float(parts[col_idx["totalvolume"]].strip() or 0))
        except (ValueError, IndexError, KeyError):
            continue
        records.append(ShortVolRecord(
            trade_date=d, symbol=symbol,
            short_volume=short_vol, short_exempt_volume=short_exempt, total_volume=total_vol,
        ))
    return records


class ShortVolumeStore:
    """Thread-safe in-memory store, same shape/convention as core/ftd_data.py's FTDDataStore."""

    def __init__(self):
        self._lock = threading.RLock()
        self._by_symbol: Dict[str, "deque[ShortVolRecord]"] = defaultdict(lambda: deque(maxlen=WINDOW_DAYS))
        self._loaded_dates: set = set()
        self._last_refresh: float = 0.0
        self._available: bool = False

    def status(self) -> dict:
        with self._lock:
            return {
                "available": self._available,
                "symbols_tracked": len(self._by_symbol),
                "days_loaded": len(self._loaded_dates),
                "last_refresh_ts": self._last_refresh,
                "window_days": WINDOW_DAYS,
                "source": f"FINRA {FINRA_GROUP} daily short volume (free, public, official)",
            }

    def series_for(self, symbol: str, limit: int = 30) -> List[ShortVolRecord]:
        symbol = symbol.upper().strip()
        with self._lock:
            return list(self._by_symbol.get(symbol, ()))[-limit:]

    def latest(self, symbol: str) -> Optional[dict]:
        recs = self.series_for(symbol, limit=WINDOW_DAYS)
        if not recs:
            return None
        latest = recs[-1]
        ratios = [r.short_volume_ratio for r in recs]
        avg_ratio = sum(ratios) / len(ratios)
        return {
            "symbol": symbol.upper(),
            "latest": latest.as_dict(),
            "window_days": len(recs),
            "window_avg_short_volume_ratio": round(avg_ratio, 4),
            "ratio_vs_window_avg": round(latest.short_volume_ratio - avg_ratio, 4),
            "note": (
                "short_volume_ratio is shares sold short / total volume for ONE trading "
                "day -- a proxy for that day's shorting pressure, not short-interest-as-"
                "%-of-float. See module docstring for the distinction."
            ),
        }

    def _add_record(self, rec: ShortVolRecord) -> None:
        with self._lock:
            series = self._by_symbol[rec.symbol]
            if series and series[-1].trade_date == rec.trade_date:
                return
            series.append(rec)
            self._available = True


_STORE = ShortVolumeStore()


def get_store() -> ShortVolumeStore:
    return _STORE


def _trading_days_back(n: int) -> List[date]:
    """Last n weekday dates ending today (a cheap NYSE-holiday-agnostic
    approximation -- a request for a holiday's file just 404s and is
    skipped, same as a weekend would)."""
    out = []
    d = date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def _fetch_one_day(d: date) -> int:
    """Fetch + ingest one day's file. Returns record count ingested (0 on any failure)."""
    key = d.isoformat()
    if key in _STORE._loaded_dates:
        return 0
    url = _file_url(d)
    try:
        req = urllib.request.Request(url, headers=FINRA_HDRS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as e:
        logger.debug("[FINRA-SHORT-VOL] %s fetch failed (weekend/holiday/unavailable?): %s", key, e)
        return 0
    recs = _parse_short_vol_txt(raw, expected_date=d)
    for r in recs:
        _STORE._add_record(r)
    _STORE._loaded_dates.add(key)
    if recs:
        logger.info("[FINRA-SHORT-VOL] ingested %s (%d symbols)", key, len(recs))
    return len(recs)


def _poll():
    while True:
        try:
            for d in _trading_days_back(BACKFILL_DAYS):
                _fetch_one_day(d)
            _STORE._last_refresh = time.time()
        except Exception as e:
            logger.warning("[FINRA-SHORT-VOL] poll error: %s", e)
        time.sleep(REFRESH_INTERVAL_S)


_started = False


def start_finra_short_vol_poller() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_poll, daemon=True, name="finra-short-vol-poller").start()
    logger.info("[FINRA-SHORT-VOL] poller started (group=%s, window=%dd)", FINRA_GROUP, WINDOW_DAYS)
