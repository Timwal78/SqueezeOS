"""
Engine 7 — SML Parabolic Flight Path
====================================
A standalone sub-routine that slices the Base-4 Matrix diagonally to track
non-linear geometric acceleration, liquidity exhaustion, and symmetrical consolidation.

It is deployed when the HUD detects an 'APEX SINGULARITY'.
"""

import logging
from typing import List, Dict, Any

import threading
import time
import math

from core.proprietary_ema_engine import _ema, _tail

logger = logging.getLogger("SML.Engine7")

def _stdev(values: List[float], period: int) -> float:
    if len(values) < 2: return 0.0
    slice_vals = values[-period:]
    mean = sum(slice_vals) / len(slice_vals)
    var = sum((x - mean) ** 2 for x in slice_vals) / (len(slice_vals) - 1)
    return math.sqrt(var)

class Engine7_Parabolic:
    """
    Engine 7 — SML Parabolic Flight Path.
    Extracts non-linear, geometric acceleration curves.
    """
    
    # Track active threads to prevent redundant spawning
    _active_trackers = set()

    @classmethod
    def launch_tracking_thread(cls, symbol: str):
        """Spins up an independent background worker to aggressively track the flight path."""
        if symbol in cls._active_trackers:
            return
            
        cls._active_trackers.add(symbol)
        t = threading.Thread(target=cls._tracking_loop, args=(symbol,), daemon=True)
        t.start()

    @classmethod
    def _tracking_loop(cls, symbol: str):
        """High-frequency polling loop isolated from main ingestion thread."""
        from core.state import state
        from core.legacy import get_service
        
        logger.info(f"[APEX] Engine 7 Parabolic Flight Path tracking loop started for {symbol}")
        state.push_terminal("APEX_TRACKING", "Engine 7 actively tracking geometric acceleration", symbol, score=100.0)
        
        engine = cls()
        try:
            while True:
                time.sleep(1.0) # 1-second micro-polling
                
                with state.lock:
                    data = state.universe.get(symbol, [])
                
                if not data:
                    continue
                    
                # Assuming OHLCV where close is index 4, or direct float list if pre-processed
                closes = [d[4] if isinstance(d, (list, tuple)) else d for d in data]
                
                result = engine.analyze(closes, is_singularity=True)
                sig = result.get("signal")
                
                if sig in ("COMPRESSION_FAILED", "LIQUIDITY_EXHAUSTION", "PARABOLIC_EXHAUSTION_EXIT"):
                    msg = f"Parabolic flight path broken: {sig}. Terminating tracker."
                    logger.warning(f"[APEX] [{symbol}] {msg}")
                    state.push_terminal("APEX_TERMINATED", msg, symbol, score=-50.0)
                    
                    # ── Asynchronous Execution Payload ──
                    if sig == "PARABOLIC_EXHAUSTION_EXIT":
                        exec_eng = get_service("exec")
                        if exec_eng:
                            active_trades = exec_eng.get_active_trades()
                            if symbol in active_trades:
                                trade = active_trades[symbol]
                                qty = trade.get("qty", 0)
                                # Marketable Limit Order dynamically pegged using the Golden Ratio multiplier of active volatility
                                current_price = closes[-1]
                                raw_bands = result.get("_raw_bands", {})
                                std_dev_36 = raw_bands.get("std_dev_36", current_price * 0.02) # Fallback to 2% if missing
                                
                                dynamic_discount = 1.618 * std_dev_36
                                limit_price = round(current_price - dynamic_discount, 2)
                                
                                logger.critical(f"[APEX] EXECUTING EMERGENCY LIQUIDATION for {symbol}: SELL {qty} @ {limit_price} (Dynamic Discount: -${dynamic_discount:.2f})")
                                exec_eng.execute_trade(
                                    symbol=symbol,
                                    directive="SELL",
                                    qty=qty,
                                    price=limit_price,
                                    reason=f"APEX_TERMINATED: {sig}"
                                )
                                
                                # ── 402Proof Settlement Attestation ──
                                try:
                                    from core.nexus402_bridge import notarize_execution
                                    cert = notarize_execution(symbol, "SELL", qty, limit_price, sig, dynamic_discount)
                                    if cert:
                                        state.push_terminal("402PROOF_MINTED", f"Proof of Settlement secured. Cert: {cert.get('certificate_id')}", symbol, score=100.0)
                                except ImportError:
                                    logger.warning("[APEX] core.nexus402_bridge missing. Execution untracked by Ghost Layer.")
                                    
                    break
        finally:
            cls._active_trackers.discard(symbol)

    def analyze(self, closes: List[float], is_singularity: bool) -> dict:
        n = len(closes)
        if n < 48:
            return {"engine": 7, "signal": "INSUFFICIENT_DATA"}

        price = closes[-1]
        
        # Calculate the required diagonal EMAs
        e1  = _tail(_ema(closes, min(1,  n)))
        e4  = _tail(_ema(closes, min(4,  n)))
        e8  = _tail(_ema(closes, min(8,  n)))
        e12 = _tail(_ema(closes, min(12, n)))
        e16 = _tail(_ema(closes, min(16, n)))
        e24 = _tail(_ema(closes, min(24, n)))
        e36 = _tail(_ema(closes, min(36, n)))
        e48 = _tail(_ema(closes, min(48, n)))

        # ── 1. The Quadratic Expansion (4, 16, 36) ─────────────────────────
        # Represents geometric acceleration. Asset is trapped in a mathematically
        # flawless quadratic launch sequence if riding the 4, holding 16, and macro 36.
        quadratic_bull = price > e4 > e16 > e36
        quadratic_bear = price < e4 < e16 < e36

        # ── 2. The Multiplier Compression (1, 8, 24, 48) ───────────────────
        # "Liquidity Exhaustion" tracker. 
        compression_stack_bull = price > e1 > e8 > e24 > e48
        liquidity_exhaustion   = e1 < e8 and e8 > e24 > e48
        compression_failed     = e1 < e8 and price < e24

        # ── 3. The Symmetrical Pivot (12, 16) ──────────────────────────────
        # Symmetrical harmonic pivot point. 16 EMA is the absolute center-of-gravity.
        pivot_diff_pct = abs(e12 - e16) / price if price else 0.0
        symmetrical_consolidation = pivot_diff_pct < 0.005

        # ── 4. The Exit Matrix (Phi Standard Deviation Band) ────────────────
        std_dev_36 = _stdev(closes, min(36, n))
        lower_band = e36 - (1.618 * std_dev_36) # Golden Ratio Multiplier
        parabolic_exhaustion = e4 < lower_band

        # ── Signal Logic ───────────────────────────────────────────────────
        signal = "NEUTRAL"
        
        if is_singularity:
            if parabolic_exhaustion:
                signal = "PARABOLIC_EXHAUSTION_EXIT"
            elif quadratic_bull:
                signal = "QUADRATIC_LAUNCH_BULL"
            elif quadratic_bear:
                signal = "QUADRATIC_LAUNCH_BEAR"
            elif compression_failed:
                signal = "COMPRESSION_FAILED"
            elif liquidity_exhaustion:
                signal = "LIQUIDITY_EXHAUSTION"
            elif symmetrical_consolidation:
                signal = "SYMMETRICAL_CONSOLIDATION"
            else:
                signal = "PARABOLIC_CHOP"
        else:
            signal = "DORMANT"

        _score_map = {
            "QUADRATIC_LAUNCH_BULL":     100,
            "QUADRATIC_LAUNCH_BEAR":    -100,
            "LIQUIDITY_EXHAUSTION":      -20,
            "COMPRESSION_FAILED":        -50,
            "SYMMETRICAL_CONSOLIDATION":   0,
            "PARABOLIC_CHOP":              0,
            "DORMANT":                     0,
            "NEUTRAL":                     0,
        }

        return {
            "engine":             7,
            "name":               "SML Parabolic Flight Path",
            "dimension":          "GEOMETRIC_ACCELERATION",
            "is_singularity":     is_singularity,
            "quadratic_bull":     quadratic_bull,
            "quadratic_bear":     quadratic_bear,
            "liquidity_exhaustion": liquidity_exhaustion,
            "compression_failed":   compression_failed,
            "symmetrical_consolidation": symmetrical_consolidation,
            "parabolic_exhaustion": parabolic_exhaustion,
            "pivot_diff_pct":     round(pivot_diff_pct * 100, 4),
            "signal":             signal,
            "score_contrib":      _score_map.get(signal, 0),
            
            # Internal raw data (redacted before JSON serialization)
            "_raw_emas":          {"e1": e1, "e4": e4, "e8": e8, "e12": e12, "e16": e16, "e24": e24, "e36": e36, "e48": e48},
            "_raw_bands":         {"std_dev_36": std_dev_36, "lower_band": lower_band}
        }

def redact_engine7_block(block: dict) -> dict:
    """Strips internal parameters and EMA values from Engine 7 output."""
    if not isinstance(block, dict):
        return block
    
    safe_fields = {
        "engine", "dimension", "signal", "score_contrib", 
        "is_singularity", "quadratic_bull", "quadratic_bear",
        "liquidity_exhaustion", "compression_failed", "symmetrical_consolidation",
        "parabolic_exhaustion"
    }
    return {k: v for k, v in block.items() if k in safe_fields}
