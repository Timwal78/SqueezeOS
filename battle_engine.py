"""
Battle Computer Engine — FTD Settlement Cycle Resonance
=========================================================
Computes T+N echo windows from live SEC Reg SHO FTD data sourced from
core.ftd_data.FTDDataStore (biweekly SEC ZIPs + daily Reg SHO threshold list).

Prime Directive §1: No simulated data. Returns QUIET state if the store is
still warming up. Never fabricates FTD counts.
"""
from __future__ import annotations

import logging
import math
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Settlement-cycle methodology constants ────────────────────────────────────
# T-offset, weight, color — these are stable methodology parameters.
CYCLES = [
    ('T+25 Stat Wall',          25,  0.72, 'red'),
    ('T+35 Main Echo',          35,  1.00, 'orange'),
    ('T+75 Secondary Echo',     75,  0.68, 'red'),
    ('T+105 Amplified Echo',   105,  1.32, 'orange'),
    ('T+140 Fade / Crush Risk', 140, 0.95, 'goldtxt'),
]


# ── Dynamic calendar helpers ──────────────────────────────────────────────────

def _us_market_holidays(year: int) -> set:
    """Compute NYSE/Nasdaq holidays for a given year. Observed rules applied."""

    def observed(d: date) -> date:
        if d.weekday() == 5:
            return d - timedelta(days=1)   # Saturday → Friday
        if d.weekday() == 6:
            return d + timedelta(days=1)   # Sunday → Monday
        return d

    def nth_weekday(yr: int, mo: int, wd: int, n: int) -> date:
        first = date(yr, mo, 1)
        offset = (wd - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))

    def last_weekday(yr: int, mo: int, wd: int) -> date:
        last = date(yr, mo, monthrange(yr, mo)[1])
        return last - timedelta(days=(last.weekday() - wd) % 7)

    def easter(yr: int) -> date:
        a = yr % 19
        b, c = divmod(yr, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        mo, dy = divmod(h + l - 7 * m + 114, 31)
        return date(yr, mo, dy + 1)

    return {
        observed(date(year, 1, 1)).isoformat(),          # New Year's Day
        nth_weekday(year, 1, 0, 3).isoformat(),          # MLK Day
        nth_weekday(year, 2, 0, 3).isoformat(),          # Presidents' Day
        (easter(year) - timedelta(days=2)).isoformat(),  # Good Friday
        last_weekday(year, 5, 0).isoformat(),            # Memorial Day
        observed(date(year, 6, 19)).isoformat(),         # Juneteenth
        observed(date(year, 7, 4)).isoformat(),          # Independence Day
        nth_weekday(year, 9, 0, 1).isoformat(),          # Labor Day
        nth_weekday(year, 11, 3, 4).isoformat(),         # Thanksgiving
        observed(date(year, 12, 25)).isoformat(),        # Christmas
    }


def _monthly_opex_dates(months_forward: int = 24) -> List[str]:
    """Generate standard monthly OPEX dates (3rd Friday of each month)."""
    result = []
    today = date.today()
    year, month = today.year, today.month
    for _ in range(months_forward):
        first = date(year, month, 1)
        offset = (4 - first.weekday()) % 7   # days to first Friday
        third_friday = first + timedelta(days=offset + 14)
        result.append(third_friday.isoformat())
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FTDAnchor:
    date: str
    fails: int
    ticker: str
    price: float = 0.0
    description: str = ""


@dataclass
class BattleEvent:
    date: str
    label: str
    ticker: str
    score_impact: float
    type: str  # 'ECHO' or 'CATALYST'


# ── Live FTD bridge ───────────────────────────────────────────────────────────

def fetch_realtime_ftd(ticker: str) -> List[FTDAnchor]:
    """
    Fetch live FTD anchors from core.ftd_data.FTDDataStore (SEC EDGAR source).
    Returns [] if the store is still warming up — never fabricates data.
    """
    try:
        from core.ftd_data import get_store
        store = get_store()
        if not store.status().get("available"):
            logger.info("[BATTLE] FTD store warming up — %s anchors deferred", ticker)
            return []
        records = store.series_for(ticker.upper(), limit=180)
        anchors = [
            FTDAnchor(
                date=r.settlement_date.isoformat(),
                fails=r.fail_shares,
                ticker=r.symbol,
                price=r.price,
                description=r.description,
            )
            for r in records
            if r.fail_shares > 0
        ]
        logger.info("[BATTLE] %s: %d live FTD anchors from SEC store", ticker, len(anchors))
        return anchors
    except Exception as e:
        logger.warning("[BATTLE] FTD store lookup failed for %s: %s", ticker, e)
        return []


# ── Engine ────────────────────────────────────────────────────────────────────

class BattleComputerEngine:
    def __init__(self, target_ticker: str = 'GME'):
        self.target_ticker = target_ticker
        self.damping = 0.86
        self.convergence_window = 2
        self.anchors: Dict[str, List[FTDAnchor]] = {}
        self._holidays_cache: Dict[int, set] = {}
        self._opex_cache: Optional[List[str]] = None

    # ── Calendar helpers ──────────────────────────────────────────────────

    def _holidays(self, year: int) -> set:
        if year not in self._holidays_cache:
            self._holidays_cache[year] = _us_market_holidays(year)
        return self._holidays_cache[year]

    def _opex(self) -> List[str]:
        if self._opex_cache is None:
            self._opex_cache = _monthly_opex_dates(months_forward=24)
        return self._opex_cache

    # ── Trading day arithmetic ────────────────────────────────────────────

    def is_trading_day(self, d: datetime) -> bool:
        if d.weekday() >= 5:
            return False
        return d.strftime('%Y-%m-%d') not in self._holidays(d.year)

    def add_trading_days(self, d: datetime, n: int) -> datetime:
        curr = d
        count = 0
        while count < n:
            curr += timedelta(days=1)
            if self.is_trading_day(curr):
                count += 1
        return curr

    def trading_day_dist(self, d1: datetime, d2: datetime) -> int:
        if d1 == d2:
            return 0
        start, end = (d1, d2) if d1 < d2 else (d2, d1)
        curr, dist = start, 0
        while curr.strftime('%Y-%m-%d') != end.strftime('%Y-%m-%d'):
            curr += timedelta(days=1)
            if self.is_trading_day(curr):
                dist += 1
            if dist > 1000:
                break
        return dist if d1 < d2 else -dist

    # ── Core scoring ──────────────────────────────────────────────────────

    def get_opex_risk(self, d: datetime) -> Tuple[str, int]:
        min_dist = 99
        for od in self._opex():
            dt = datetime.strptime(od, '%Y-%m-%d')
            dist = abs(self.trading_day_dist(d, dt))
            min_dist = min(min_dist, dist)
        if min_dist <= 1: return ('Extreme', 18)
        if min_dist <= 3: return ('High', 12)
        if min_dist <= 5: return ('Med', 7)
        return ('Low', 0)

    def refresh(self) -> None:
        """Pull fresh FTD anchors from the SEC store."""
        self.anchors = {self.target_ticker: fetch_realtime_ftd(self.target_ticker)}
        if self.target_ticker == 'GME':
            self.anchors['AMC'] = fetch_realtime_ftd('AMC')

    def calculate_resonance(self, ticker: str, target_date: str) -> dict:
        target_dt = datetime.strptime(target_date, '%Y-%m-%d')
        anchors = self.anchors.get(ticker, [])
        if not anchors:
            return {
                "ticker": ticker,
                "date": target_date,
                "score": 0,
                "state": "QUIET",
                "action": "WAIT",
                "opex_risk": "Low",
                "active_echos": [],
                "note": "FTD store warming up or no anchors in 180-day window",
            }

        mx_fails = max(a.fails for a in anchors)
        total_score = 0.0
        active_echos = []

        for anchor in anchors:
            anchor_dt = datetime.strptime(anchor.date, '%Y-%m-%d')
            for label, t_offset, weight, _color in CYCLES:
                echo_dt = self.add_trading_days(anchor_dt, t_offset)
                dist = abs(self.trading_day_dist(target_dt, echo_dt))
                if dist > self.convergence_window:
                    continue
                amp = (anchor.fails / mx_fails) * weight * math.pow(
                    self.damping, max(1, round(t_offset / 35))
                )
                score_inc = amp * (1 - dist / (self.convergence_window + 1)) * 72
                total_score += score_inc
                active_echos.append({"label": label, "t": t_offset, "impact": round(score_inc, 2)})

        risk_label, risk_score = self.get_opex_risk(target_dt)
        total_score += risk_score
        final_score = min(100, round(total_score))

        state, action = "QUIET", "WAIT"
        if final_score >= 82:   state, action = "IGNITION",   "ADD/HOLD"
        elif final_score >= 64: state, action = "BULL ZONE",  "STARTER/ADD"
        elif final_score >= 44: state, action = "WATCH",      "WATCH"
        elif final_score >= 24: state, action = "EARLY HEAT", "SCOUT"

        return {
            "ticker": ticker,
            "date": target_date,
            "score": final_score,
            "state": state,
            "action": action,
            "opex_risk": risk_label,
            "active_echos": active_echos,
        }

    def get_battle_summary(self, target_date: Optional[str] = None) -> dict:
        if not target_date:
            target_date = datetime.now().strftime('%Y-%m-%d')

        self.refresh()   # always pull live SEC data

        gme = self.calculate_resonance('GME', target_date)
        amc = self.calculate_resonance('AMC', target_date)

        avg_score = (gme['score'] + amc['score']) / 2
        basket_score = min(100, round(avg_score * 1.12))

        state, action = "QUIET", "WAIT"
        if basket_score >= 82:   state, action = "IGNITION",   "ADD/HOLD"
        elif basket_score >= 64: state, action = "BULL ZONE",  "STARTER/ADD"
        elif basket_score >= 44: state, action = "WATCH",      "WATCH"
        elif basket_score >= 24: state, action = "EARLY HEAT", "SCOUT"

        return {
            "summary": {
                "date": target_date,
                "basket_score": basket_score,
                "basket_state": state,
                "basket_action": action,
                "leader": "GME" if gme['score'] > amc['score'] else "AMC",
            },
            "gme": gme,
            "amc": amc,
        }
