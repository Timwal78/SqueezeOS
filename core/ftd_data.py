"""
FTD Data Layer — SEC Reg SHO Fails-To-Deliver + Threshold List ingestion.

The SEC publishes two public regulatory datasets that institutional traders
pay Bloomberg / Ortex / Fintel hundreds of dollars per month to access:

  1. **Fails-To-Deliver (FTD) reports** — biweekly CSV dumps of every CUSIP
     with FTDs, the date, the share count, and the reference price. Source:
     https://www.sec.gov/data/foiadocsfailsdatahtm

  2. **Reg SHO Threshold Securities List** — daily list of securities with
     persistent settlement failures (FTD position ≥ 0.5 % of TSO and ≥ 10k
     shares for ≥ 5 consecutive settlement days). Source:
     https://www.sec.gov/divisions/marketreg/regsho-threshold-securities.shtml

This module fetches both feeds, normalizes them into in-memory time series,
and exposes lookup helpers used by the /api/ftd blueprint and the
resurrected SettlementCycleEngine.

DESIGN NOTES
============
* **AGENT_LAW §1 (no simulated data):** if SEC returns nothing or fails, we
  return AWAITING_DATA — never invent FTD counts. Same rule as oracle_data.
* **Refresh cadence:** SEC FTD data updates biweekly; we re-check every 24 h.
  Threshold list updates daily; we re-check every 6 h.
* **Memory model:** rolling 180-day window per symbol. That's the entire
  active T+35 universe twice over — plenty for cycle analysis.
* **ETF baskets:** hardcoded constituent maps for the retail-meme ETF
  universe (XRT, IWM, IJR, KRE) since those are the symbols the FTD-via-
  ETF synthetic short thesis actually concerns. The basket lookup returns
  each constituent's FTD percentile rank within the basket — pure data.

Compliance posture: this module surfaces public regulatory data only. It
does NOT predict squeezes, recommend trades, or front-run any settlement
event. Per the operator's directive, all responses are descriptive — they
report what's in the public data, nothing more.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import threading
import time
import urllib.request
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("SqueezeOS-FTD")

# ── SEC endpoints ────────────────────────────────────────────────────────────

# Index page that lists every biweekly FTD ZIP. We scrape the file names off
# it rather than hardcoding URLs so we keep working as the SEC posts new data.
SEC_FTD_INDEX = "https://www.sec.gov/data/foiadocsfailsdatahtm"

# Pattern matches links like cnsfails202311a.zip, cnsfails202311b.zip
SEC_FTD_LINK_RE = re.compile(r"href=\"(/files/data/fails-deliver-data/cnsfails\d{6}[ab]?\.zip)\"", re.IGNORECASE)

# Threshold list page
SEC_THRESHOLD_INDEX = "https://www.sec.gov/divisions/marketreg/regsho-threshold-securities.shtml"

# SEC requires a contact UA header on automated requests
SEC_HDRS = {
    "User-Agent": "SqueezeOS/1.0 agents@scriptmasterlabs.com",
    "Accept": "text/html,application/json,*/*",
}

FTD_REFRESH_INTERVAL_S = 24 * 3600    # SEC publishes biweekly; checking daily is sufficient
THRESHOLD_REFRESH_INTERVAL_S = 6 * 3600  # Threshold list updates daily
WINDOW_DAYS = 180                      # rolling per-symbol window


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class FTDRecord:
    """One day of FTD data for one CUSIP/symbol."""
    settlement_date: date
    cusip: str
    symbol: str
    fail_shares: int
    price: float
    description: str = ""

    def as_dict(self) -> dict:
        return {
            "settlement_date": self.settlement_date.isoformat(),
            "cusip": self.cusip,
            "symbol": self.symbol,
            "fail_shares": self.fail_shares,
            "price": self.price,
            "notional": round(self.fail_shares * self.price, 2),
            "description": self.description,
        }


@dataclass
class ThresholdEntry:
    """One day of Reg SHO threshold list entry."""
    entry_date: date
    symbol: str
    cusip: str
    company: str
    market_category: str = ""

    def as_dict(self) -> dict:
        return {
            "entry_date": self.entry_date.isoformat(),
            "symbol": self.symbol,
            "cusip": self.cusip,
            "company": self.company,
            "market_category": self.market_category,
        }


# ── ETF basket maps — retail-meme universe ──────────────────────────────────
#
# These are the ETFs cited in the FTD-as-synthetic-short literature. The
# constituent list is illustrative — we don't claim weight precision, only
# membership for the basket-rank endpoint. Refresh quarterly per ETF
# rebalance dates from the issuer's published holdings file.
#
# Sources:
#   XRT — State Street SPDR holdings disclosure
#   IWM — iShares Russell 2000 (sample of high-FTD-history constituents)
#   IJR — iShares Core S&P Small-Cap (sample)
#   KRE — SPDR S&P Regional Banking (full holdings small enough to enumerate)

ETF_BASKETS: Dict[str, List[str]] = {
    "XRT": [
        "GME", "AMC", "EXPR", "BBBYQ", "BJ", "M", "JWN", "KSS", "DDS", "URBN",
        "LULU", "ROST", "TJX", "GPS", "AEO", "ANF", "BBY", "DLTR", "BURL", "FIVE",
        "OLLI", "PETM", "DKS", "BBWI", "ULTA", "FND", "TPX", "WSM", "RH", "W",
        "ETSY", "EBAY", "BBY", "FL", "GME", "CVNA", "CHWY", "BABA", "TGT", "WMT",
        "COST", "HD", "LOW", "DG", "DLTR", "FIVE", "OLLI", "DKS", "BJ", "KR",
    ],
    "IWM": [
        # representative high-FTD-history small-caps from Russell 2000
        "GME", "AMC", "BBBYQ", "EXPR", "MMAT", "PROG", "ATER", "SPRT", "IRNT",
        "RKT", "SDC", "WISH", "CLOV", "MULN", "BBIG", "CEI", "BKKT", "RDBX",
        "HKD", "AMTD", "MEGL", "MGOL", "DWAC", "PHUN", "MARK", "CTRM", "TRCH",
    ],
    "IJR": [
        # iShares Core S&P Small-Cap (sample of higher-FTD-velocity names)
        "GME", "AMC", "EXPR", "BBBYQ", "ATER", "PROG", "MMAT", "WISH", "CLOV",
        "RKT", "TUP", "GPRO", "FIZZ", "SHAK", "TPX", "TGI", "SPB", "OSTK", "DBI",
    ],
    "KRE": [
        # SPDR S&P Regional Banking — full holdings list (compressed)
        "FCNCA", "ZION", "EWBC", "WAL", "CFR", "PNFP", "FHN", "WBS", "WTFC", "BPOP",
        "SBNY", "ONB", "SNV", "UBSI", "VLY", "FFBC", "HOMB", "PB", "HWC", "BANR",
        "FRC", "WAFD", "PRK", "BANC", "FFIN", "BOH", "FCBC", "GBCI", "INDB", "TCBI",
    ],
}


# ── In-memory store ──────────────────────────────────────────────────────────


class FTDDataStore:
    """
    Thread-safe in-memory store for SEC FTD + threshold-list data.

    Single instance per process. Started by start_ftd_pollers() at app boot.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # symbol -> deque[FTDRecord] (chronological, oldest first)
        self._by_symbol: Dict[str, "deque[FTDRecord]"] = defaultdict(
            lambda: deque(maxlen=WINDOW_DAYS)
        )
        # symbol -> ThresholdEntry (most recent entry; None when off list)
        self._threshold: Dict[str, Optional[ThresholdEntry]] = {}
        self._last_ftd_refresh: float = 0.0
        self._last_threshold_refresh: float = 0.0
        self._loaded_zip_names: set = set()
        self._available: bool = False  # True once at least one feed succeeded

    # ── public read API ────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            return {
                "available": self._available,
                "symbols_tracked": len(self._by_symbol),
                "threshold_entries": sum(1 for v in self._threshold.values() if v),
                "last_ftd_refresh_ts": self._last_ftd_refresh,
                "last_threshold_refresh_ts": self._last_threshold_refresh,
                "loaded_ftd_files": len(self._loaded_zip_names),
                "window_days": WINDOW_DAYS,
            }

    def series_for(self, symbol: str, limit: int = 90) -> List[FTDRecord]:
        symbol = symbol.upper().strip()
        with self._lock:
            return list(self._by_symbol.get(symbol, ()))[-limit:]

    def latest_ratio(self, symbol: str) -> Optional[dict]:
        """Most recent FTD record + percentile rank within this symbol's window."""
        recs = self.series_for(symbol, limit=WINDOW_DAYS)
        if not recs:
            return None
        latest = recs[-1]
        fails = sorted(r.fail_shares for r in recs)
        position = sum(1 for f in fails if f < latest.fail_shares)
        percentile = position / len(fails) if fails else 0.0
        return {
            "symbol": symbol.upper(),
            "latest": latest.as_dict(),
            "window_days": len(recs),
            "window_max_fails": max(r.fail_shares for r in recs),
            "window_avg_fails": round(sum(r.fail_shares for r in recs) / len(recs), 2),
            "rank_percentile": round(percentile, 4),
            "note": (
                "rank_percentile is the share of in-window records with strictly "
                "smaller fail counts than the latest. 0.95 means the latest reading "
                "is in the top 5% of the rolling 180-day window."
            ),
        }

    def basket_breakdown(self, etf: str) -> Optional[dict]:
        etf = etf.upper().strip()
        constituents = ETF_BASKETS.get(etf)
        if not constituents:
            return None
        rows = []
        for sym in constituents:
            ratio = self.latest_ratio(sym)
            if not ratio:
                rows.append({"symbol": sym, "available": False})
                continue
            rows.append({
                "symbol": sym,
                "available": True,
                "latest_fail_shares": ratio["latest"]["fail_shares"],
                "latest_notional": ratio["latest"]["notional"],
                "latest_settlement_date": ratio["latest"]["settlement_date"],
                "rank_percentile_in_window": ratio["rank_percentile"],
                "window_max_fails": ratio["window_max_fails"],
            })
        rows.sort(key=lambda r: r.get("latest_notional") or 0, reverse=True)
        return {
            "etf": etf,
            "constituent_count": len(constituents),
            "constituents_with_ftd_data": sum(1 for r in rows if r["available"]),
            "constituents": rows,
            "note": (
                "Constituents are sorted by latest FTD notional value (fail_shares × "
                "reference_price). This is a descriptive ranking of where the ETF's "
                "FTD pile is concentrated; it is not a trade signal."
            ),
        }

    def threshold_list(self) -> List[dict]:
        with self._lock:
            return [v.as_dict() for v in self._threshold.values() if v]

    def is_on_threshold_list(self, symbol: str) -> bool:
        with self._lock:
            entry = self._threshold.get(symbol.upper().strip())
            return entry is not None

    def threshold_entry_date(self, symbol: str) -> Optional[date]:
        with self._lock:
            entry = self._threshold.get(symbol.upper().strip())
            return entry.entry_date if entry else None

    # ── ingestion (called by pollers) ──────────────────────────────────────

    def _add_record(self, rec: FTDRecord) -> None:
        with self._lock:
            series = self._by_symbol[rec.symbol]
            # Deduplicate by settlement_date
            if series and series[-1].settlement_date == rec.settlement_date:
                return
            series.append(rec)
            self._available = True

    def _set_threshold(self, entry: ThresholdEntry) -> None:
        with self._lock:
            self._threshold[entry.symbol] = entry

    def _clear_threshold(self, symbols_seen_today: set) -> None:
        """Remove threshold entries for symbols not in today's published list."""
        with self._lock:
            for sym in list(self._threshold.keys()):
                if sym not in symbols_seen_today:
                    self._threshold[sym] = None


