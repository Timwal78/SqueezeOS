"""
RMRE Bridge — Connects the Reflexive Market Regime Engine to SqueezeOS.
═══════════════════════════════════════════════════════════════════════

Integration points:
  1. Regime modifier on consolidated Beast Score (+/- up to 10 pts)
  2. /api/market/regime endpoint for frontend display
  3. Upstream driver info injected into scan results
  4. Regime history for live terminal tracking
"""
from __future__ import annotations

import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from threading import Lock, Thread
from collections import deque

import numpy as np
import pandas as pd

from sml_engine import SMLEngine

logger = logging.getLogger(__name__)

# ── Ensure RMRE source is importable (Legacy / Future expansion) ──
RMRE_SRC = Path(__file__).resolve().parent.parent / "rmre_mvp" / "rmre_mvp" / "src"
if str(RMRE_SRC) not in sys.path:
    sys.path.insert(0, str(RMRE_SRC))

RMRE_AVAILABLE = True # SML Engine is now the primary provider

class RMREBridge:
    """
    Bridges RMRE and SML regime intelligence into the SqueezeOS Beast Score.
    Runs at 60s intervals for a live-flowing Regime panel.
    """

    REGIME_SYMBOLS = ["AMC", "GME", "XRT", "IWM", "SPY", "VIX", "TLT", "US10Y", "DXY", "HYG", "GOLD", "QQQ", "IJR"]

    def __init__(self):
        self._lock = Lock()
        self._cache: Dict[str, Any] = {}
        self._last_update: float = 0
        self._update_interval = 60  # 60s
        self._market_history: List[Dict] = []
        self._max_history_bars = 220
        self._data_mgr: Optional[Any] = None
        self._mtf_cache: Dict[str, Dict[str, Any]] = {}  # symbol -> {data, timestamp}

        # ── Regime history: last 10 regime states ──
        self._regime_history: deque = deque(maxlen=10)
        self._net_pressure_history: deque = deque(maxlen=50) # Track history for slope
        self._last_regime: str = ""
        self._sml = SMLEngine()

    def set_data_provider(self, dm: Any) -> None:
        """Sets the data manager for HTF lookups."""
        self._data_mgr = dm
        logger.info("[RMRE] Data manager linked for MTF discovery")

    def pre_load_history(self, symbol: str) -> bool:
        """Pre-loads 252 bars of history for a symbol into the bridge."""
        if not self._data_mgr or not self._data_mgr.polygon:
            return False
        try:
            logger.info(f"[RMRE] Pre-loading history for {symbol}...")
            # Polygon FREE tier provides 'prev-day' or 'aggregates'
            # We use aggregates to get enough bars to start the engine
            df = self._data_mgr.polygon.get_aggregates(symbol, 1, 'day', limit=252)
            if not df:
                return False

            # Convert to list of dicts with normalized keys for ingest_quotes
            for bar in df:
                ts = pd.to_datetime(bar['timestamp'], unit='ms').normalize()
                self._market_history.append({
                    "timestamp": ts,
                    "symbol": symbol.upper(),
                    "close": float(bar['close']),
                    "volume": float(bar['volume']),
                    "high": float(bar['high']),
                    "low": float(bar['low'])
                })
            
            # Deduplicate and sort
            df_hist = pd.DataFrame(self._market_history)
            df_hist = df_hist.drop_duplicates(subset=['timestamp', 'symbol'], keep='last')
            self._market_history = df_hist.sort_values('timestamp').to_dict('records')
            
            logger.info(f"[RMRE] History pre-loaded for {symbol} ({len(df)} bars)")
            return True
        except Exception as e:
            logger.error(f"[RMRE] Pre-load error for {symbol}: {e}")
            return False

    def pre_load_history_async(self, symbol: str) -> None:
        """Triggers pre_load_history in a separate thread to avoid blocking."""
        with self._lock:
            # Check if recently loaded (within 24 hours)
            # Find any bars for this symbol in market history
            has_history = any(h['symbol'] == symbol.upper() for h in self._market_history)
            if has_history:
                return

        # Start thread
        Thread(target=self.pre_load_history, args=(symbol,), daemon=True).start()

    @property
    def available(self) -> bool:
        return RMRE_AVAILABLE

    @property
    def regime_changed(self) -> bool:
        """True if regime changed since last compute."""
        current = self._cache.get("regime", "")
        return bool(current and current != self._last_regime)

    def get_regime_history(self) -> List[Dict]:
        return list(self._regime_history)

    def ingest_quotes(self, quotes: Dict[str, Dict]) -> None:
        timestamp = pd.Timestamp.now().normalize()

        for symbol, data in quotes.items():
            price = data.get('price', 0) or data.get('lastPrice', 0) or data.get('close', 0)
            volume = data.get('volume', 0) or data.get('totalVolume', 0)

            if price <= 0:
                continue

            mapped_symbol = symbol.upper()
            if mapped_symbol == "GLD":
                mapped_symbol = "GOLD"

            self._market_history.append({
                "timestamp": timestamp,
                "symbol": mapped_symbol,
                "close": float(price),
                "volume": float(volume),
            })

        if len(self._market_history) > self._max_history_bars * len(self.REGIME_SYMBOLS):
            self._market_history = self._market_history[-(self._max_history_bars * len(self.REGIME_SYMBOLS)):]
        
        unique_syms = set(h['symbol'] for h in self._market_history)
        logger.info(f"[RMRE] Ingested {len(quotes)} quotes. Total History Symbols: {len(unique_syms)} ({list(unique_syms)[:5]}...)")

    def compute_regime(self, target_symbol: str = "AMC") -> Dict[str, Any]:
        now = time.time()
        # Cache for 60s
        if now - self._last_update < self._update_interval and self._cache and self._cache.get("target") == target_symbol:
            return self._cache

        with self._lock:
            try:
                return self._run_pipeline(target_symbol)
            except Exception as e:
                logger.error(f"[RMRE] Pipeline error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return self._default_regime(target_symbol)

    def _run_pipeline(self, target_symbol: str) -> Dict[str, Any]:
        """
        Implements SML Fractal Cascade™ v2 Integration.
        """
        df_all = pd.DataFrame(self._market_history)
        if df_all.empty or len(df_all.symbol.unique()) < 4:
            return self._default_regime(target_symbol)

        # ── 1. PREPARE DATA ──
        market_history = {}
        for sym in df_all.symbol.unique():
            sym_df = df_all[df_all['symbol'] == sym].sort_values('timestamp')
            if 'high' not in sym_df.columns: sym_df['high'] = sym_df['close']
            if 'low' not in sym_df.columns: sym_df['low'] = sym_df['close']
            if 'volume' not in sym_df.columns: sym_df['volume'] = 0
            market_history[sym] = sym_df

        # ── 2. HTF CASCADE (v2) ──
        mtf_data = {}
        now_ts = time.time()
        
        # Free Tier Optimization: Cache MTF data for 60 minutes
        cache_key = target_symbol.upper()
        if cache_key in self._mtf_cache:
            entry = self._mtf_cache[cache_key]
            if now_ts - entry['ts'] < 3600: # 1 hour
                mtf_data = entry['data']
        
        if not mtf_data:
            dm = self._data_mgr
            if dm and dm.polygon:
                try:
                    # Fetch daily data for the last 500 bars
                    df_daily = dm.polygon.get_aggregates(target_symbol, 1, 'day', limit=500)
                    if not df_daily.empty:
                        df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'], unit='ms')
                        df_daily.set_index('timestamp', inplace=True)
                        
                        intervals = [
                            ('6M', '6ME'), ('3M', '3ME'), ('1M', 'ME'), ('2W', '2W'),
                            ('1W', 'W'), ('4D', '4D'), ('2D', '2D'), ('1D', 'D')
                        ]
                        
                        for label, freq in intervals:
                            resampled = df_daily.resample(freq).agg({'high': 'max', 'low': 'min', 'close': 'last', 'open': 'first'})
                            if len(resampled) >= 2:
                                curr = resampled.iloc[-1]
                                prev = resampled.iloc[-2]
                                c2h, c2l, c2c = curr['high'], curr['low'], curr['close']
                                c1h, c1l = prev['high'], prev['low']
                                
                                classify = self._sml.f_classify(c2h, c2l, c2c, c1h, c1l)
                                sweep = self._sml.f_sweep_state(c2h, c2l, c1h, c1l)
                                
                                mtf_data[label] = {
                                    "classify": classify,
                                    "sweep": sweep,
                                    "state": self._sml.f_state_str(classify, sweep),
                                    "meaning": self._sml.f_meaning_str(classify, sweep),
                                    "pos_pct": self._sml.f_round(self._sml.f_safe_div(c2c - c1l, c1h - c1l) * 100.0, 0)
                                }
                            else:
                                mtf_data[label] = {"classify": 0, "sweep": 0, "state": "INSIDE", "meaning": "No clear move yet", "pos_pct": 50.0}
                        
                        # Save to cache
                        self._mtf_cache[cache_key] = {'data': mtf_data, 'ts': now_ts}
                    else:
                        logger.warning(f"[RMRE] No daily data for {target_symbol} HTF Cascade")
                except Exception as e:
                    logger.error(f"[RMRE] MTF Resample Error: {e}")

        # ── 3. RUN SML ENGINE ──
        sml_result = self._sml.compute_all(target_symbol, market_history, mtf_data, list(self._net_pressure_history))
        if not sml_result:
            return self._default_regime(target_symbol)

        # ── 4. WRAPUP & MODIFIER ──
        net_pressure = sml_result['net_pressure']
        self._net_pressure_history.append(net_pressure)
        
        regime_text = sml_result['regime_text']
        lifecycle_text = sml_result['lifecycle_text']
        decision = sml_result['decision']
        
        # ── Risk Range Mapping (v3) ──
        levels = sml_result.get('levels', {})
        tp1 = levels.get('tp1', 0)
        tp2 = levels.get('tp2', 0)
        inv = levels.get('invalidation', 0)
        
        risk_ranges = {
            "st": {"low": inv, "high": tp1, "label": "SCALPING"},
            "it": {"low": inv, "high": tp2, "label": "SWING"},
            "lt": {"low": inv, "high": round(tp2 * 1.5, 3), "label": "CORE"}
        }
        
        # ── Legacy Compatibility Mapping ──
        legacy_regime = "risk_on" if net_pressure > 20 else "risk_off" if net_pressure < -20 else "neutral"
        
        result = {
            "target": target_symbol,
            "regime": legacy_regime,
            "regime_label": regime_text,
            "regime_confidence": sml_result['regime_confidence'] / 100.0,
            "conviction": "ULTIMATE" if abs(net_pressure) > 80 else "HIGH" if abs(net_pressure) > 60 else "MEDIUM" if abs(net_pressure) > 40 else "LOW",
            "confidence": sml_result['confidence'],
            "net_pressure": net_pressure,
            "bull_chain": sml_result['bull_chain'],
            "bear_chain": sml_result['bear_chain'],
            "bull_count": sml_result.get('bull_count', 0),
            "bear_count": sml_result.get('bear_count', 0),
            "avoid_count": sml_result.get('avoid_count', 0),
            "cascade_bias": sml_result.get('cascade_bias', 'NEUTRAL'),
            "cascade_meaning": sml_result.get('cascade_meaning', ''),
            "lifecycle": lifecycle_text.upper(),
            "decision": decision,
            "macro_score": round(sml_result['macro_score'] * 20, 2),
            "risk_score": round(sml_result['risk_score'] * 20, 2),
            "basket_score": round(sml_result['basket_score'] * 20, 2),
            "target_score": round(sml_result['target_score'] * 20, 2),
            "reflex_score": round(sml_result['reflex_score'] * 20, 2),
            "hurst_val": sml_result.get('hurst_val', 0.5),
            "hurst_confirms": sml_result['hurst_confirms'],
            "levels": sml_result['levels'],
            "risk_ranges": risk_ranges,
            "mtf_map": mtf_data,
            "beast_modifier": int(net_pressure / 5.0),
            "updated_at": time.time(),
            "moass_watch": (regime_text == "EXECUTION" and target_symbol in ("AMC", "GME") and net_pressure > 80) or decision == "MOASS WATCH" or (sml_result.get('squeeze_score', 0) > 90 and sml_result.get('lifecycle_text') == "Active"),
            "fractal": {"label": f"{lifecycle_text} {regime_text}", "score": float(round(float(sml_result.get('confidence', 0)/100.0), 2))},
            "regime_history": list(reversed(self._regime_history)) if self._regime_history else []
        }

        # ── 10. HISTORY & SIDE EFFECTS ──
        self._regime_history.append({
            "timestamp": time.time(),
            "regime": regime_text.lower(),
            "net_pressure": net_pressure,
            "decision": decision
        })
        self._last_regime = regime_text.lower()

        self._cache = result
        self._last_update = time.time()
        return result

    def get_beast_modifier(self, symbol: str = "AMC") -> int:
        regime = self.compute_regime(symbol)
        return regime.get("beast_modifier", 0)

    def _default_regime(self, target: str) -> Dict[str, Any]:
        return {
            "target": target, "regime": "unknown", "regime_label": "UNKNOWN",
            "confidence": 0.0, "net_pressure": 0.0, "beast_modifier": 0,
            "lifecycle": "DORMANT", "decision": "WAIT",
            "risk_ranges": {},
            "updated_at": time.time(),
            "moass_watch": False,
        }

# ── Global instance ──
rmre_bridge = RMREBridge()
