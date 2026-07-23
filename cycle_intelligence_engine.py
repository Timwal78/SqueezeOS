"""
CIE — Cycle Intelligence Engine, server-side Python.
=======================================================================
The SINGLE implementation of the CIE math. Consumers:

  • cie_scanner.py            — background loop → iam_executor (auto-trading)
  • core/api/cie_bp.py        — /api/cie/<symbol> on-demand analysis
  • tests/test_cie_cycle.py   — four-layer stress test (imports from here)
  • tests/backtest_cie.py     — backtest harness

Mirrors pine/cycle_intelligence_engine.pine ("CIE-BEAST") conceptually —
four independent pressure axes combined into one convergence signal:

  1. SettlementCycleEngine   — FTD velocity + Reg SHO threshold T+35 countdown
                                + cost-to-borrow (forced buy-in pressure)
  2. DarkPoolCycleAnalyzer   — off-exchange ratio (OER), hidden-order
                                imbalance (HOI), decayed dark momentum (DLMD)
  3. HistoricalFractalMatcher— correlates the live return window against a
                                library of labeled historical analogs
  4. MemeCycleDetector       — 6-phase DORMANT→PARABOLIC classifier from
                                volume-vs-ADV ratio + IV percentile rank

`CycleIntelligenceEngine.evaluate()` sums the four axes' 0–1.5 pressure
scores into a composite_z and resolves a state: DORMANT / BUILDING /
PRIMED / CIE_FIRE (fires when composite_z >= 3.0 with >=2 axes active).

This engine was previously referenced by tests/CLAUDE.md but the file
itself was missing from the repo — tests/test_cie_cycle.py failed with
ModuleNotFoundError before this was written. No backtest evidence exists
yet; do not claim this is profitable until tests/backtest_cie.py has run
against real bars (same evidence-before-claims rule as ORB/DRUCK/IMO).

Every layer degrades honestly: with no data ingested, pressure_score is
0.0 and an [ESTIMATED_PROXY]-style note explains why — never a guess.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple


CIE_CONFIG = {
    # Layer 1 — Settlement Cycle
    "sett_ftd_high_pct": 0.005,          # FTD shares / float ratio considered "high"
    "sett_ctb_htb_pct": 0.30,            # cost-to-borrow ratio considered "hard to borrow"
    "sett_t35_days": 35,                 # Reg SHO forced buy-in window
    "sett_t35_proximity_days": 7,        # ramp-up window before the deadline
    # Layer 2 — Dark Pool Cycle
    "dp_oer_len": 20,                    # rolling bars for OER/HOI/cluster lookback
    "dp_dlmd_decay": 0.88,               # EMA decay for dark-pool momentum
    "dp_cluster_min_bars": 5,            # bars of one-sided dominance to call a cluster
    "dp_cluster_dominance": 0.65,        # per-bar dominance fraction to count toward a cluster
    # Layer 3 — Historical Fractal Matcher
    "hfm_window": 20,                    # bars in the comparison window
    "hfm_min_corr": 0.85,                # minimum correlation to call it a match
    # Layer 4 — Meme Cycle Phase Detector
    "mcpd_vol_window": 20,               # bars for ADV (volume SMA)
    "mcpd_iv_window": 200,               # bars of IV history for percentile rank
    "mcpd_sir_extreme_pct": 15.0,        # short-interest % considered "extreme"
}

_PROXY = "[ESTIMATED_PROXY]"


def _pearson(a: List[float], b: List[float]) -> Optional[float]:
    """Pearson correlation of two equal-length series. None if degenerate."""
    n = min(len(a), len(b))
    if n < 2:
        return None
    a = a[-n:]
    b = b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


# ══════════════════════════════════════════════════════════════════
# Layer 1: Settlement Cycle Engine
# ══════════════════════════════════════════════════════════════════
@dataclass
class SettlementSignal:
    symbol: str
    pressure_score: float
    ftd_velocity: Optional[float]
    t35_days_remaining: Optional[int]
    notes: List[str] = field(default_factory=list)


class SettlementCycleEngine:
    """FTD velocity + Reg SHO threshold-list T+35 countdown + cost-to-borrow."""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or dict(CIE_CONFIG)
        self._ftd: Dict[str, List[Tuple[date, int, int]]] = {}
        self._threshold: Dict[str, Tuple[bool, Optional[date]]] = {}
        self._ctb: Dict[str, float] = {}

    def update_ftd(self, symbol: str, dt: date, ftd_shares: int, float_shares: int) -> None:
        recs = self._ftd.setdefault(symbol, [])
        recs.append((dt, ftd_shares, float_shares))
        recs.sort(key=lambda r: r[0])
        del recs[:-30]

    def update_threshold_status(self, symbol: str, on_list: bool, since_date: Optional[date] = None) -> None:
        self._threshold[symbol] = (on_list, since_date)

    def update_ctb(self, symbol: str, ctb: float) -> None:
        self._ctb[symbol] = ctb

    def evaluate(self, symbol: str, today: date) -> SettlementSignal:
        notes: List[str] = []

        records = self._ftd.get(symbol, [])
        ftd_velocity: Optional[float] = None
        ftd_score = 0.0
        if not records:
            notes.append(f"ftd_velocity_unavailable: no FTD data ingested {_PROXY}")
        else:
            ratios = [f / max(1, fl) for (_, f, fl) in records]
            ftd_velocity = sum(ratios) / len(ratios)
            high_pct = self.cfg.get("sett_ftd_high_pct", 0.005)
            if high_pct > 0:
                ftd_score = min(0.75, max(0.0, (ftd_velocity / high_pct) * 0.5))

        threshold_score = 0.0
        t35_days_remaining: Optional[int] = None
        on_list, since_date = self._threshold.get(symbol, (False, None))
        if on_list and since_date:
            t35_total = self.cfg.get("sett_t35_days", 35)
            elapsed = (today - since_date).days
            t35_days_remaining = max(0, t35_total - elapsed)
            proximity = self.cfg.get("sett_t35_proximity_days", 7)
            if t35_days_remaining <= 0:
                threshold_score = 0.5
            elif t35_days_remaining <= proximity:
                threshold_score = 0.5 * (1.0 - t35_days_remaining / proximity)
        elif on_list and not since_date:
            notes.append(f"threshold_since_date_unavailable: on-list but no start date {_PROXY}")

        ctb_score = 0.0
        ctb = self._ctb.get(symbol)
        if ctb is not None:
            htb_pct = self.cfg.get("sett_ctb_htb_pct", 0.30)
            if htb_pct > 0:
                ctb_score = 0.5 if ctb >= htb_pct else 0.25 * (ctb / htb_pct)

        pressure_score = min(1.5, round(ftd_score + threshold_score + ctb_score, 4))
        return SettlementSignal(
            symbol=symbol,
            pressure_score=pressure_score,
            ftd_velocity=round(ftd_velocity, 6) if ftd_velocity is not None else None,
            t35_days_remaining=t35_days_remaining,
            notes=notes,
        )


# ══════════════════════════════════════════════════════════════════
# Layer 2: Dark Pool Cycle Analyzer
# ══════════════════════════════════════════════════════════════════
@dataclass
class DarkPoolSignal:
    ticker: str
    oer: Optional[float]
    hoi: Optional[float]
    dlmd: float
    cluster_bars: int
    cluster_active: bool
    pressure_score: float
    notes: List[str] = field(default_factory=list)


class DarkPoolCycleAnalyzer:
    """Off-exchange ratio, hidden-order imbalance, decayed dark momentum (DLMD)."""

    def __init__(self, ticker: str, cfg: Optional[dict] = None):
        self.ticker = ticker
        self.cfg = cfg or dict(CIE_CONFIG)
        maxlen = self.cfg.get("dp_oer_len", 20)
        self._oer_hist: deque = deque(maxlen=maxlen)
        self._dominance_hist: deque = deque(maxlen=maxlen)
        self._dlmd = 0.0

    def ingest_bar(self, dark_prints: Optional[List[dict]], lit_volume: float, spot: float) -> None:
        if not dark_prints:
            return
        buy = sum(p["size"] for p in dark_prints if p["price"] > p.get("mid", spot))
        sell = sum(p["size"] for p in dark_prints if p["price"] < p.get("mid", spot))
        total = buy + sell
        if total <= 0:
            return

        oer = total / max(1.0, total + lit_volume)
        self._oer_hist.append(oer)
        self._dominance_hist.append(max(buy, sell) / total)

        bar_ofi = max(-1.0, min(1.0, (buy - sell) / total))
        decay = self.cfg.get("dp_dlmd_decay", 0.88)
        self._dlmd = max(-1.0, min(1.0, decay * self._dlmd + (1.0 - decay) * bar_ofi))

    def evaluate(self) -> DarkPoolSignal:
        notes: List[str] = []
        if not self._oer_hist:
            notes.append(f"dark_flow_unavailable: no dark-pool prints ingested {_PROXY}")
            return DarkPoolSignal(self.ticker, None, None, round(self._dlmd, 4), 0, False, 0.0, notes)

        oer = self._oer_hist[-1]
        hoi = sum(self._dominance_hist) / len(self._dominance_hist)
        cluster_min = self.cfg.get("dp_cluster_min_bars", 5)
        cluster_thresh = self.cfg.get("dp_cluster_dominance", 0.65)
        cluster_bars = sum(1 for d in self._dominance_hist if d >= cluster_thresh)
        cluster_active = cluster_bars >= cluster_min

        oer_score = 0.40 if oer >= 0.50 else 0.15 if oer >= 0.35 else 0.0
        hoi_score = min(0.5, hoi * 0.5)
        dlmd_score = min(0.35, abs(self._dlmd) * 0.35)
        pressure_score = min(1.5, round(oer_score + hoi_score + dlmd_score, 4))

        return DarkPoolSignal(
            ticker=self.ticker,
            oer=round(oer, 4),
            hoi=round(hoi, 4),
            dlmd=round(self._dlmd, 4),
            cluster_bars=cluster_bars,
            cluster_active=cluster_active,
            pressure_score=pressure_score,
            notes=notes,
        )


# ══════════════════════════════════════════════════════════════════
# Layer 3: Historical Fractal Matcher
# ══════════════════════════════════════════════════════════════════
@dataclass
class HFMSignal:
    ticker: str
    window_bars: int
    best_similarity: Optional[float]
    top_matches: List[dict]
    median_forward_return: Optional[float]
    pressure_score: float
    notes: List[str] = field(default_factory=list)


class HistoricalFractalMatcher:
    """Correlates the live return window against a library of labeled analogs."""

    def __init__(self, cfg: Optional[dict] = None, ticker: str = "UNKNOWN"):
        self.cfg = cfg or dict(CIE_CONFIG)
        self.ticker = ticker
        self.w = self.cfg.get("hfm_window", 20)
        self._closes: deque = deque(maxlen=self.w + 1)
        self._volumes: deque = deque(maxlen=self.w + 1)
        self._ivs: deque = deque(maxlen=self.w + 1)
        self._library: List[dict] = []

    def add_historical_signature(self, label: str, price_returns: List[float],
                                  volume_ratios: List[float], iv_series: List[float],
                                  forward_return: float) -> None:
        self._library.append({
            "label": label,
            "price_returns": list(price_returns),
            "volume_ratios": list(volume_ratios),
            "iv_series": list(iv_series),
            "forward_return": forward_return,
        })

    def ingest_bar(self, close: float, volume: float, iv_atm: float, adv: Optional[float] = None) -> None:
        self._closes.append(close)
        self._volumes.append(volume)
        self._ivs.append(iv_atm)

    def _current_returns(self) -> List[float]:
        closes = list(self._closes)
        if len(closes) < 2:
            return []
        return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]

    def evaluate(self) -> HFMSignal:
        notes: List[str] = []
        window_bars = max(0, len(self._closes) - 1)

        if not self._library:
            notes.append(f"library_empty: no historical signatures loaded {_PROXY}")
            return HFMSignal(self.ticker, window_bars, None, [], None, 0.0, notes)

        if len(self._closes) < self.w + 1:
            notes.append("window_unfilled: awaiting full lookback window")
            return HFMSignal(self.ticker, window_bars, None, [], None, 0.0, notes)

        cur_returns = self._current_returns()[-self.w:]
        min_corr = self.cfg.get("hfm_min_corr", 0.85)

        matches = []
        for sig in self._library:
            sim = _pearson(cur_returns, sig["price_returns"][-self.w:])
            if sim is None:
                continue
            matches.append({
                "label": sig["label"],
                "similarity": round(sim, 4),
                "forward_return": sig["forward_return"],
            })
        matches.sort(key=lambda m: m["similarity"], reverse=True)

        best_similarity = matches[0]["similarity"] if matches else None
        top_matches = [m for m in matches if m["similarity"] >= min_corr][:5]

        median_forward_return = None
        if top_matches:
            fwds = sorted(m["forward_return"] for m in top_matches)
            n = len(fwds)
            med = fwds[n // 2] if n % 2 else (fwds[n // 2 - 1] + fwds[n // 2]) / 2
            median_forward_return = round(med * 100, 2)

        if best_similarity is None:
            pressure_score = 0.0
        elif best_similarity >= min_corr:
            pressure_score = min(1.5, round(1.0 + max(0.0, best_similarity - min_corr) * 3.0, 4))
        else:
            pressure_score = round(max(0.0, best_similarity) * (1.0 / min_corr) * 0.8, 4)

        return HFMSignal(
            ticker=self.ticker,
            window_bars=window_bars,
            best_similarity=best_similarity,
            top_matches=top_matches,
            median_forward_return=median_forward_return,
            pressure_score=pressure_score,
            notes=notes,
        )


# ══════════════════════════════════════════════════════════════════
# Layer 4: Meme Cycle Phase Detector
# ══════════════════════════════════════════════════════════════════
@dataclass
class MCPDSignal:
    ticker: str
    phase: str
    phase_score: float
    pressure_score: float
    volume_ratio: Optional[float]
    iv_percentile: Optional[float]
    notes: List[str] = field(default_factory=list)


_PHASE_PRESSURE = {
    "PARABOLIC": 1.5, "IGNITION": 1.0, "DISTRIBUTION": 0.8,
    "ACCUMULATION": 0.5, "UNWIND": 0.3, "DORMANT": 0.0,
}
_PHASE_ORDER = ["PARABOLIC", "IGNITION", "ACCUMULATION", "DISTRIBUTION", "UNWIND", "DORMANT"]


class MemeCycleDetector:
    """6-phase DORMANT→PARABOLIC classifier from volume-vs-ADV + IV percentile rank."""

    def __init__(self, ticker: str, cfg: Optional[dict] = None):
        self.ticker = ticker
        self.cfg = cfg or dict(CIE_CONFIG)
        self._volumes: deque = deque(maxlen=self.cfg.get("mcpd_vol_window", 20))
        self._ivs: deque = deque(maxlen=self.cfg.get("mcpd_iv_window", 200))
        self._sir: Optional[float] = None

    def update_short_interest(self, sir_pct: float) -> None:
        self._sir = sir_pct

    def ingest_bar(self, volume: float, iv_atm: float) -> None:
        self._volumes.append(volume)
        self._ivs.append(iv_atm)

    def evaluate(self, tnt_state: str = "NEUTRAL") -> MCPDSignal:
        notes: List[str] = []

        volume_ratio: Optional[float] = None
        if self._volumes:
            adv = sum(self._volumes) / len(self._volumes)
            volume_ratio = round(self._volumes[-1] / adv, 4) if adv > 0 else None

        iv_pct: Optional[float] = None
        if len(self._ivs) >= 10:
            cur_iv = self._ivs[-1]
            below = sum(1 for v in self._ivs if v < cur_iv)
            iv_pct = round(below / len(self._ivs), 4)

        if self._sir is None:
            notes.append(f"sir_unavailable: no short-interest data supplied {_PROXY}")

        vr = volume_ratio if volume_ratio is not None else 1.0
        tnt_active = tnt_state in ("TNT_LONG", "TNT_SHORT")
        sir_extreme = self._sir is not None and self._sir >= self.cfg.get("mcpd_sir_extreme_pct", 15.0)

        def _between(lo: float, hi: float) -> bool:
            return iv_pct is not None and lo <= iv_pct < hi

        def _ge(lo: float) -> bool:
            return iv_pct is not None and iv_pct >= lo

        def _lt(hi: float) -> bool:
            return iv_pct is not None and iv_pct < hi

        scores = {
            "DORMANT":      (1.0 if vr < 0.80 else 0.0) + (0.5 if _lt(0.35) else 0.0),
            "ACCUMULATION": (0.5 if 0.80 <= vr < 2.5 else 0.0) + (0.5 if _between(0.35, 0.50) else 0.0),
            "IGNITION":     (1.0 if vr >= 2.5 else 0.0) + (0.5 if _between(0.50, 0.80) else 0.0)
                            + (0.5 if tnt_active else 0.0),
            "PARABOLIC":    (0.5 if vr >= 2.5 else 0.0) + (1.0 if _ge(0.80) else 0.0)
                            + (1.0 if tnt_active else 0.0) + (0.5 if sir_extreme else 0.0),
            "DISTRIBUTION": (0.5 if _between(0.70, 0.80) else 0.0),
            "UNWIND":       (0.5 if _lt(0.35) else 0.0) + (0.5 if vr < 1.0 else 0.0),
        }
        best_phase = max(_PHASE_ORDER, key=lambda p: (scores[p], -_PHASE_ORDER.index(p)))
        phase_score = scores[best_phase]
        pressure_score = _PHASE_PRESSURE[best_phase]

        return MCPDSignal(
            ticker=self.ticker,
            phase=best_phase,
            phase_score=phase_score,
            pressure_score=pressure_score,
            volume_ratio=volume_ratio,
            iv_percentile=iv_pct,
            notes=notes,
        )


# ══════════════════════════════════════════════════════════════════
# Convergence: Cycle Intelligence Engine
# ══════════════════════════════════════════════════════════════════
@dataclass
class CIESignal:
    ticker: str
    state: str
    composite_z: float
    components: dict
    settlement: Optional[SettlementSignal]
    dark_pool: Optional[DarkPoolSignal]
    fractal: Optional[HFMSignal]
    meme_cycle: Optional[MCPDSignal]


class CycleIntelligenceEngine:
    """Combines all four axes per ticker into one composite_z / state signal."""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or dict(CIE_CONFIG)
        self._settlement = SettlementCycleEngine(self.cfg)
        self._dark: Dict[str, DarkPoolCycleAnalyzer] = {}
        self._fractal: Dict[str, HistoricalFractalMatcher] = {}
        self._meme: Dict[str, MemeCycleDetector] = {}

    def _dark_for(self, ticker: str) -> DarkPoolCycleAnalyzer:
        return self._dark.setdefault(ticker, DarkPoolCycleAnalyzer(ticker, self.cfg))

    def _fractal_for(self, ticker: str) -> HistoricalFractalMatcher:
        return self._fractal.setdefault(ticker, HistoricalFractalMatcher(self.cfg, ticker))

    def _meme_for(self, ticker: str) -> MemeCycleDetector:
        return self._meme.setdefault(ticker, MemeCycleDetector(ticker, self.cfg))

    # -- ingestion -----------------------------------------------------
    def ingest_ftd(self, ticker: str, dt: date, ftd_shares: int, float_shares: int) -> None:
        self._settlement.update_ftd(ticker, dt, ftd_shares, float_shares)

    def update_threshold_status(self, ticker: str, on_list: bool, since_date: Optional[date] = None) -> None:
        self._settlement.update_threshold_status(ticker, on_list, since_date)

    def update_ctb(self, ticker: str, ctb: float) -> None:
        self._settlement.update_ctb(ticker, ctb)

    def ingest_dark_bar(self, ticker: str, dark_prints: Optional[List[dict]], lit_volume: float, spot: float) -> None:
        self._dark_for(ticker).ingest_bar(dark_prints, lit_volume, spot)

    def add_historical_signature(self, ticker: str, label: str, price_returns: List[float],
                                  volume_ratios: List[float], iv_series: List[float],
                                  forward_return: float) -> None:
        self._fractal_for(ticker).add_historical_signature(
            label, price_returns, volume_ratios, iv_series, forward_return)

    def ingest_price_bar(self, ticker: str, close: float, volume: float, iv_atm: float,
                          adv: Optional[float] = None) -> None:
        """One bar of real market data feeds both the fractal matcher and the
        meme-cycle detector — they need the same close/volume/iv inputs."""
        self._fractal_for(ticker).ingest_bar(close, volume, iv_atm, adv)
        self._meme_for(ticker).ingest_bar(volume, iv_atm)

    def update_short_interest(self, ticker: str, sir_pct: float) -> None:
        self._meme_for(ticker).update_short_interest(sir_pct)

    # -- evaluation ------------------------------------------------------
    def evaluate(self, ticker: str, tnt_state: str = "NEUTRAL", today: Optional[date] = None) -> CIESignal:
        today = today or date.today()

        settlement = self._settlement.evaluate(ticker, today)
        dark_pool = self._dark[ticker].evaluate() if ticker in self._dark else None
        fractal = self._fractal[ticker].evaluate() if ticker in self._fractal else None
        meme_cycle = self._meme[ticker].evaluate(tnt_state) if ticker in self._meme else None

        z_sett = settlement.pressure_score if settlement else 0.0
        z_dark = dark_pool.pressure_score if dark_pool else 0.0
        z_frac = fractal.pressure_score if fractal else 0.0
        z_meme = meme_cycle.pressure_score if meme_cycle else 0.0
        composite_z = round(z_sett + z_dark + z_frac + z_meme, 4)

        active_axes = sum(1 for z in (z_sett, z_dark, z_frac, z_meme) if z >= 0.5)
        if composite_z >= 3.0 and active_axes >= 2:
            state = "CIE_FIRE"
        elif composite_z >= 1.5 and active_axes >= 2:
            state = "PRIMED"
        elif composite_z > 0:
            state = "BUILDING"
        else:
            state = "DORMANT"

        components = {
            "z_settlement": z_sett, "z_dark_pool": z_dark,
            "z_fractal": z_frac, "z_meme_cycle": z_meme,
        }
        return CIESignal(
            ticker=ticker, state=state, composite_z=composite_z, components=components,
            settlement=settlement, dark_pool=dark_pool, fractal=fractal, meme_cycle=meme_cycle,
        )


# ══════════════════════════════════════════════════════════════════
# Stateless single-symbol wrapper — mirrors orb_engine.analyze() /
# druck_engine.analyze(). Used by both core/api/cie_bp.py (on-demand)
# and cie_scanner.py (background loop).
# ══════════════════════════════════════════════════════════════════
def _realized_vol_proxy(highs: List[float], lows: List[float], closes: List[float],
                         length: int = 14) -> List[float]:
    """SMA-smoothed True Range % of close, aligned to `closes`.

    NOT options-chain implied volatility. This engine has no real IV feed
    wired (that would need a Tradier options-chain pull per bar per
    symbol); realized range volatility is used as a same-shape substitute
    for the meme-cycle layer's "iv_atm" input, same convention as the
    original CIE-BEAST Pine script's ATR-rank meme-phase detector. Callers
    must not present this as options IV.
    """
    n = len(closes)
    if n == 0:
        return []
    tr = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = highs[i] - lows[i]
        else:
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out = [0.0] * n
    for i in range(n):
        window = tr[max(0, i - length + 1): i + 1]
        atr = sum(window) / len(window) if window else 0.0
        out[i] = (atr / closes[i]) if closes[i] else 0.0
    return out


def analyze(symbol: str, bars: List[dict],
            ftd_records: Optional[List[Tuple[date, int, int]]] = None,
            on_threshold_list: bool = False, threshold_since: Optional[date] = None,
            ctb: Optional[float] = None, sir_pct: Optional[float] = None,
            tnt_state: str = "NEUTRAL", today: Optional[date] = None,
            hfm_forward_bars: int = 10, hfm_stride: int = 5,
            hfm_max_signatures: int = 40) -> dict:
    """
    Real-bars-only single-symbol CIE read.

    Settlement layer uses real SEC FTD/threshold-list data when supplied
    (see core/ftd_data.py) — pass none of it and that axis stays at 0.0
    with an honest "unavailable" note, never fabricated.

    Dark-pool layer is NEVER fed here: no real dark-pool print feed exists
    anywhere in this codebase (confirmed by search — the "dark_pool"
    references elsewhere are unrelated OFI-style proxies in other
    engines). It stays at 0.0/"dark_flow_unavailable" until a real feed is
    wired — that is future work, not simulated here.

    Historical Fractal Matcher gets a self-referential signature library
    mined from the SAME real bar history passed in: every
    hfm_stride-spaced hfm_window-bar segment (excluding the live tail
    window) is stored with its own real forward return over the next
    hfm_forward_bars. This needs no external dataset and never invents a
    forward return — it's this exact symbol's own real price history.

    `bars` — list of {"c"/"close", "h"/"high", "l"/"low", "v"/"volume",
    "date"/"t"} in chronological order (DataManager.get_bars() shape).
    """
    w = CIE_CONFIG["hfm_window"]
    if not bars or len(bars) < w + hfm_forward_bars + 2:
        return {"status": "error", "message": "insufficient bars", "symbol": symbol,
                "bars_received": len(bars or []), "bars_required": w + hfm_forward_bars + 2}

    def _f(b: dict, *keys, default=0.0) -> float:
        for k in keys:
            if k in b and b[k] is not None:
                return float(b[k])
        return default

    closes = [_f(b, "c", "close") for b in bars]
    highs = [_f(b, "h", "high", default=closes[i]) for i, b in enumerate(bars)]
    lows = [_f(b, "l", "low", default=closes[i]) for i, b in enumerate(bars)]
    vols = [_f(b, "v", "volume") for b in bars]
    vol_proxy = _realized_vol_proxy(highs, lows, closes)

    engine = CycleIntelligenceEngine()

    for (dt, ftd_shares, float_shares) in (ftd_records or []):
        engine.ingest_ftd(symbol, dt, ftd_shares, float_shares)
    if on_threshold_list:
        engine.update_threshold_status(symbol, True, threshold_since)
    if ctb is not None:
        engine.update_ctb(symbol, ctb)
    if sir_pct is not None:
        engine.update_short_interest(symbol, sir_pct)

    n = len(closes)
    lib_end = n - (w + 1)  # leave the final w+1 bars as the untouched live window
    idx = 0
    sig_count = 0
    while idx + w + hfm_forward_bars <= lib_end and sig_count < hfm_max_signatures:
        seg_closes = closes[idx: idx + w + 1]
        seg_rets = [math.log(seg_closes[i] / seg_closes[i - 1]) for i in range(1, len(seg_closes))]
        seg_vols = vols[idx + 1: idx + w + 1]
        adv_window = vols[max(0, idx - w): idx + 1]
        adv = sum(adv_window) / len(adv_window) if adv_window else 0.0
        seg_vol_ratios = [(v / adv) if adv > 0 else 1.0 for v in seg_vols]
        seg_ivs = vol_proxy[idx + 1: idx + w + 1]
        fwd_start = closes[idx + w]
        fwd_end = closes[idx + w + hfm_forward_bars]
        fwd_return = (fwd_end / fwd_start) - 1.0 if fwd_start else 0.0
        engine.add_historical_signature(symbol, f"bar_{idx}", seg_rets, seg_vol_ratios, seg_ivs, fwd_return)
        sig_count += 1
        idx += hfm_stride

    for i in range(n):
        engine.ingest_price_bar(symbol, closes[i], vols[i], vol_proxy[i])

    sig = engine.evaluate(symbol, tnt_state=tnt_state, today=today or date.today())

    direction: Optional[str] = None
    if sig.dark_pool and sig.dark_pool.dlmd:
        direction = "BUY" if sig.dark_pool.dlmd > 0 else "SELL"
    elif sig.fractal and sig.fractal.median_forward_return is not None:
        direction = "BUY" if sig.fractal.median_forward_return >= 0 else "SELL"

    signal = None
    if sig.state == "CIE_FIRE" and direction:
        signal = direction
    elif sig.state in ("CIE_FIRE", "PRIMED"):
        signal = "WATCH"

    last_bar = bars[-1]
    bar_key = last_bar.get("date") or last_bar.get("t") or str(n)

    return {
        "status": "success",
        "symbol": symbol,
        "price": closes[-1],
        "bar_key": bar_key,
        "state": sig.state,
        "composite_z": sig.composite_z,
        "components": sig.components,
        "direction": direction,
        "signal": signal,
        "settlement": asdict(sig.settlement) if sig.settlement else None,
        "dark_pool": asdict(sig.dark_pool) if sig.dark_pool else None,
        "fractal": asdict(sig.fractal) if sig.fractal else None,
        "meme_cycle": asdict(sig.meme_cycle) if sig.meme_cycle else None,
        "historical_signatures_mined": sig_count,
        "disclosure": (
            "meme_cycle's iv_atm input is a realized ATR% volatility proxy, NOT "
            "options-chain implied volatility. dark_pool is never fed real data in "
            "this wrapper — no real dark-pool print feed exists in this codebase, "
            "so that axis stays at 0.0 by design, not simulated."
        ),
    }