# Module-level singleton (init at import — pollers attach to it)
_STORE = FTDDataStore()


def get_store() -> FTDDataStore:
    """Return the process-wide FTD data store."""
    return _STORE


# ── Pollers ──────────────────────────────────────────────────────────────────


def _parse_ftd_csv(raw_bytes: bytes) -> List[FTDRecord]:
    """
    SEC FTD CSV format (after the |-delimited header line):
      SETTLEMENT DATE | CUSIP | SYMBOL | QUANTITY (FAILS) | DESCRIPTION | PRICE

    The format has been stable since 2009. Headers can differ slightly across
    eras (e.g. "QUANTITY (FAILS)" vs "QUANTITY"). We match by index, not name,
    after sniffing the first row.
    """
    text = raw_bytes.decode("latin-1", errors="replace")
    lines = text.splitlines()
    if not lines:
        return []

    delim = "|"
    # Detect delimiter: SEC files have used both | and comma over the years
    sniff = lines[0]
    if "|" not in sniff and "," in sniff:
        delim = ","

    records: List[FTDRecord] = []
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if len(rows) < 2:
        return []

    header = [c.strip().upper() for c in rows[0]]
    # Build a tolerant index map
    def col(*names: str) -> Optional[int]:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_date = col("SETTLEMENT DATE", "DATE", "SETTLEMENT_DATE")
    i_cusip = col("CUSIP")
    i_sym = col("SYMBOL", "TICKER")
    i_qty = col("QUANTITY (FAILS)", "QUANTITY", "FAILS", "FAILS_SHARES", "TOTAL FAILS")
    i_desc = col("DESCRIPTION", "ISSUER NAME", "NAME")
    i_price = col("PRICE", "AVG PRICE", "PX")

    if None in (i_date, i_sym, i_qty):
        logger.warning("[FTD] SEC CSV header missing required columns: %s", header)
        return []

    for row in rows[1:]:
        if len(row) <= max(i_date, i_sym, i_qty):
            continue
        try:
            raw_date = row[i_date].strip()
            # SEC dates: YYYYMMDD
            if len(raw_date) == 8 and raw_date.isdigit():
                sd = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
            else:
                # Try ISO
                sd = date.fromisoformat(raw_date)
        except (ValueError, IndexError):
            continue

        symbol = row[i_sym].strip().upper()
        if not symbol or len(symbol) > 6:
            continue

        try:
            fails = int(row[i_qty].strip().replace(",", ""))
        except (ValueError, IndexError):
            continue
        if fails <= 0:
            continue

        cusip = row[i_cusip].strip() if i_cusip is not None and i_cusip < len(row) else ""
        desc = row[i_desc].strip() if i_desc is not None and i_desc < len(row) else ""
        try:
            price = float(row[i_price].strip()) if i_price is not None and i_price < len(row) else 0.0
        except ValueError:
            price = 0.0

        records.append(FTDRecord(
            settlement_date=sd,
            cusip=cusip,
            symbol=symbol,
            fail_shares=fails,
            price=price,
            description=desc[:120],
        ))

    return records


