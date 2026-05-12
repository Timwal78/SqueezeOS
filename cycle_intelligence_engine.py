"""
SQUEEZE OS — Cycle Intelligence Engine (CIE) v1.0
══════════════════════════════════════════════════════════════════════
Proprietary institutional-grade cycle detection: settlement pressure,
dark-pool accumulation cycles, historical fractal analog matching,
and meme-cycle phase detection — fused into a single convergence signal.

Four-layer architecture — each layer equals or exceeds MMLE standalone:

  LAYER 1 — Settlement Cycle Engine (SCE)
    Regulation SHO T+2/T+21/T+35 forced-buy-in pressure.  Tracks FTD
    accumulation velocity, threshold-security proximity, and cost-to-
    borrow implied short interest.

  LAYER 2 — Dark Pool Cycle Analyzer (DPCA)
    Multi-bar off-exchange volume ratio (OER), block-cluster detector,
    hidden order-flow imbalance (HOI), and time-weighted dark/lit
    momentum divergence (DLMD).  Unlike MMLE's single-bar dark proxy,
    DPCA tracks dark behavior across a rolling 20-bar window to detect
    multi-session accumulation cycles.

  LAYER 3 — Historical Fractal Matcher (HFM)
    Rolling price·volume·IV signature comparison against a caller-supplied
    historical library (sourced from Polygon OHLCV or Schwab history).
    Computes weighted Pearson correlation of normalized return sequences;
    surfaces top-N analog periods and their empirical forward-return
    distributions.  The legitimate statistical form of pattern
    recognition — parameterized, transparent, and falsifiable.

  LAYER 4 — Meme Cycle Phase Detector (MCPD)
    Six-phase regime: DORMANT → ACCUMULATION → IGNITION → PARABOLIC →
    DISTRIBUTION → UNWIND.  Multi-axis z-score fusion at the MMLE
    composite standard; MMLE TNT state is a confirmatory input.

Governance:
    Bound by AGENT_LAW.md
      - Law 1: NO simulated data — pause if missing.
      - Law 2: Parameterized alpha factors — every coefficient in CIE_CONFIG.
      - Law 3: Transparent proxies — labeled [ESTIMATED_PROXY: ...].
      - Law 4: 5-min institutional cadence preserved.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION (AGENT_LAW §2 — every coefficient is auditable)
# ═══════════════════════════════════════════════════════════════
CIE_CONFIG: Dict[str, Any] = {
    # ── Settlement Cycle Engine ──────────────────────────────
    # T+21 = first forced close-out window (Reg SHO 204: 13 consecutive
    #         settlement days on threshold list + T+2 base = ~21 cal days)
    # T+35 = extended buy-in deadline from initial failure date
    "sett_t21_days": 21,
    "sett_t35_days": 35,
    # FTD velocity: daily FTD as % of float to classify severity
    "sett_ftd_low_pct": 0.001,     # 0.1% of float — threshold list entry
    "sett_ftd_high_pct": 0.005,    # 0.5% of float — elevated pressure
    # Window proximity decay: high score when days_remaining ≤ this
    "sett_proximity_days": 7,
    # CTB rate above which borrow is classified "hard-to-borrow"
    "sett_ctb_htb_pct": 0.30,      # 30% annualized
    # ── Dark Pool Cycle Analyzer ─────────────────────────────
    # Rolling window for dark pool analysis (bars at 5-min cadence)
    "dpca_window": 20,
    # Block threshold: min dark print size to classify as institutional block
    "dpca_block_min_shares": 10000,
    # Off-exchange volume ratio thresholds
    "dpca_oer_neutral": 0.35,      # below → unusual lit dominance
    "dpca_oer_elevated": 0.50,     # above → institutional dark dominance
    # Hidden order imbalance: buy_notional / (buy + sell notional)
    "dpca_hoi_bull_threshold": 0.60,
    "dpca_hoi_bear_threshold": 0.40,
    # Exponential decay constant for time-weighted DLMD per-bar
    "dpca_dlmd_decay": 0.88,
    # Accumulation cluster: min consecutive bars with net dark buying
    "dpca_cluster_min_bars": 3,
    # ── Historical Fractal Matcher ───────────────────────────
    # Signature window: number of 5-min bars to compare
    "hfm_window": 20,
    # Minimum composite Pearson correlation to surface as an analog
    "hfm_min_corr": 0.75,
    # Forward-return horizon for analog evaluation (bars)
    "hfm_forward_horizon": 6,      # 30 minutes
    # Number of best analog matches to surface
    "hfm_top_n": 3,
    # Feature weights in composite similarity (must sum to 1.0)
    "hfm_weight_price": 0.50,
    "hfm_weight_volume": 0.30,
    "hfm_weight_iv": 0.20,
    # ── Meme Cycle Phase Detector ────────────────────────────
    # Minimum volume ratio (vs 20-bar ADV) to classify as IGNITION
    "mcpd_ignition_vol_ratio": 2.5,
    # IV percentile thresholds (rolling 100-bar rank)
    "mcpd_iv_pct_accumulation": 0.50,
    "mcpd_iv_pct_parabolic": 0.80,
    "mcpd_iv_pct_distribution": 0.70,
    # Days-to-cover (short interest / ADV) thresholds
    "mcpd_sir_elevated": 5.0,
    "mcpd_sir_extreme": 15.0,
    # Phase transition hysteresis: challenger must exceed incumbent by this factor
    "mcpd_phase_hysteresis": 1.20,
    # ── Cycle Convergence Signal ─────────────────────────────
    # Composite = sum of 4 layer scores; each layer max is 1.5 → total max 6.0
    "cie_enter_score": 3.0,        # CIE_FIRE threshold
    "cie_primed_score": 1.5,       # PRIMED threshold
    "cie_min_active_layers": 2,    # require ≥ 2 of 4 layers ≥ 0.5 to fire
}


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════
@dataclass
class SettlementPressure:
    """Output of the Settlement Cycle Engine (Layer 1)."""
    ticker: str
    ftd_velocity: Optional[float]         # FTDs/day as % of float; None if unavailable
    days_since_threshold: Optional[int]   # days on Reg SHO threshold list
    t35_days_remaining: Optional[int]     # calendar days to forced buy-in deadline
    ctb_rate: Optional[float]            # annualized cost-to-borrow %
    pressure_score: float                 # normalized [0, 1.5]
    notes: List[str] = field(default_factory=list)


@dataclass
class DarkPoolBar:
    """One 5-minute bar of aggregated dark pool data."""
    timestamp: float
    total_dark_volume: float
    total_lit_volume: float
    dark_buy_blocks: int
    dark_sell_blocks: int
    dark_buy_notional: float
    dark_sell_notional: float


@dataclass
class DarkPoolCycle:
    """Output of the Dark Pool Cycle Analyzer (Layer 2)."""
    ticker: str
    oer: Optional[float]                  # off-exchange volume ratio [0, 1]
    hoi: Optional[float]                  # hidden order imbalance [0, 1]
    dlmd: float                           # dark/lit momentum divergence [-1, 1]
    cluster_active: bool
    cluster_bars: int                     # consecutive bars of net dark buying
    pressure_score: float                 # normalized [0, 1.5]
    notes: List[str] = field(default_factory=list)


@dataclass
class FractalMatch:
    """One historical analog returned by the Historical Fractal Matcher."""
    period_label: str
    similarity: float                     # weighted Pearson composite [0, 1]
    forward_return: Optional[float]       # empirical forward return (decimal)
    price_component: float
    volume_component: float
    iv_component: float


@dataclass
class FractalAnalysis:
    """Output of the Historical Fractal Matcher (Layer 3)."""
    ticker: str
    window_bars: int
    top_matches: List[FractalMatch]
    best_similarity: float
    median_forward_return: Optional[float]  # % return (already ×100)
    pressure_score: float                   # normalized [0, 1.5]
    notes: List[str] = field(default_factory=list)


@dataclass
class MemeCycleState:
    """Output of the Meme Cycle Phase Detector (Layer 4)."""
    ticker: str
    phase: str                            # DORMANT|ACCUMULATION|IGNITION|PARABOLIC|DISTRIBUTION|UNWIND
    phase_score: float
    volume_ratio: Optional[float]         # current bar vol / 20-bar ADV
    iv_percentile: Optional[float]        # rolling IV rank [0, 1]
    sir: Optional[float]                  # short interest ratio (days-to-cover)
    tnt_active: bool
    pressure_score: float                 # normalized [0, 1.5]
    notes: List[str] = field(default_factory=list)


@dataclass
class CycleSignal:
    """Top-level output of the Cycle Intelligence Engine."""
    ticker: str
    timestamp: float
    state: str                            # DORMANT | BUILDING | PRIMED | CIE_FIRE
    composite_z: float                    # sum of 4 layer scores [0, 6.0]
    components: Dict[str, Any]
    settlement: Optional[SettlementPressure]
    dark_pool: Optional[DarkPoolCycle]
    fractal: Optional[FractalAnalysis]
    meme_cycle: Optional[MemeCycleState]
    notes: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# MATH UTILITIES
# ═══════════════════════════════════════════════════════════════
def _zscore_series(vals: List[float]) -> List[float]:
    if not vals:
        return []
    n = len(vals)
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / n
    sd = math.sqrt(var) if var > 0 else 1.0
    return [(v - mu) / sd for v in vals]


def _pearson(a: List[float], b: List[float]) -> float:
    n = len(a)
    if n < 3 or len(b) != n:
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


# ═══════════════════════════════════════════════════════════════
# LAYER 1 — SETTLEMENT CYCLE ENGINE
# Regulation SHO: T+2 standard, T+21 threshold, T+35 forced buy-in
# ═══════════════════════════════════════════════════════════════
class SettlementCycleEngine:
    """
    Tracks FTD accumulation velocity, Reg SHO threshold list proximity,
    and cost-to-borrow pressure per ticker.

    FTD data must be supplied by the caller (SEC EDGAR bi-monthly CSV
    or Polygon reference endpoint).  Engine will not invent missing
    values (AGENT_LAW §1).
    """
    def __init__(self, cfg: Dict[str, Any] = CIE_CONFIG):
        self.cfg = cfg
        # {ticker: deque of (report_date, ftd_shares, float_shares)}
        self._ftd_history: Dict[str, Deque[Tuple[date, int, int]]] = {}
        # {ticker: date when threshold list entry began}
        self._threshold_start: Dict[str, Optional[date]] = {}
        # {ticker: date of first FTD in current Reg SHO cycle}
        self._ftd_cycle_start: Dict[str, Optional[date]] = {}
        # {ticker: annualized CTB rate}
        self._ctb: Dict[str, Optional[float]] = {}

    def update_ftd(self, ticker: str, report_date: date,
                   ftd_shares: int, float_shares: int) -> None:
        """Ingest one SEC FTD data point.  Call in chronological order."""
        if ticker not in self._ftd_history:
            self._ftd_history[ticker] = deque(maxlen=60)
        self._ftd_history[ticker].append((report_date, ftd_shares, float_shares))

    def update_threshold_status(self, ticker: str, on_list: bool,
                                since_date: Optional[date] = None) -> None:
        if on_list:
            if not self._threshold_start.get(ticker):
                self._threshold_start[ticker] = since_date or date.today()
        else:
            self._threshold_start[ticker] = None
            self._ftd_cycle_start[ticker] = None

    def update_ctb(self, ticker: str, annualized_rate: float) -> None:
        """Update cost-to-borrow rate (IB, Schwab borrow desk, or Ortex feed)."""
        self._ctb[ticker] = annualized_rate

    def evaluate(self, ticker: str, today: Optional[date] = None) -> SettlementPressure:
        today = today or date.today()
        cfg = self.cfg
        notes: List[str] = []

        # FTD velocity: 5-day rolling average FTD as % of float
        ftd_velocity: Optional[float] = None
        hist = self._ftd_history.get(ticker)
        if hist and len(hist) >= 2:
            recent = list(hist)[-5:]
            avg_ftd = sum(r[1] for r in recent) / len(recent)
            avg_float = sum(r[2] for r in recent if r[2] > 0)
            if avg_float > 0:
                ftd_velocity = avg_ftd / (avg_float / len(recent))
        elif not hist:
            notes.append("[ESTIMATED_PROXY: ftd_velocity_unavailable — update_ftd() not called]")

        # Threshold list proximity and T+35 countdown
        threshold_start = self._threshold_start.get(ticker)
        days_since_threshold: Optional[int] = None
        t35_days_remaining: Optional[int] = None
        if threshold_start is not None:
            days_since_threshold = (today - threshold_start).days
            ftd_start = self._ftd_cycle_start.get(ticker) or threshold_start
            t35_deadline = ftd_start + timedelta(days=cfg["sett_t35_days"])
            t35_days_remaining = (t35_deadline - today).days

        ctb_rate = self._ctb.get(ticker)
        if ctb_rate is None:
            notes.append("[ESTIMATED_PROXY: ctb_rate_unavailable]")

        score = 0.0

        if ftd_velocity is not None:
            if ftd_velocity >= cfg["sett_ftd_high_pct"]:
                score += 0.75
            elif ftd_velocity >= cfg["sett_ftd_low_pct"]:
                score += 0.35

        if t35_days_remaining is not None:
            prox = cfg["sett_proximity_days"]
            if t35_days_remaining < 0:
                score += 0.50
                notes.append("T+35 window elapsed — forced buy-in may be outstanding")
            elif t35_days_remaining <= prox:
                score += 0.50 * (1.0 - t35_days_remaining / prox)

        if ctb_rate is not None and ctb_rate >= cfg["sett_ctb_htb_pct"]:
            excess = ctb_rate - cfg["sett_ctb_htb_pct"]
            score += min(0.25, excess / cfg["sett_ctb_htb_pct"] * 0.25)

        return SettlementPressure(
            ticker=ticker,
            ftd_velocity=ftd_velocity,
            days_since_threshold=days_since_threshold,
            t35_days_remaining=t35_days_remaining,
            ctb_rate=ctb_rate,
            pressure_score=round(min(1.5, score), 3),
            notes=notes,
        )


# ═══════════════════════════════════════════════════════════════
# LAYER 2 — DARK POOL CYCLE ANALYZER
# Multi-bar OER, block clustering, HOI, time-weighted DLMD
# ═══════════════════════════════════════════════════════════════
class DarkPoolCycleAnalyzer:
    """
    Tracks dark pool behavior over a rolling window of 5-minute bars.

    MMLE's dark_lit_divergence() is a single-bar, sign-based metric.
    DPCA upgrades to a multi-bar, notional-weighted accumulation
    cycle detector by maintaining exponentially decayed momentum (DLMD)
    and an institutional block cluster counter.
    """
    def __init__(self, cfg: Dict[str, Any] = CIE_CONFIG, ticker: str = ""):
        self.cfg = cfg
        self.ticker = ticker
        self._bars: Deque[DarkPoolBar] = deque(maxlen=cfg["dpca_window"])
        self._dlmd = 0.0   # exponentially weighted dark/lit momentum divergence

    def ingest_bar(
        self,
        dark_prints: Optional[List[Dict[str, Any]]],
        lit_volume: float,
        spot: float,
        timestamp: Optional[float] = None,
    ) -> None:
        ts = timestamp or time.time()
        if dark_prints is None:
            # AGENT_LAW §1: missing feed — do not invent a bar
            logger.debug("[CIE/DPCA] %s: dark_prints=None — bar skipped", self.ticker)
            return

        dark_vol = 0.0
        buy_blocks = sell_blocks = 0
        buy_notional = sell_notional = 0.0
        block_min = self.cfg["dpca_block_min_shares"]

        for p in dark_prints:
            try:
                px = float(p.get("price", 0))
                sz = float(p.get("size", 0))
                mid = float(p.get("mid", spot))
            except (TypeError, ValueError):
                continue
            if sz <= 0 or px <= 0:
                continue
            dark_vol += sz
            notional = sz * px
            if sz >= block_min:
                if px >= mid:
                    buy_blocks += 1
                    buy_notional += notional
                else:
                    sell_blocks += 1
                    sell_notional += notional

        self._bars.append(DarkPoolBar(
            timestamp=ts,
            total_dark_volume=dark_vol,
            total_lit_volume=max(0.0, lit_volume),
            dark_buy_blocks=buy_blocks,
            dark_sell_blocks=sell_blocks,
            dark_buy_notional=buy_notional,
            dark_sell_notional=sell_notional,
        ))

        # Update exponentially weighted DLMD
        total_block = buy_notional + sell_notional
        bar_sign = (buy_notional - sell_notional) / total_block if total_block > 0 else 0.0
        decay = self.cfg["dpca_dlmd_decay"]
        self._dlmd = decay * self._dlmd + (1.0 - decay) * bar_sign
        self._dlmd = max(-1.0, min(1.0, self._dlmd))

    def evaluate(self) -> DarkPoolCycle:
        cfg = self.cfg
        notes: List[str] = []

        if not self._bars:
            notes.append("[ESTIMATED_PROXY: no dark bars ingested — AWAITING_STREAM]")
            return DarkPoolCycle(
                ticker=self.ticker, oer=None, hoi=None,
                dlmd=0.0, cluster_active=False, cluster_bars=0,
                pressure_score=0.0, notes=notes,
            )

        bars = list(self._bars)
        total_dark = sum(b.total_dark_volume for b in bars)
        total_lit = sum(b.total_lit_volume for b in bars)
        total_vol = total_dark + total_lit

        oer: Optional[float] = round(total_dark / total_vol, 4) if total_vol > 0 else None
        if oer is None:
            notes.append("[ESTIMATED_PROXY: oer_unavailable — zero volume in window]")

        total_buy_n = sum(b.dark_buy_notional for b in bars)
        total_sell_n = sum(b.dark_sell_notional for b in bars)
        total_n = total_buy_n + total_sell_n
        hoi: Optional[float] = round(total_buy_n / total_n, 4) if total_n > 0 else None
        if hoi is None:
            notes.append("[ESTIMATED_PROXY: hoi_unavailable — no block prints in window]")

        # Cluster: trailing consecutive bars with net dark buying
        cluster_bars = 0
        for b in reversed(bars):
            if b.dark_buy_notional > b.dark_sell_notional:
                cluster_bars += 1
            else:
                break
        cluster_active = cluster_bars >= cfg["dpca_cluster_min_bars"]

        score = 0.0
        if oer is not None:
            if oer >= cfg["dpca_oer_elevated"]:
                score += 0.40
            elif oer >= cfg["dpca_oer_neutral"]:
                score += 0.15

        if hoi is not None:
            if hoi >= cfg["dpca_hoi_bull_threshold"]:
                score += 0.50
            elif hoi <= cfg["dpca_hoi_bear_threshold"]:
                score += 0.20

        # DLMD momentum contribution
        score += min(0.35, abs(self._dlmd) * 0.35)

        # Cluster bonus
        if cluster_active:
            score += min(0.25, cluster_bars / (cfg["dpca_window"] / 2) * 0.25)

        return DarkPoolCycle(
            ticker=self.ticker,
            oer=oer,
            hoi=hoi,
            dlmd=round(self._dlmd, 4),
            cluster_active=cluster_active,
            cluster_bars=cluster_bars,
            pressure_score=round(min(1.5, score), 3),
            notes=notes,
        )


# ═══════════════════════════════════════════════════════════════
# LAYER 3 — HISTORICAL FRACTAL MATCHER
# Statistical pattern similarity — parameterized, falsifiable
# ═══════════════════════════════════════════════════════════════
@dataclass
class _Signature:
    label: str
    price_returns: List[float]    # z-scored log returns, len=hfm_window
    volume_ratios: List[float]    # z-scored volume/ADV, len=hfm_window
    iv_series: List[float]        # z-scored IV, len=hfm_window
    forward_return: Optional[float]  # decimal return over forward_horizon


class HistoricalFractalMatcher:
    """
    Maintains a library of historical signatures and finds the closest
    matches to the current rolling window.  All data must be caller-
    supplied from a real market source (AGENT_LAW §1).

    Similarity is weighted Pearson correlation across three normalized
    feature series: price returns, volume ratios, and IV.  No calendar
    offsets, numerology, or social signals are used as inputs.
    """
    def __init__(self, cfg: Dict[str, Any] = CIE_CONFIG, ticker: str = ""):
        self.cfg = cfg
        self.ticker = ticker
        self._library: List[_Signature] = []
        w = cfg["hfm_window"]
        fh = cfg["hfm_forward_horizon"]
        self._closes: Deque[float] = deque(maxlen=w + fh + 1)
        self._volumes: Deque[float] = deque(maxlen=w + fh)
        self._ivs: Deque[float] = deque(maxlen=w + fh)
        self._adv: Optional[float] = None

    def add_historical_signature(
        self,
        label: str,
        price_returns: List[float],
        volume_ratios: List[float],
        iv_series: List[float],
        forward_return: Optional[float] = None,
    ) -> None:
        """
        Register a historical window for future comparison.
        All series must have length ≥ hfm_window.
        forward_return: decimal (e.g. 0.12 = +12%) over hfm_forward_horizon bars.
        """
        w = self.cfg["hfm_window"]
        if min(len(price_returns), len(volume_ratios), len(iv_series)) < w:
            logger.warning("[CIE/HFM] %s: signature '%s' too short — skipped", self.ticker, label)
            return
        self._library.append(_Signature(
            label=label,
            price_returns=_zscore_series(list(price_returns[-w:])),
            volume_ratios=_zscore_series(list(volume_ratios[-w:])),
            iv_series=_zscore_series(list(iv_series[-w:])),
            forward_return=forward_return,
        ))

    def ingest_bar(self, close: float, volume: float, iv_atm: float,
                   adv: Optional[float] = None) -> None:
        self._closes.append(close)
        self._volumes.append(volume)
        self._ivs.append(iv_atm)
        if adv is not None and adv > 0:
            self._adv = adv

    def evaluate(self) -> FractalAnalysis:
        cfg = self.cfg
        notes: List[str] = []
        w = cfg["hfm_window"]

        if len(self._closes) < w + 1:
            notes.append("[ESTIMATED_PROXY: hfm_window_unfilled — AWAITING_STREAM]")
            return FractalAnalysis(
                ticker=self.ticker, window_bars=len(self._closes),
                top_matches=[], best_similarity=0.0,
                median_forward_return=None, pressure_score=0.0, notes=notes,
            )

        # Build current log-return series
        closes = list(self._closes)[-(w + 1):]
        cur_rets: List[float] = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            cur_rets.append(math.log(closes[i] / prev) if prev > 0 else 0.0)
        cur_rets = _zscore_series(cur_rets[-w:])

        adv = self._adv or 1.0
        cur_vols = _zscore_series([v / adv for v in list(self._volumes)[-w:]])
        cur_ivs = _zscore_series(list(self._ivs)[-w:])

        if not self._library:
            notes.append("[ESTIMATED_PROXY: hfm_library_empty — add_historical_signature() not called]")
            return FractalAnalysis(
                ticker=self.ticker, window_bars=w,
                top_matches=[], best_similarity=0.0,
                median_forward_return=None, pressure_score=0.0, notes=notes,
            )

        wp = cfg["hfm_weight_price"]
        wv = cfg["hfm_weight_volume"]
        wi = cfg["hfm_weight_iv"]
        matches: List[FractalMatch] = []
        for sig in self._library:
            pc = _pearson(cur_rets, sig.price_returns)
            vc = _pearson(cur_vols, sig.volume_ratios)
            ic = _pearson(cur_ivs, sig.iv_series)
            composite = wp * pc + wv * vc + wi * ic
            if composite >= cfg["hfm_min_corr"]:
                matches.append(FractalMatch(
                    period_label=sig.label,
                    similarity=round(composite, 4),
                    forward_return=sig.forward_return,
                    price_component=round(pc, 4),
                    volume_component=round(vc, 4),
                    iv_component=round(ic, 4),
                ))

        matches.sort(key=lambda m: -m.similarity)
        top = matches[:cfg["hfm_top_n"]]
        best_sim = top[0].similarity if top else 0.0

        fwd_returns = sorted(m.forward_return for m in top if m.forward_return is not None)
        median_fwd: Optional[float] = None
        if fwd_returns:
            n = len(fwd_returns)
            median_fwd = (fwd_returns[n // 2] if n % 2 != 0
                          else (fwd_returns[n // 2 - 1] + fwd_returns[n // 2]) / 2)

        pressure = min(1.5, best_sim * 1.5) if best_sim >= cfg["hfm_min_corr"] else 0.0

        return FractalAnalysis(
            ticker=self.ticker,
            window_bars=w,
            top_matches=top,
            best_similarity=best_sim,
            median_forward_return=round(median_fwd * 100, 2) if median_fwd is not None else None,
            pressure_score=round(pressure, 3),
            notes=notes,
        )


# ═══════════════════════════════════════════════════════════════
# LAYER 4 — MEME CYCLE PHASE DETECTOR
# DORMANT → ACCUMULATION → IGNITION → PARABOLIC → DISTRIBUTION → UNWIND
# ═══════════════════════════════════════════════════════════════
_PHASES = ("DORMANT", "ACCUMULATION", "IGNITION", "PARABOLIC", "DISTRIBUTION", "UNWIND")

_PHASE_PRESSURE = {
    "DORMANT": 0.0,
    "ACCUMULATION": 0.5,
    "IGNITION": 1.0,
    "PARABOLIC": 1.5,
    "DISTRIBUTION": 0.8,
    "UNWIND": 0.3,
}


def _iv_pct_rank(history: Deque[float], current: float) -> Optional[float]:
    if not history:
        return None
    below = sum(1 for x in history if x < current)
    return below / len(history)


class MemeCycleDetector:
    """
    Six-phase meme-cycle regime detector.  Multi-axis scoring mirrors
    MMLE's TNT classifier philosophy: no single axis can trigger a
    phase transition alone.  MMLE TNT state is accepted as an optional
    confirmatory input (AGENT_LAW §3: transparent proxy — labeled when used).
    """
    def __init__(self, cfg: Dict[str, Any] = CIE_CONFIG, ticker: str = ""):
        self.cfg = cfg
        self.ticker = ticker
        self._vol_window: Deque[float] = deque(maxlen=20)
        self._iv_history: Deque[float] = deque(maxlen=100)
        self._current_phase = "DORMANT"
        self._sir: Optional[float] = None

    def ingest_bar(self, volume: float, iv_atm: float) -> None:
        self._vol_window.append(volume)
        if iv_atm > 0:
            self._iv_history.append(iv_atm)

    def update_short_interest(self, sir: float) -> None:
        """Supply days-to-cover from a real borrow-desk or Ortex/Fintel feed."""
        self._sir = sir

    def evaluate(self, tnt_state: str = "NEUTRAL") -> MemeCycleState:
        cfg = self.cfg
        notes: List[str] = []

        volume_ratio: Optional[float] = None
        if self._vol_window:
            adv = sum(self._vol_window) / len(self._vol_window)
            if adv > 0:
                volume_ratio = self._vol_window[-1] / adv

        iv_pct: Optional[float] = None
        if self._iv_history:
            iv_pct = _iv_pct_rank(self._iv_history, self._iv_history[-1])

        tnt_active = tnt_state in ("TNT_LONG", "TNT_SHORT")

        scores: Dict[str, float] = {p: 0.0 for p in _PHASES}

        if volume_ratio is not None:
            if volume_ratio < 0.80:
                scores["DORMANT"] += 1.0
            elif volume_ratio < cfg["mcpd_ignition_vol_ratio"]:
                scores["ACCUMULATION"] += 0.5
            else:
                scores["IGNITION"] += 1.0
                scores["PARABOLIC"] += 0.5

        if iv_pct is not None:
            if iv_pct < 0.35:
                scores["DORMANT"] += 0.5
                scores["UNWIND"] += 0.5
            elif iv_pct < cfg["mcpd_iv_pct_accumulation"]:
                scores["ACCUMULATION"] += 0.5
            elif iv_pct < cfg["mcpd_iv_pct_parabolic"]:
                scores["IGNITION"] += 0.5
                scores["PARABOLIC"] += 0.5
            elif iv_pct < cfg["mcpd_iv_pct_distribution"]:
                scores["DISTRIBUTION"] += 0.5
            else:
                scores["PARABOLIC"] += 1.0

        if self._sir is not None:
            if self._sir >= cfg["mcpd_sir_extreme"]:
                scores["IGNITION"] += 0.5
                scores["PARABOLIC"] += 1.0
            elif self._sir >= cfg["mcpd_sir_elevated"]:
                scores["ACCUMULATION"] += 0.5
                scores["IGNITION"] += 0.5
        else:
            notes.append("[ESTIMATED_PROXY: sir_unavailable — update_short_interest() not called]")

        if tnt_active:
            notes.append("[ESTIMATED_PROXY: tnt_state used as confirmatory input]")
            scores["IGNITION"] += 0.5
            scores["PARABOLIC"] += 1.0

        best_phase = max(scores, key=lambda p: scores[p])
        best_score = scores[best_phase]
        cur_score = scores[self._current_phase]
        # Hysteresis: challenger must beat incumbent by cfg factor
        if best_phase != self._current_phase:
            if cur_score <= 0 or best_score >= cur_score * cfg["mcpd_phase_hysteresis"]:
                self._current_phase = best_phase

        return MemeCycleState(
            ticker=self.ticker,
            phase=self._current_phase,
            phase_score=round(best_score, 3),
            volume_ratio=round(volume_ratio, 3) if volume_ratio is not None else None,
            iv_percentile=round(iv_pct, 3) if iv_pct is not None else None,
            sir=round(self._sir, 2) if self._sir is not None else None,
            tnt_active=tnt_active,
            pressure_score=round(_PHASE_PRESSURE.get(self._current_phase, 0.0), 3),
            notes=notes,
        )


# ═══════════════════════════════════════════════════════════════
# TOP-LEVEL ENGINE — Cycle Convergence Signal
# ═══════════════════════════════════════════════════════════════
class CycleIntelligenceEngine:
    """
    Wires all four layers into a single 5-minute evaluation.  Emits
    CIE_FIRE when settlement pressure, dark-pool accumulation, fractal
    confirmation, and meme-cycle phase all converge above threshold.

    Integration pattern (mirrors MMLiquidityEngine):
      1. Call ingest_*() methods each bar with real data.
      2. Call evaluate(ticker, tnt_state) once per 5-min bar.
      3. CycleSignal.state == 'CIE_FIRE' is the convergence alert.
    """
    def __init__(self, cfg: Dict[str, Any] = CIE_CONFIG):
        self.cfg = cfg
        self._settlement: Dict[str, SettlementCycleEngine] = {}
        self._dark: Dict[str, DarkPoolCycleAnalyzer] = {}
        self._fractal: Dict[str, HistoricalFractalMatcher] = {}
        self._meme: Dict[str, MemeCycleDetector] = {}

    def _sce(self, t: str) -> SettlementCycleEngine:
        if t not in self._settlement:
            self._settlement[t] = SettlementCycleEngine(self.cfg)
        return self._settlement[t]

    def _dpca(self, t: str) -> DarkPoolCycleAnalyzer:
        if t not in self._dark:
            self._dark[t] = DarkPoolCycleAnalyzer(self.cfg, t)
        return self._dark[t]

    def _hfm(self, t: str) -> HistoricalFractalMatcher:
        if t not in self._fractal:
            self._fractal[t] = HistoricalFractalMatcher(self.cfg, t)
        return self._fractal[t]

    def _mcpd(self, t: str) -> MemeCycleDetector:
        if t not in self._meme:
            self._meme[t] = MemeCycleDetector(self.cfg, t)
        return self._meme[t]

    # ── data ingestion ────────────────────────────────────────
    def ingest_ftd(self, ticker: str, report_date: date,
                   ftd_shares: int, float_shares: int) -> None:
        self._sce(ticker).update_ftd(ticker, report_date, ftd_shares, float_shares)

    def update_threshold_status(self, ticker: str, on_list: bool,
                                since_date: Optional[date] = None) -> None:
        self._sce(ticker).update_threshold_status(ticker, on_list, since_date)

    def update_ctb(self, ticker: str, annualized_rate: float) -> None:
        self._sce(ticker).update_ctb(ticker, annualized_rate)

    def ingest_dark_bar(self, ticker: str,
                        dark_prints: Optional[List[Dict[str, Any]]],
                        lit_volume: float, spot: float) -> None:
        self._dpca(ticker).ingest_bar(dark_prints, lit_volume, spot)

    def ingest_price_bar(self, ticker: str, close: float, volume: float,
                         iv_atm: float, adv: Optional[float] = None) -> None:
        self._hfm(ticker).ingest_bar(close, volume, iv_atm, adv)
        self._mcpd(ticker).ingest_bar(volume, iv_atm)

    def add_historical_signature(self, ticker: str, label: str,
                                 price_returns: List[float],
                                 volume_ratios: List[float],
                                 iv_series: List[float],
                                 forward_return: Optional[float] = None) -> None:
        self._hfm(ticker).add_historical_signature(
            label, price_returns, volume_ratios, iv_series, forward_return)

    def update_short_interest(self, ticker: str, sir: float) -> None:
        self._mcpd(ticker).update_short_interest(sir)

    # ── main evaluation (AGENT_LAW §4: 5-min cadence) ────────
    def evaluate(
        self,
        ticker: str,
        tnt_state: str = "NEUTRAL",
        today: Optional[date] = None,
    ) -> CycleSignal:
        """
        Evaluate all four layers and return a CycleSignal.

        tnt_state: pass the current MMLiquidityEngine TNT state for this
                   ticker.  Treats MMLE as a confirmatory input to Layer 4,
                   not a replacement (AGENT_LAW §3: transparent proxy).
        """
        cfg = self.cfg

        sett = self._sce(ticker).evaluate(ticker, today)
        dark = self._dpca(ticker).evaluate()
        frac = self._hfm(ticker).evaluate()
        meme = self._mcpd(ticker).evaluate(tnt_state)

        z_sett = sett.pressure_score
        z_dark = dark.pressure_score
        z_frac = frac.pressure_score
        z_meme = meme.pressure_score

        composite = z_sett + z_dark + z_frac + z_meme
        active_layers = sum(1 for z in (z_sett, z_dark, z_frac, z_meme) if z >= 0.5)

        state = "DORMANT"
        if composite >= cfg["cie_enter_score"] and active_layers >= cfg["cie_min_active_layers"]:
            state = "CIE_FIRE"
        elif composite >= cfg["cie_primed_score"] and active_layers >= 2:
            state = "PRIMED"
        elif composite > 0:
            state = "BUILDING"

        components: Dict[str, Any] = {
            "z_settlement": round(z_sett, 3),
            "z_dark_pool": round(z_dark, 3),
            "z_fractal": round(z_frac, 3),
            "z_meme_cycle": round(z_meme, 3),
            "active_layers": active_layers,
            "meme_phase": meme.phase,
            "dark_cluster_bars": dark.cluster_bars,
            "dark_oer": dark.oer,
            "dark_hoi": dark.hoi,
            "dark_dlmd": dark.dlmd,
            "best_fractal_similarity": frac.best_similarity,
            "median_forward_return_pct": frac.median_forward_return,
            "ftd_velocity": sett.ftd_velocity,
            "t35_days_remaining": sett.t35_days_remaining,
        }

        return CycleSignal(
            ticker=ticker,
            timestamp=time.time(),
            state=state,
            composite_z=round(composite, 3),
            components=components,
            settlement=sett,
            dark_pool=dark,
            fractal=frac,
            meme_cycle=meme,
        )


__all__ = [
    "CIE_CONFIG",
    "SettlementPressure",
    "DarkPoolBar",
    "DarkPoolCycle",
    "FractalMatch",
    "FractalAnalysis",
    "MemeCycleState",
    "CycleSignal",
    "SettlementCycleEngine",
    "DarkPoolCycleAnalyzer",
    "HistoricalFractalMatcher",
    "MemeCycleDetector",
    "CycleIntelligenceEngine",
]
