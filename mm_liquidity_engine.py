"""
SQUEEZE OS — MM Liquidity Engine (MMLE) v1.0
══════════════════════════════════════════════════════════════════════
Closed-loop dealer-stress capture: Vanna/Charm cross-derivative fusion,
VPIN flow toxicity, dark/lit divergence, and liquidity-void mapping.

The "Asymmetric Variable":
    Vanna/Charm Sign Concordance with Gamma (VCSC_Γ)
When VCSC_Γ > 0.70 AND aggregate dealer Γ < threshold, the dealer hedge
book enters the Triple-Negative Trap (TNT) regime: price, vol, and time
all force the same direction of underlying purchase/sale. Price then
magnetizes to the nearest large-OI wall on the trapped side, traversing
the liquidity void with mechanical inevitability.

Governance:
    Bound by AGENT_LAW.md
      - Law 1: NO simulated data — pause if chain/quotes missing.
      - Law 2: parameterized alpha factors — every coefficient in MMLE_CONFIG.
      - Law 3: transparent proxies — labeled [ESTIMATED_PROXY: ...].
      - Law 4: 5-min institutional cadence preserved.

Reference: MM_LIQUIDITY_ENGINE_MANIFEST.md
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION (AGENT_LAW §2 — every coefficient is auditable)
# ═══════════════════════════════════════════════════════════════
MMLE_CONFIG: Dict[str, Any] = {
    # OTM band for VCSC_Γ aggregation (fraction around spot)
    "vcsc_band_pct": 0.15,
    # TNT regime gate — minimum sign-concordance fraction
    "vcsc_min": 0.70,
    # Dealer aggregate gamma threshold expressed as $-gamma per dollar of
    # daily notional flow (= |gex| / (spot · ADV · 1%)). Scale-invariant
    # across SPY-tier liquidity and small-cap meme tickers.
    "gamma_per_notional_min": 0.001,
    # VPIN — volume bucket size as fraction of ADV; bucket window for σ
    "vpin_bucket_vol_pct": 0.005,
    "vpin_window": 50,
    # Liquidity void — minimum gap width in ATR multiples
    "void_atr_mult": 1.5,
    # TNT composite scoring (post-normalization each feature ∈ [0, 1.5])
    "tnt_enter_score": 3.0,           # sum across 5 features, max 7.5
    "tnt_exit_score": 1.5,
    "tnt_min_active_axes": 3,         # require ≥ 3 of 5 features ≥ 0.5
    # Vanna-Charm Convergence Window: front-month DTE max + intraday window
    "vccw_dte_max": 3,
    "vccw_minute_open": 585,   # 09:45 ET
    "vccw_minute_close": 930,  # 15:30 ET
    # Risk-free rate proxy (used in BS Greeks)
    "rf_rate": 0.04,
    # Iceberg execution profile (consumed by execution_engine)
    "iceberg_slice_pct": 0.08,
    "iceberg_jitter_ms": (800, 2200),
    # Dealer positioning assumption (overrideable per-symbol)
    "dealer_call_short_assumption": True,
    # Cosine-similarity gate on F_axis components (math gotcha §3)
    "axis_collapse_cos": 0.85,
}


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════
@dataclass
class StrikeGreeks:
    strike: float
    dte: int
    gamma: float       # per-share
    vanna: float       # per-share, dDelta/dσ
    charm: float       # per-share, dDelta/dτ (per-day)
    oi: int
    iv: float


@dataclass
class DealerSurface:
    ticker: str
    spot: float
    timestamp: float
    by_strike: Dict[float, Dict[str, float]] = field(default_factory=dict)
    gex_total: float = 0.0
    vex_total: float = 0.0
    cex_total: float = 0.0
    vcsc_gamma: float = 0.0      # the Asymmetric Variable
    iv_atm: float = 0.0
    walls: Dict[str, float] = field(default_factory=dict)  # call_wall, put_wall


@dataclass
class FlowToxicity:
    vpin: Optional[float]                 # 0..1; None if window unfilled
    vpin_z: Optional[float]
    dark_lit_divergence: Optional[float]  # signed [-1, 1]; None if dark feed missing


@dataclass
class LiquidityVoid:
    lower_wall: float
    upper_wall: float
    width: float
    width_in_atr: float
    contains_spot: bool


@dataclass
class TNTSignal:
    ticker: str
    timestamp: float
    state: str                       # NEUTRAL | COMPRESSED | TNT_LONG | TNT_SHORT | AWAITING_STREAM
    composite_z: float
    components: Dict[str, float]
    target_magnet: Optional[float]   # strike to magnetize toward
    expected_traverse_minutes: Optional[float]
    void: Optional[LiquidityVoid]
    notes: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# BLACK-SCHOLES CROSS-DERIVATIVES
# (Γ already in gamma_flow_engine.estimate_gamma; we add Vanna and Charm
#  here to keep the MMLE module self-contained.)
# ═══════════════════════════════════════════════════════════════
SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> Tuple[float, float]:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        raise ValueError("invalid BS inputs")
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    try:
        d1, _ = _d1_d2(S, K, T, r, sigma)
        return _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def bs_vanna(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """∂Δ/∂σ  =  −φ(d1) · d2 / σ  (per-share, per 1.0 vol-point)."""
    try:
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        return -_norm_pdf(d1) * d2 / sigma
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def bs_charm(S: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    """∂Δ/∂τ in per-day units (τ = calendar days; sign convention: τ flows forward)."""
    try:
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        sqrt_T = math.sqrt(T)
        # Standard Hull (Options, Futures, and Other Derivatives) charm:
        #   call_charm = -φ(d1) * (2(r) T - d2 σ √T) / (2 T σ √T)
        # Convert annualized to per-day by dividing by 365.
        common = -_norm_pdf(d1) * (2.0 * r * T - d2 * sigma * sqrt_T) / (2.0 * T * sigma * sqrt_T)
        if not is_call:
            # put charm differs by the sign of the q/r adjustment; for q=0 the
            # formula is identical except for the sign of the first term.
            common = common  # equivalent for q=0; explicit to document intent
        return common / 365.0
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


# ═══════════════════════════════════════════════════════════════
# DEALER SURFACE BUILDER
# Sign convention (DEALER perspective):
#   default — dealers short calls, long puts. Overrideable per-symbol.
# ═══════════════════════════════════════════════════════════════
def _dealer_sign(opt_type: str, call_short: bool) -> int:
    if opt_type.upper() == "CALL":
        return -1 if call_short else +1
    return +1 if call_short else -1   # put side mirrors


def build_dealer_surface(
    raw_chain: Dict[str, Any],
    spot: float,
    ticker: str = "",
    cfg: Dict[str, Any] = MMLE_CONFIG,
) -> Optional[DealerSurface]:
    """
    Construct dealer Γ/Vanna/Charm surface from a raw Schwab option chain.
    Returns None when the chain is incomplete (AGENT_LAW §1.1: pause, never invent).
    """
    if not raw_chain or spot <= 0:
        logger.warning("[MMLE] %s: empty chain or invalid spot — AWAITING_STREAM", ticker)
        return None

    call_map = raw_chain.get("callExpDateMap") or {}
    put_map = raw_chain.get("putExpDateMap") or {}
    if not call_map and not put_map:
        logger.warning("[MMLE] %s: chain missing call/put maps — AWAITING_STREAM", ticker)
        return None

    band = cfg["vcsc_band_pct"]
    s_lo, s_hi = spot * (1.0 - band), spot * (1.0 + band)
    rf = cfg["rf_rate"]
    call_short = cfg["dealer_call_short_assumption"]

    by_strike: Dict[float, Dict[str, float]] = {}
    iv_atm_samples: List[float] = []
    today = datetime.now(timezone.utc).date()

    def _ingest(opt_map: Dict[str, Any], opt_type: str) -> None:
        for expiry_key, strikes in opt_map.items():
            if ":" not in expiry_key:
                continue
            try:
                expiry = datetime.strptime(expiry_key.split(":")[0], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            dte = (expiry - today).days
            if dte < 0:
                continue
            T = max(1.0 / 365.0, dte / 365.0)
            sign = _dealer_sign(opt_type, call_short)
            is_call = opt_type.upper() == "CALL"

            for strike_str, contracts in strikes.items():
                try:
                    K = float(strike_str)
                except (ValueError, TypeError):
                    continue
                if not (s_lo <= K <= s_hi):
                    continue
                for opt in contracts or []:
                    if not isinstance(opt, dict):
                        continue
                    oi = int(opt.get("openInterest", 0) or 0)
                    if oi <= 0:
                        continue
                    iv_raw = float(opt.get("volatility", 0) or 0) / 100.0
                    if iv_raw <= 0:
                        # AGENT_LAW §3.1 — labeled proxy: skip rather than invent
                        logger.debug("[MMLE][ESTIMATED_PROXY: iv_missing] %s K=%.2f skipped",
                                     ticker, K)
                        continue

                    g = float(opt.get("gamma", 0) or 0)
                    if g <= 0:
                        g = bs_gamma(spot, K, T, rf, iv_raw)
                    v = bs_vanna(spot, K, T, rf, iv_raw)
                    ch = bs_charm(spot, K, T, rf, iv_raw, is_call)

                    # Dollar exposures per 1% spot move (notional convention
                    # consistent with gamma_flow_engine.option_gex).
                    mult = 100
                    gex = sign * g * oi * mult * (spot ** 2) * 0.01
                    # Vanna $ exposure per 1 vol-point: VEX = Vanna · OI · 100 · S
                    vex = sign * v * oi * mult * spot
                    # Charm $ exposure per day: CEX = Charm · OI · 100 · S
                    cex = sign * ch * oi * mult * spot

                    bucket = by_strike.setdefault(K, {
                        "gex": 0.0, "vex": 0.0, "cex": 0.0,
                        "oi": 0, "abs_g_oi": 0.0,
                        "sign_g": 0, "sign_v": 0, "sign_c": 0,
                    })
                    bucket["gex"] += gex
                    bucket["vex"] += vex
                    bucket["cex"] += cex
                    bucket["oi"] += oi
                    bucket["abs_g_oi"] += abs(g * oi)

                    if abs(K - spot) / spot < 0.025:
                        iv_atm_samples.append(iv_raw)

    _ingest(call_map, "CALL")
    _ingest(put_map, "PUT")

    if not by_strike:
        logger.warning("[MMLE] %s: no qualifying strikes after filters — AWAITING_STREAM", ticker)
        return None

    # Resolve sign per strike from net dollar exposures
    for K, b in by_strike.items():
        b["sign_g"] = 1 if b["gex"] > 0 else (-1 if b["gex"] < 0 else 0)
        b["sign_v"] = 1 if b["vex"] > 0 else (-1 if b["vex"] < 0 else 0)
        b["sign_c"] = 1 if b["cex"] > 0 else (-1 if b["cex"] < 0 else 0)

    # VCSC_Γ — the Asymmetric Variable
    num = 0.0
    den = 0.0
    for K, b in by_strike.items():
        w = b["abs_g_oi"]
        if w <= 0:
            continue
        concord = 1.0 if (b["sign_g"] != 0 and b["sign_g"] == b["sign_v"] == b["sign_c"]) else 0.0
        num += concord * w
        den += w
    vcsc = (num / den) if den > 0 else 0.0

    gex_total = sum(b["gex"] for b in by_strike.values())
    vex_total = sum(b["vex"] for b in by_strike.values())
    cex_total = sum(b["cex"] for b in by_strike.values())

    # Walls — largest absolute |GEX·OI| above/below spot
    above = sorted(((K, abs(b["gex"]) * b["oi"]) for K, b in by_strike.items() if K > spot),
                   key=lambda x: -x[1])
    below = sorted(((K, abs(b["gex"]) * b["oi"]) for K, b in by_strike.items() if K < spot),
                   key=lambda x: -x[1])
    walls = {
        "call_wall": above[0][0] if above else 0.0,
        "put_wall": below[0][0] if below else 0.0,
    }

    iv_atm = (sum(iv_atm_samples) / len(iv_atm_samples)) if iv_atm_samples else 0.0

    return DealerSurface(
        ticker=ticker,
        spot=spot,
        timestamp=time.time(),
        by_strike=by_strike,
        gex_total=gex_total,
        vex_total=vex_total,
        cex_total=cex_total,
        vcsc_gamma=vcsc,
        iv_atm=iv_atm,
        walls=walls,
    )


# ═══════════════════════════════════════════════════════════════
# VPIN — Easley/López de Prado, volume-clock buckets
# ═══════════════════════════════════════════════════════════════
class VPINTracker:
    """
    Streaming VPIN over a fixed bucket-volume V*. Each bucket aggregates trades
    until cumulative volume reaches V*; trades are signed via the Lee-Ready
    tick rule when no NBBO context is available.
    """
    def __init__(self, bucket_volume: float, window: int = 50):
        if bucket_volume <= 0:
            raise ValueError("bucket_volume must be > 0")
        self.bucket_volume = bucket_volume
        self.window: Deque[Tuple[float, float]] = deque(maxlen=window)  # (buy_vol, sell_vol)
        self._cur_buy = 0.0
        self._cur_sell = 0.0
        self._cur_total = 0.0
        self._last_price: Optional[float] = None
        self._vpin_history: Deque[float] = deque(maxlen=max(window * 4, 200))

    def add_trade(self, price: float, size: float, side: Optional[str] = None) -> None:
        if size <= 0 or price <= 0:
            return
        if side is None:
            # Tick rule classification
            if self._last_price is None:
                side = "buy"
            elif price > self._last_price:
                side = "buy"
            elif price < self._last_price:
                side = "sell"
            else:
                # Repeat — split evenly (Lee-Ready fallback)
                self._cur_buy += size / 2
                self._cur_sell += size / 2
                self._cur_total += size
                self._last_price = price
                self._roll()
                return
        self._last_price = price
        if side == "buy":
            self._cur_buy += size
        else:
            self._cur_sell += size
        self._cur_total += size
        self._roll()

    def _roll(self) -> None:
        while self._cur_total >= self.bucket_volume:
            # Allocate exactly one bucket from the tail of accumulators
            scale = self.bucket_volume / self._cur_total
            b = self._cur_buy * scale
            s = self._cur_sell * scale
            self.window.append((b, s))
            self._cur_buy -= b
            self._cur_sell -= s
            self._cur_total -= self.bucket_volume
            self._update_history()

    def _update_history(self) -> None:
        if not self.window:
            return
        num = sum(abs(b - s) for b, s in self.window)
        den = sum(b + s for b, s in self.window)
        if den > 0:
            self._vpin_history.append(num / den)

    def vpin(self) -> Optional[float]:
        if len(self.window) < self.window.maxlen:
            return None  # AGENT_LAW: don't invent — wait for window fill
        return self._vpin_history[-1] if self._vpin_history else None

    def vpin_z(self) -> Optional[float]:
        if len(self._vpin_history) < 30:
            return None
        vals = list(self._vpin_history)
        mu = sum(vals) / len(vals)
        var = sum((v - mu) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var) if var > 0 else 0.0
        if sd == 0 or self._vpin_history[-1] is None:
            return None
        return (self._vpin_history[-1] - mu) / sd


# ═══════════════════════════════════════════════════════════════
# DARK / LIT DIVERGENCE
# Dark print sign vs lit order-flow imbalance sign over the same bar.
# ═══════════════════════════════════════════════════════════════
def dark_lit_divergence(
    dark_prints: List[Dict[str, Any]],
    lit_ofi: float,
    spot: float,
) -> Optional[float]:
    """
    Returns a signed score in [-1, +1]:
      +1 — dark accumulation aligns long while lit shows short flow (bullish trap setup)
      -1 — dark distribution aligns short while lit shows long flow (bearish trap setup)
       0 — concordant (no divergence edge)
    None when the dark feed is missing (AGENT_LAW §3.1: must be labeled).
    """
    if dark_prints is None:
        return None
    if not dark_prints:
        # Empty list is *known empty*, not missing — return 0
        return 0.0

    # Sign each dark print: print at/above mid → buyer-initiated; below → seller
    buy = 0.0
    sell = 0.0
    for p in dark_prints:
        try:
            px = float(p.get("price", 0))
            sz = float(p.get("size", 0))
            mid = float(p.get("mid", spot))
        except (TypeError, ValueError):
            continue
        if sz <= 0 or px <= 0:
            continue
        if px >= mid:
            buy += sz
        else:
            sell += sz

    if buy + sell <= 0:
        return 0.0

    dark_sign = (buy - sell) / (buy + sell)         # [-1, 1]
    lit_sign = max(-1.0, min(1.0, lit_ofi))          # clamp
    # Divergence is positive when signs disagree and dark is positive
    if dark_sign == 0 or lit_sign == 0:
        return 0.0
    if (dark_sign > 0) and (lit_sign < 0):
        return dark_sign * abs(lit_sign)
    if (dark_sign < 0) and (lit_sign > 0):
        return dark_sign * abs(lit_sign)
    return 0.0  # concordant


# ═══════════════════════════════════════════════════════════════
# LIQUIDITY VOID MAP
# ═══════════════════════════════════════════════════════════════
def find_liquidity_void(
    surface: DealerSurface,
    atr: float,
    cfg: Dict[str, Any] = MMLE_CONFIG,
) -> Optional[LiquidityVoid]:
    if atr <= 0 or not surface.by_strike:
        return None
    if len(surface.by_strike) < 2:
        return None
    # Walls are ranked by |GEX|·OI — same metric as DealerSurface.walls so
    # void boundaries align with dealer hedge magnets.
    def _weight(b: Dict[str, float]) -> float:
        return abs(b["gex"]) * max(1, b["oi"])

    below = [(K, _weight(b)) for K, b in surface.by_strike.items() if K < surface.spot]
    above = [(K, _weight(b)) for K, b in surface.by_strike.items() if K > surface.spot]
    if not below or not above:
        return None
    lower, lower_w = max(below, key=lambda kv: kv[1])
    upper, upper_w = max(above, key=lambda kv: kv[1])
    # Wall-dominance gate (uses OI, the resting-liquidity proxy): the
    # bracketing peaks must dominate the corridor between them. Flat OI
    # distributions are NOT voids regardless of price-distance.
    interior_oi = [b["oi"] for K, b in surface.by_strike.items()
                   if lower < K < upper]
    lower_oi = surface.by_strike[lower]["oi"]
    upper_oi = surface.by_strike[upper]["oi"]
    if interior_oi:
        corridor_max_oi = max(interior_oi)
        wall_min_oi = min(lower_oi, upper_oi)
        if wall_min_oi < 2.0 * corridor_max_oi:
            return None
    width = upper - lower
    width_atr = width / atr if atr > 0 else 0.0
    return LiquidityVoid(
        lower_wall=lower,
        upper_wall=upper,
        width=width,
        width_in_atr=width_atr,
        contains_spot=lower < surface.spot < upper,
    )


# ═══════════════════════════════════════════════════════════════
# AXIS-COLLAPSE GATE (math gotcha §3)
# Cosine similarity between (Γ·σ_S, Vanna·σ_σ, Charm·1) for trapped regime.
# ═══════════════════════════════════════════════════════════════
def axis_collapse_score(
    surface: DealerSurface,
    sigma_S_daily: float,
    sigma_vol_daily: float,
) -> float:
    """
    Returns max pairwise cosine similarity in [0, 1] between hedge-force axes.
    Above cfg['axis_collapse_cos'] indicates collapsed degrees of freedom.
    """
    if sigma_S_daily <= 0 or sigma_vol_daily <= 0:
        return 0.0
    # Aggregate axes weighted by |OI·Greek|
    g_axis = surface.gex_total * sigma_S_daily
    v_axis = surface.vex_total * sigma_vol_daily
    c_axis = surface.cex_total

    vec = (g_axis, v_axis, c_axis)
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return 0.0
    # Pairwise cosines (effectively |xi*xj|/(|xi||xj|) — magnitudes only)
    pairs = [(g_axis, v_axis), (g_axis, c_axis), (v_axis, c_axis)]
    sims = []
    for a, b in pairs:
        na, nb = abs(a), abs(b)
        if na == 0 or nb == 0:
            continue
        # cosine in 1-D is the sign agreement — collapsed iff signs match
        sims.append(1.0 if (a * b) > 0 else 0.0)
    return max(sims) if sims else 0.0


# ═══════════════════════════════════════════════════════════════
# REGIME CLASSIFIER (TNT detector)
# ═══════════════════════════════════════════════════════════════
def _within_vccw(now: Optional[datetime] = None, cfg: Dict[str, Any] = MMLE_CONFIG) -> bool:
    """09:45–15:30 ET window check (uses local minute-of-day in ET)."""
    now = now or datetime.now()
    minute_of_day = now.hour * 60 + now.minute
    return cfg["vccw_minute_open"] <= minute_of_day <= cfg["vccw_minute_close"]


def _z(x: Optional[float], mu: float = 0.0, sd: float = 1.0) -> float:
    if x is None or sd <= 0:
        return 0.0
    return (x - mu) / sd


def classify_tnt(
    surface: DealerSurface,
    flow: FlowToxicity,
    void: Optional[LiquidityVoid],
    sigma_S_daily: float,
    sigma_vol_daily: float,
    nearest_dte: int,
    atr: float,
    adv: float = 0.0,
    cfg: Dict[str, Any] = MMLE_CONFIG,
    now: Optional[datetime] = None,
) -> TNTSignal:
    notes: List[str] = []
    components: Dict[str, float] = {}

    # Window gate
    vccw_open = _within_vccw(now, cfg) and (0 <= nearest_dte <= cfg["vccw_dte_max"])
    if not vccw_open:
        notes.append("VCCW closed (DTE/intraday window)")

    # ──────────────────────────────────────────────────────────────────
    # Each feature is normalized to roughly [0, 1.5] so that no single
    # axis can drive a TNT trigger by itself. TNT requires multi-axis
    # confirmation (cfg['tnt_min_active_axes']).
    # ──────────────────────────────────────────────────────────────────
    # 1. VCSC_Γ — saturates at 1.0 when fully concordant
    z_vcsc = max(0.0, surface.vcsc_gamma - cfg["vcsc_min"]) / max(1e-6, 1.0 - cfg["vcsc_min"])
    z_vcsc = min(1.5, z_vcsc)

    # 2. Dealer aggregate gamma — scale-invariant via daily-traded-notional.
    # gamma_per_notional = |gex_total| / (spot · ADV)
    # Interpretation: dollars of dealer hedge demand per dollar of organic
    # daily flow. > min threshold means dealer rebalancing is large vs the
    # market's natural absorption capacity.
    if adv > 0 and surface.spot > 0 and surface.gex_total < 0:
        gamma_per_notional = abs(surface.gex_total) / (surface.spot * adv)
    elif surface.gex_total < 0:
        # AGENT_LAW §3.1 — ADV unavailable: transparent fallback using
        # ATR · OI · spot · 100 as a coarse daily-notional proxy.
        sum_oi = sum(b["oi"] for b in surface.by_strike.values())
        denom = max(1.0, atr * sum_oi * 100.0 * surface.spot)
        gamma_per_notional = abs(surface.gex_total) / denom
        notes.append("[ESTIMATED_PROXY: gamma_per_notional uses ATR·ΣOI proxy]")
    else:
        gamma_per_notional = 0.0
    z_gamma = min(1.5, gamma_per_notional / max(1e-9, cfg["gamma_per_notional_min"]))

    # 3. VPIN toxicity — one-sided contribution, capped
    if flow.vpin_z is None:
        z_vpin = 0.0
    else:
        z_vpin = min(1.5, max(0.0, flow.vpin_z) / 2.0)  # z=2 → contribution=1.0

    # 4. Dark/lit divergence — capped
    if flow.dark_lit_divergence is None:
        notes.append("[ESTIMATED_PROXY: dark_lit_divergence_unavailable]")
        z_dark = 0.0
        regime_cap = "COMPRESSED"
    else:
        z_dark = min(1.5, abs(flow.dark_lit_divergence) * 1.5)
        regime_cap = None

    # 5. Void width — saturates at 2× the configured minimum
    if void is None:
        z_void = 0.0
    else:
        ratio = void.width_in_atr / max(1e-6, cfg["void_atr_mult"])
        z_void = min(1.5, max(0.0, ratio - 1.0))

    composite = z_vcsc + z_gamma + z_vpin + z_dark + z_void
    active_axes = sum(1 for f in (z_vcsc, z_gamma, z_vpin, z_dark, z_void) if f >= 0.5)

    components.update({
        "z_vcsc": round(z_vcsc, 3),
        "z_gamma": round(z_gamma, 3),
        "z_vpin": round(z_vpin, 3),
        "z_dark": round(z_dark, 3),
        "z_void": round(z_void, 3),
        "active_axes": active_axes,
        "vcsc_gamma": round(surface.vcsc_gamma, 3),
        "gex_total": round(surface.gex_total, 0),
        "vex_total": round(surface.vex_total, 0),
        "cex_total": round(surface.cex_total, 0),
        "gamma_per_notional": round(gamma_per_notional, 6),
    })

    # Axis-collapse gate
    cos = axis_collapse_score(surface, sigma_S_daily, sigma_vol_daily)
    components["axis_cos"] = round(cos, 3)
    axis_collapsed = cos >= cfg["axis_collapse_cos"]

    # Direction: TNT_LONG when target_magnet is above and sign of forced flow is +
    direction_long = (
        surface.gex_total < 0
        and surface.vex_total < 0
        and surface.cex_total < 0
    )
    direction_short = (
        surface.gex_total > 0
        and surface.vex_total > 0
        and surface.cex_total > 0
    )

    # Default state
    state = "NEUTRAL"
    target = None
    expected_minutes = None

    tnt_eligible = (
        vccw_open
        and composite >= cfg["tnt_enter_score"]
        and active_axes >= cfg["tnt_min_active_axes"]
        and axis_collapsed
    )
    if tnt_eligible:
        if direction_long:
            state = "TNT_LONG"
            target = surface.walls.get("call_wall") or None
        elif direction_short:
            state = "TNT_SHORT"
            target = surface.walls.get("put_wall") or None
        else:
            state = "COMPRESSED"
    elif composite >= cfg["tnt_exit_score"] and active_axes >= 2:
        state = "COMPRESSED"

    # Apply regime cap if dark-feed proxy missing
    if regime_cap == "COMPRESSED" and state in ("TNT_LONG", "TNT_SHORT"):
        notes.append("regime capped to COMPRESSED — dark feed unavailable")
        state = "COMPRESSED"
        target = None

    # Expected traverse time — HJB optimal control rough estimate.
    # τ* = void_width / (k · |H|), where |H| is dealer hedge-flow magnitude
    # proxied by |gex_total| / (S · ADV_per_minute). We expose only the
    # void-in-ATR multiple as a transparent proxy here.
    if state in ("TNT_LONG", "TNT_SHORT") and void and atr > 0:
        # rough upper bound: width_in_atr × 6 minutes per ATR (transparent)
        expected_minutes = round(void.width_in_atr * 6.0, 1)
        notes.append(f"[ESTIMATED_PROXY: traverse_minutes ≈ width_in_atr × 6]")

    return TNTSignal(
        ticker=surface.ticker,
        timestamp=time.time(),
        state=state,
        composite_z=round(composite, 3),
        components=components,
        target_magnet=target,
        expected_traverse_minutes=expected_minutes,
        void=void,
        notes=notes,
    )


# ═══════════════════════════════════════════════════════════════
# TOP-LEVEL ENGINE — ties layers 2-4 of the manifest together
# ═══════════════════════════════════════════════════════════════
class MMLiquidityEngine:
    """
    5-minute structural cadence (AGENT_LAW §4) — caller invokes evaluate()
    once per bar with the ingest payload.
    """
    def __init__(self, cfg: Dict[str, Any] = MMLE_CONFIG):
        self.cfg = cfg
        self._vpin: Dict[str, VPINTracker] = {}

    def _get_vpin(self, ticker: str, adv: float) -> VPINTracker:
        if ticker not in self._vpin:
            bucket = max(1.0, adv * self.cfg["vpin_bucket_vol_pct"])
            self._vpin[ticker] = VPINTracker(bucket_volume=bucket,
                                             window=self.cfg["vpin_window"])
        return self._vpin[ticker]

    def ingest_trade(self, ticker: str, price: float, size: float,
                     adv: float, side: Optional[str] = None) -> None:
        self._get_vpin(ticker, adv).add_trade(price, size, side)

    def evaluate(
        self,
        ticker: str,
        spot: float,
        raw_chain: Dict[str, Any],
        atr: float,
        sigma_S_daily: float,
        sigma_vol_daily: float,
        adv: float,
        nearest_dte: int,
        lit_ofi: float = 0.0,
        dark_prints: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> TNTSignal:
        surface = build_dealer_surface(raw_chain, spot, ticker, self.cfg)
        if surface is None:
            return TNTSignal(
                ticker=ticker, timestamp=time.time(),
                state="AWAITING_STREAM", composite_z=0.0,
                components={}, target_magnet=None,
                expected_traverse_minutes=None, void=None,
                notes=["chain incomplete — AGENT_LAW §1.1"],
            )

        vpin_t = self._get_vpin(ticker, adv)
        flow = FlowToxicity(
            vpin=vpin_t.vpin(),
            vpin_z=vpin_t.vpin_z(),
            dark_lit_divergence=dark_lit_divergence(dark_prints, lit_ofi, spot)
            if dark_prints is not None else None,
        )

        void = find_liquidity_void(surface, atr, self.cfg)

        return classify_tnt(
            surface=surface,
            flow=flow,
            void=void,
            sigma_S_daily=sigma_S_daily,
            sigma_vol_daily=sigma_vol_daily,
            nearest_dte=nearest_dte,
            atr=atr,
            adv=adv,
            cfg=self.cfg,
            now=now,
        )


__all__ = [
    "MMLE_CONFIG",
    "StrikeGreeks",
    "DealerSurface",
    "FlowToxicity",
    "LiquidityVoid",
    "TNTSignal",
    "VPINTracker",
    "MMLiquidityEngine",
    "build_dealer_surface",
    "find_liquidity_void",
    "dark_lit_divergence",
    "classify_tnt",
    "bs_gamma",
    "bs_vanna",
    "bs_charm",
]