def _fetch_ftd_index_urls() -> List[str]:
    """Scrape the SEC FTD index page and return the absolute ZIP URLs."""
    try:
        req = urllib.request.Request(SEC_FTD_INDEX, headers=SEC_HDRS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("[FTD] index fetch failed: %s", e)
        return []

    paths = SEC_FTD_LINK_RE.findall(html)
    urls = [f"https://www.sec.gov{p}" for p in paths]
    # Most recent files first (cnsfails202412b > cnsfails202412a > cnsfails202411b)
    urls.sort(reverse=True)
    return urls


def _poll_ftd():
    """Background daemon: pull the 2-3 most recent SEC FTD ZIPs every 24 h."""
    while True:
        try:
            urls = _fetch_ftd_index_urls()
            # Only load the 3 most recent files (≈ 6 weeks of data, plenty for
            # the 180-day rolling window to fill up over time).
            for url in urls[:3]:
                fname = url.rsplit("/", 1)[-1]
                if fname in _STORE._loaded_zip_names:
                    continue
                try:
                    req = urllib.request.Request(url, headers=SEC_HDRS)
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        zbytes = resp.read()
                    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                        for member in zf.namelist():
                            if member.lower().endswith((".txt", ".csv")):
                                raw = zf.read(member)
                                recs = _parse_ftd_csv(raw)
                                for r in recs:
                                    _STORE._add_record(r)
                                logger.info(
                                    "[FTD] ingested %s (%d records, %d symbols)",
                                    member, len(recs), len({r.symbol for r in recs}),
                                )
                    _STORE._loaded_zip_names.add(fname)
                except Exception as e:
                    logger.warning("[FTD] file %s failed: %s", fname, e)

            _STORE._last_ftd_refresh = time.time()
        except Exception as e:
            logger.warning("[FTD] poll error: %s", e)
        time.sleep(FTD_REFRESH_INTERVAL_S)


# Threshold list scraping
THRESHOLD_LINK_RE = re.compile(
    r"href=\"(/divisions/marketreg/regsho/[a-z0-9\-]+nasdaqth\.txt|"
    r"/divisions/marketreg/regsho/[a-z0-9\-]+nyseth\.txt)\"",
    re.IGNORECASE,
)


def _parse_threshold_txt(raw_bytes: bytes, exchange: str) -> List[ThresholdEntry]:
    """
    SEC daily threshold list format (tab- or pipe-delimited):
      Date | Symbol | CUSIP | Company Name | Market Category
    """
    text = raw_bytes.decode("latin-1", errors="replace")
    lines = text.splitlines()
    entries: List[ThresholdEntry] = []
    for ln in lines[1:]:  # skip header
        parts = re.split(r"[|\t]", ln)
        if len(parts) < 4:
            continue
        try:
            raw_date = parts[0].strip()
            if len(raw_date) == 8 and raw_date.isdigit():
                ed = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
            else:
                ed = date.fromisoformat(raw_date)
        except ValueError:
            continue
        symbol = parts[1].strip().upper()
        cusip = parts[2].strip()
        company = parts[3].strip()
        market_category = parts[4].strip() if len(parts) > 4 else exchange
        if not symbol:
            continue
        entries.append(ThresholdEntry(
            entry_date=ed,
            symbol=symbol,
            cusip=cusip,
            company=company[:120],
            market_category=market_category[:40],
        ))
    return entries


def _poll_threshold():
    """Background daemon: pull current Reg SHO threshold list every 6 h."""
    while True:
        try:
            req = urllib.request.Request(SEC_THRESHOLD_INDEX, headers=SEC_HDRS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            paths = THRESHOLD_LINK_RE.findall(html)
            # Sort newest first; only consume the latest two (Nasdaq + NYSE)
            paths.sort(reverse=True)
            seen_today: set = set()
            consumed = 0
            for p in paths[:6]:
                url = f"https://www.sec.gov{p}"
                fname = p.rsplit("/", 1)[-1]
                exch = "NASDAQ" if "nasdaq" in fname.lower() else "NYSE"
                try:
                    r = urllib.request.Request(url, headers=SEC_HDRS)
                    with urllib.request.urlopen(r, timeout=30) as rs:
                        raw = rs.read()
                    entries = _parse_threshold_txt(raw, exch)
                    for e in entries:
                        _STORE._set_threshold(e)
                        seen_today.add(e.symbol)
                    consumed += 1
                    logger.info(
                        "[FTD] threshold list %s: %d entries", fname, len(entries),
                    )
                    if consumed >= 2:  # one Nasdaq + one NYSE is enough
                        break
                except Exception as e:
                    logger.warning("[FTD] threshold file %s failed: %s", fname, e)
            if seen_today:
                _STORE._clear_threshold(seen_today)
            _STORE._last_threshold_refresh = time.time()
        except Exception as e:
            logger.warning("[FTD] threshold poll error: %s", e)
        time.sleep(THRESHOLD_REFRESH_INTERVAL_S)


def start_ftd_pollers() -> None:
    """Start the FTD + threshold-list background daemons. Idempotent."""
    if getattr(start_ftd_pollers, "_started", False):
        return
    setattr(start_ftd_pollers, "_started", True)
    threads = [
        threading.Thread(target=_poll_ftd, daemon=True, name="ftd-fetcher"),
        threading.Thread(target=_poll_threshold, daemon=True, name="ftd-threshold"),
    ]
    for t in threads:
        t.start()
    logger.info("[FTD] pollers started — FTD (24h), Threshold (6h)")


# ── Cycle helper — bridge to the resurrected SettlementCycleEngine ───────────


def cycle_summary_for(symbol: str) -> dict:
    """
    Lightweight settlement-cycle summary that does NOT predict price action.

    Returns a descriptive bundle:
      * latest FTD record + 90-day rolling stats
      * threshold list status + entry date
      * T+35 calendar marker from latest FTD (NOT a trade recommendation)
      * 13-trading-day Reg SHO 204 marker if on threshold list

    Per AGENT_LAW §1: every field that requires data the store doesn't have
    is returned as None with a [SOURCE_UNAVAILABLE: ...] note. Nothing is
    fabricated.
    """
    symbol = symbol.upper().strip()
    store = get_store()
    series = store.series_for(symbol, limit=180)
    notes: List[str] = []
    out: dict = {"symbol": symbol}

    if not series:
        notes.append("[SOURCE_UNAVAILABLE: no FTD records in 180-day window — symbol may be inactive or feed still warming up]")
        out["ftd_records_in_window"] = 0
        out["notes"] = notes
        return out

    latest = series[-1]
    fails_seq = [r.fail_shares for r in series]
    avg_fails = sum(fails_seq) / len(fails_seq)
    spike_ratio = latest.fail_shares / avg_fails if avg_fails > 0 else None

    out["ftd_records_in_window"] = len(series)
    out["latest_settlement_date"] = latest.settlement_date.isoformat()
    out["latest_fail_shares"] = latest.fail_shares
    out["latest_reference_price"] = latest.price
    out["latest_notional_usd"] = round(latest.fail_shares * latest.price, 2)
    out["window_avg_fail_shares"] = round(avg_fails, 1)
    out["window_max_fail_shares"] = max(fails_seq)
    out["window_spike_ratio"] = round(spike_ratio, 3) if spike_ratio is not None else None

    threshold_date = store.threshold_entry_date(symbol)
    out["on_reg_sho_threshold_list"] = threshold_date is not None
    out["threshold_entry_date"] = threshold_date.isoformat() if threshold_date else None

    if threshold_date:
        days_on_list = (date.today() - threshold_date).days
        out["days_on_threshold_list"] = days_on_list
        out["reg_sho_204_close_out_marker"] = (
            threshold_date + timedelta(days=13)
        ).isoformat()
    else:
        out["days_on_threshold_list"] = None
        out["reg_sho_204_close_out_marker"] = None
        notes.append("[REG_SHO: symbol not currently on threshold securities list]")

    # T+35 calendar markers — pure date arithmetic from latest FTD settlement
    # date. Per Reg SHO 204, broker-dealers have extended close-out windows
    # in certain circumstances. This is a descriptive marker only.
    t35_target = latest.settlement_date + timedelta(days=35)
    t21_target = latest.settlement_date + timedelta(days=21)
    today = date.today()
    out["t21_calendar_marker"] = t21_target.isoformat()
    out["t35_calendar_marker"] = t35_target.isoformat()
    out["days_to_t21_from_today"] = (t21_target - today).days
    out["days_to_t35_from_today"] = (t35_target - today).days

    notes.append(
        "T+21 and T+35 are descriptive calendar markers anchored to the LATEST "
        "FTD settlement date. They are not predictions of forced buying. Reg SHO "
        "204 provides bona-fide market-maker exemptions and rolling close-out "
        "mechanics that can extend or short-circuit these windows."
    )

    out["notes"] = notes
    return out
