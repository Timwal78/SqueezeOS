"""
OpenMythos RDT — Recurrent-Depth Transformer
Recursive "what-if" loop on market graph snapshots to identify fractal correlations
and gamma-exposure magnets in the SML universe (GME, AMC, IWM).

Architecture:
  depth=0  — current market state (prices, Greeks, regime)
  depth=1  — 1st-order neighbors (GAMMA_CORRELATED, DARK_POOL_FLOW edges)
  depth=2  — 2nd-order: fractal pattern match against historical anchors
  depth=3  — convergence scoring: multi-ticker alignment = high conviction
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Fractal Anchor Library ────────────────────────────────────────────────────
# Historical squeeze anchor profiles (score fingerprints)
FRACTAL_ANCHORS = {
    "GME_SEP2020": {"vpin": 0.72, "gex": -8500, "regime": "IGNITION",  "mult": 4.2},
    "GME_MAY2024": {"vpin": 0.58, "gex": -3200, "regime": "BULL_ZONE", "mult": 1.8},
    "AMC_MAY2024": {"vpin": 0.61, "gex": -1800, "regime": "BULL_ZONE", "mult": 2.1},
    "AMC_MAY2025": {"vpin": 0.55, "gex": -900,  "regime": "WATCH",     "mult": 1.4},
}


@dataclass
class RDTSignal:
    symbol:       str
    depth:        int
    fractal_match: str
    fractal_score: float        # 0–100
    confidence:   float         # 0–100
    direction:    str           # BUY / SELL / HOLD / SHIELD
    target_mult:  float         # expected move multiplier
    reason:       str
    neighbors:    list = field(default_factory=list)
    ts:           str  = field(default_factory=lambda: datetime.utcnow().isoformat())


class RecurrentDepthTransformer:
    """
    Runs recursive what-if loops on the live market graph.
    At each depth level, evaluates fractal similarity against known anchors.
    Stops when depth=3 or score falls below threshold.
    """

    MAX_DEPTH  = 3
    MIN_SCORE  = 15.0   # below this, stop recursing
    EDGE_DECAY = 0.78   # confidence decay per hop

    def __init__(self, graph=None):
        """
        graph: MarketGraph instance (optional — graceful degraded mode if None)
        """
        self.graph = graph

    # ── Main Entry ────────────────────────────────────────────────────────────

    def run(self, symbol: str, price: float, vpin: float,
            gex: float, regime: str) -> Optional[RDTSignal]:
        """
        Run RDT for a single symbol.
        Returns the best-scoring RDTSignal across all depths.
        """
        logger.debug(f"[RDT] Running for {symbol} @ {price} | vpin={vpin:.2f} gex={gex:.0f}")
        return self._recurse(
            symbol=symbol, price=price, vpin=vpin,
            gex=gex, regime=regime, depth=0,
            confidence_budget=100.0
        )

    def run_universe(self, snapshots: dict) -> list:
        """
        Run RDT across the full SML universe.
        snapshots = {symbol: {price, vpin, gex, regime}, ...}
        Returns list of RDTSignal sorted by confidence DESC.
        """
        signals = []
        for sym, data in snapshots.items():
            sig = self.run(
                symbol=sym,
                price=data.get("price", 0.0),
                vpin=data.get("vpin", 0.0),
                gex=data.get("gex", 0.0),
                regime=data.get("regime", "UNKNOWN")
            )
            if sig:
                signals.append(sig)
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    # ── Recursive Core ────────────────────────────────────────────────────────

    def _recurse(self, symbol: str, price: float, vpin: float,
                 gex: float, regime: str, depth: int,
                 confidence_budget: float) -> Optional[RDTSignal]:

        # Guard None inputs (after-hours / no data)
        price  = price  or 0.0
        vpin   = vpin   or 0.0
        gex    = gex    or 0.0
        regime = regime or 'UNKNOWN'

        if depth > self.MAX_DEPTH or confidence_budget < self.MIN_SCORE:
            return None

        # Score against all fractal anchors
        best_anchor, best_score = self._match_anchors(vpin, gex, regime)

        if best_score < self.MIN_SCORE and depth > 0:
            return None

        # Derive direction from anchor
        direction = self._score_to_direction(best_score, regime, vpin)

        # Build signal at this depth
        sig = RDTSignal(
            symbol        = symbol,
            depth         = depth,
            fractal_match = best_anchor,
            fractal_score = best_score,
            confidence    = min(100.0, confidence_budget * (best_score / 100.0)),
            direction     = direction,
            target_mult   = FRACTAL_ANCHORS.get(best_anchor, {}).get("mult", 1.0),
            reason        = self._build_reason(symbol, best_anchor, best_score,
                                                regime, vpin, gex, depth)
        )

        # ── Depth recursion via graph neighbors ──────────────────────────────
        if self.graph and depth < self.MAX_DEPTH:
            neighbors = []
            try:
                edges = self.graph.get_edges(symbol)
                for edge in edges:
                    neighbor_sym = edge.get("to")
                    if not neighbor_sym or neighbor_sym == symbol:
                        continue
                    # Pull neighbor state from graph
                    neighbor_nodes = {
                        n["symbol"]: n for n in self.graph.get_all_tickers()
                    }
                    n_data = neighbor_nodes.get(neighbor_sym, {})
                    child_sig = self._recurse(
                        symbol=neighbor_sym,
                        price=n_data.get("price", 0.0),
                        vpin=n_data.get("vpin", 0.0),
                        gex=n_data.get("gex", 0.0),
                        regime=n_data.get("regime", "UNKNOWN"),
                        depth=depth + 1,
                        confidence_budget=confidence_budget * self.EDGE_DECAY
                    )
                    if child_sig:
                        neighbors.append(child_sig)
            except Exception as e:
                logger.warning(f"[RDT] Graph neighbor fetch failed at depth {depth}: {e}")

            sig.neighbors = neighbors

            # Boost confidence if neighbors confirm the direction
            confirming = sum(1 for n in neighbors if n.direction == direction)
            if confirming >= 2:
                sig.confidence = min(100.0, sig.confidence * 1.18)
                sig.reason += f" · {confirming} correlated tickers confirm."

        return sig

    # ── Fractal Matching ──────────────────────────────────────────────────────

    def _match_anchors(self, vpin: float, gex: float,
                        regime: str) -> tuple[str, float]:
        """Score current state against all fractal anchors. Returns best match."""
        best_name  = "None"
        best_score = 0.0

        for name, anchor in FRACTAL_ANCHORS.items():
            score = self._similarity(vpin, gex, regime, anchor)
            if score > best_score:
                best_score = score
                best_name  = name

        return best_name, best_score

    def _similarity(self, vpin: float, gex: float,
                    regime: str, anchor: dict) -> float:
        """
        Weighted similarity score 0–100.
        VPIN: 40pts, GEX direction: 30pts, Regime match: 30pts
        """
        vpin   = vpin   or 0.0
        gex    = gex    or 0.0
        regime = regime or 'UNKNOWN'
        score  = 0.0

        # VPIN proximity (within 0.15 = full points)
        vpin_diff = abs(vpin - anchor["vpin"])
        score += max(0.0, 40.0 * (1.0 - vpin_diff / 0.30))

        # GEX direction match
        if (gex < 0) == (anchor["gex"] < 0):
            score += 30.0
            # Magnitude proximity bonus (up to 10 extra)
            anchor_mag = abs(anchor["gex"])
            current_mag = abs(gex)
            if anchor_mag > 0:
                ratio = min(current_mag, anchor_mag) / max(current_mag, anchor_mag)
                score += 10.0 * ratio

        # Regime match
        if regime == anchor["regime"]:
            score += 30.0
        elif regime in ("BULL_ZONE", "IGNITION") and \
             anchor["regime"] in ("BULL_ZONE", "IGNITION"):
            score += 15.0

        return min(100.0, score)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _score_to_direction(self, score: float, regime: str,
                             vpin: float) -> str:
        if vpin > 0.75:
            return "SHIELD"
        if score >= 70 and regime in ("IGNITION", "BULL_ZONE"):
            return "BUY"
        if score >= 50:
            return "WATCH"
        if regime in ("BEAR", "AXIS_COLLAPSE"):
            return "SELL"
        return "HOLD"

    def _build_reason(self, symbol: str, anchor: str, score: float,
                       regime: str, vpin: float, gex: float,
                       depth: int) -> str:
        vpin = vpin or 0.0
        gex  = gex  or 0.0
        gex_sign = "negative" if gex < 0 else "positive"
        return (
            f"{symbol} fractal match {anchor} ({score:.0f}/100) at depth {depth}. "
            f"Regime {regime} \u00b7 VPIN {vpin:.0%} \u00b7 GEX {gex_sign} "
            f"({abs(gex):.0f}M exposure)."
        )
