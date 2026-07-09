"""
SML COMMAND CENTER — ORACLE ENGINE
Codename: ORACLE

Aggregates live signals from all SqueezeOS engines into a single
BUY / SELL / HOLD / SHIELD directive with full Driver/Navigator payload.

GitNexus-verified engine chain:
  gamma_flow_engine.py  → _signal_gamma_flip, analyze_fusion
  sml_engine.py         → compute_fractal_cascade, f_classify
  rmre_bridge.py        → compute_regime, _run_pipeline
  options_intelligence  → compute_flow_summary
  execution_engine.py   → get_gamma_walls
  data_providers.py     → TradierProvider (live quotes)
"""
import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional
import pandas as pd

from core.proprietary_ema_engine import redact_engine_block as _redact_engine
from core.state import state

logger = logging.getLogger("Oracle")

# Sweet spot for 0DTE focus ($1–$60 range)
SWEET_SPOT_MIN = 1.0
SWEET_SPOT_MAX = 60.0

# Directive thresholds
IGNITION_THRESHOLD   = 82  # BUY — full send
BULL_THRESHOLD       = 60  # BUY — starter
WATCH_THRESHOLD      = 40  # HOLD — structure reclaim
BEAR_THRESHOLD       = 20  # SELL — distribution detected

# Historical fractal anchors for echo detection (Sep2020 GME baseline)
FRACTAL_ANCHORS = {
    "GME": [
        {"name": "Sep2020-Echo",  "multiplier": 1.0,  "target_pct": 0.68},
        {"name": "Jan2021-Echo",  "multiplier": 1.32, "target_pct": 1.20},
        {"name": "May2024-Echo",  "multiplier": 0.72, "target_pct": 0.45},
    ],
    "AMC": [
        {"name": "May2021-Echo",  "multiplier": 1.0,  "target_pct": 0.80},
        {"name": "May2024-Echo",  "multiplier": 0.78, "target_pct": 0.38},
    ],
    "IWM": [
        {"name": "0DTE-Gamma-Band", "multiplier": 1.0, "target_pct": 0.025},
    ],
}

# TP/Stop multipliers per regime
REGIME_MULTIPLIERS = {
    "ALPHA_EXPANSION": {"tp1": 1.15, "tp2": 1.30, "stop": 0.94},
    "MACRO_COLLAPSE":  {"tp1": 0.88, "tp2": 0.80, "stop": 1.04},
    "NEUTRAL":         {"tp1": 1.07, "tp2": 1.14, "stop": 0.96},
    "SHIELD":          {"tp1": None, "tp2": None,  "stop": None},
}


class OracleEngine:
    """
    Aggregates all SqueezeOS engine signals for a given symbol
    and emits a single structured Oracle directive.
    """

    def __init__(self, services: dict):
        """
        services: dict provided by core/legacy.py _services registry
          Expected keys: 'dm', 'whale_stalker'
          Optional keys: 'sml', 'mmle', 'gamma_flow', 'rmre', 'options_intel'
        """
        self.services = services or {}
        self._cache = {}
        self._cache_ttl = 60  # seconds

    def _get_service(self, name):
        return self.services.get(name)

    def _cached(self, key, fn, ttl=None):
        ttl = ttl or self._cache_ttl
        entry = self._cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl:
            return entry["data"]
        result = fn()
        self._cache[key] = {"ts": time.time(), "data": result}
        return result

    def _get_quote(self, symbol: str) -> dict:
        """Pull live quote from Tradier via DataManager."""
        dm = self._get_service("dm")
        if not dm:
            return {}
        try:
            quotes = dm.get_quotes([symbol])
            return quotes.get(symbol, {})
        except Exception as e:
            logger.error(f"[Oracle] Quote fetch failed for {symbol}: {e}")
            return {}

    def _get_gamma_walls(self, symbol: str, price: float) -> dict:
        """Pull gamma wall levels from ExecutionEngine."""
        try:
            from execution_engine import ExecutionEngine
            from rmre_bridge import RMREBridge
            dm = self._get_service("dm")
            if not dm:
                return {}
            rmre = RMREBridge()
            ee = ExecutionEngine(schwab_api=None, rmre_bridge=rmre)
            ee.set_broker(dm)
            walls = ee.get_gamma_walls(symbol)
            if not walls:
                return {}
            
            # The execution_engine returns a single dict with call_wall, put_wall, total_gex, etc.
            # Convert this to what oracle_engine expects.
            return {
                "wall_above": walls.get("call_wall"),
                "wall_below": walls.get("put_wall"),
                "wall_strength_above": walls.get("total_gex", 0),  # Using total_gex as proxy
                "wall_strength_below": walls.get("total_gex", 0),
            }
        except Exception as e:
            logger.warning(f"[Oracle] Gamma walls unavailable for {symbol}: {e}")
            return {}

    def _get_regime(self, symbol: str) -> str:
        """Pull beast regime from RMREBridge."""
        try:
            from rmre_bridge import RMREBridge
            bridge = RMREBridge()
            result = bridge.compute_regime(symbol)
            if isinstance(result, dict):
                return result.get("regime", "NEUTRAL")
            return str(result) if result else "NEUTRAL"
        except Exception as e:
            logger.warning(f"[Oracle] Regime unavailable for {symbol}: {e}")
            return "NEUTRAL"

    def _get_fractal_signal(self, symbol: str, price: float) -> dict:
        """
        Pull fractal cascade from SMLEngine and match against known echoes.
        Returns the best matching fractal anchor and confidence.
        """
        try:
            sml = self._get_service("sml")
            if not sml:
                return {}
                
            dm = self._get_service("dm")
            market_history = {}
            if dm:
                for sym in ["SPY", "VIX", "TLT", "DXY", "QQQ", "IWM", "IJR", "XRT", symbol]:
                    try:
                        bars = dm.get_historical_bars(sym, timeframe="1Day", limit=100)
                        if bars:
                            df = pd.DataFrame(bars)
                            # Alpaca returns 'c','o','h','l','v'; Tradier returns 'close' etc.
                            rename_map = {'c': 'close', 'o': 'open', 'h': 'high', 'l': 'low', 'v': 'volume', 't': 'date'}
                            df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)
                            if 'close' in df.columns:
                                market_history[sym] = df
                    except Exception:
                        pass
                        
            result = sml.compute_all(symbol, market_history=market_history)
            score = result.get("fractal_score", 0) if isinstance(result, dict) else 0
            lifecycle = result.get("lifecycle_text", "DORMANT") if isinstance(result, dict) else "DORMANT"
            anchors = FRACTAL_ANCHORS.get(symbol, [])
            best = max(anchors, key=lambda a: a["multiplier"] * score, default=None)
            return {
                "fractal_score": score,
                "fractal_match": best["name"] if best else "None",
                "target_pct": best["target_pct"] if best else 0,
                "lifecycle": lifecycle,
            }
        except Exception as e:
            logger.warning(f"[Oracle] Fractal signal unavailable for {symbol}: {e}")
            return {}

    def _get_mmle_signal(self, symbol: str) -> dict:
        """Pull VPIN and Greeks from MMLE engine."""
        try:
            from mmle_engine import MMLeEngine
            mmle_engines = {}
            if symbol not in mmle_engines:
                mmle_engines[symbol] = MMLeEngine()
            dm = self._get_service("dm")
            if not dm:
                return {}
            bars = dm.get_historical_bars(symbol, timeframe="1Min", limit=200)
            if not bars:
                return {}
            result = mmle_engines[symbol].analyze(symbol, bars)
            return {
                "vpin": result.get("vpin", 0),
                "charm": result.get("charm", 0),
                "vanna": result.get("vanna", 0),
                "axis_collapse": result.get("axis_collapse", False),
                "mmle_signal": result.get("signal", "NEUTRAL"),
            }
        except Exception as e:
            logger.warning(f"[Oracle] MMLE unavailable for {symbol}: {e}")
            return {}

    def _get_proprietary_ema(self, symbol: str) -> dict:
        """Run the proprietary EMA suite (E1, E3, E4) against live bars."""
        try:
            from core.proprietary_ema_engine import run_proprietary_suite
            dm = self._get_service("dm")
            if not dm:
                return {}
            bars = dm.get_historical_bars(symbol, timeframe="1Day", limit=400)
            if not bars:
                return {}
            closes  = [float(b.get("c") or b.get("close",  0)) for b in bars if b.get("c") or b.get("close")]
            volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]
            if len(closes) < 11:
                return {}
            return run_proprietary_suite(closes, volumes, symbol=symbol)
        except Exception as e:
            logger.warning(f"[Oracle] Proprietary EMA unavailable for {symbol}: {e}")
            return {}

    def _get_gamma_flow(self, symbol: str) -> dict:
        """Pull gamma flip signal from GammaFlowEngine."""
        try:
            from gamma_flow_engine import GammaFlowEngine
            import asyncio
            dm = self._get_service("dm")
            if not dm:
                return {}
            polygon = getattr(dm, 'polygon', None) or dm
            watchlist = [symbol]
            gfe = GammaFlowEngine(polygon=polygon, watchlist=watchlist)
            
            # Execute async coroutine safely
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
                
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    # Run in a separate thread's new event loop
                    result = pool.submit(lambda: asyncio.run(gfe.process_ticker(symbol))).result()
            else:
                result = asyncio.run(gfe.process_ticker(symbol))
                
            if not result:
                return {}
            return {
                "gamma_flip": result.get("gamma_flip", False),
                "gamma_regime": result.get("regime", "NEUTRAL"),
                "gamma_score": result.get("score", 0),
            }
        except Exception as e:
            logger.warning(f"[Oracle] Gamma flow unavailable for {symbol}: {e}")
            return {}

    def _score_to_directive(self, score: float, regime: str, gamma_flip: bool, vpin: float) -> str:
        """Convert composite score to BUY/SELL/HOLD/SHIELD directive."""
        if regime == "SHIELD" or score < 5:
            return "SHIELD"
        if regime == "MACRO_COLLAPSE" and vpin > 0.75:
            return "SELL"
        if score >= IGNITION_THRESHOLD and gamma_flip:
            return "BUY"
        if score >= BULL_THRESHOLD:
            return "BUY"
        if score >= WATCH_THRESHOLD:
            return "HOLD"
        if regime == "MACRO_COLLAPSE" and score < WATCH_THRESHOLD:
            return "SELL"
        return "HOLD"

    def _build_reason(self, directive: str, fractal_match: str, gamma_flip: bool,
                      vpin: float, regime: str, score: float,
                      prop_consensus: str = "NEUTRAL") -> str:
        """One-sentence Driver/Navigator reason string."""
        parts = []
        # Triple Lock is the highest-conviction proprietary signal — lead with it
        if prop_consensus == "TRIPLE_LOCK_BULL":
            parts.append("TRIPLE LOCK bullish — three independent proprietary engines aligned")
        elif prop_consensus == "TRIPLE_LOCK_BEAR":
            parts.append("TRIPLE LOCK bearish — three independent proprietary engines aligned")
        elif prop_consensus == "LIE_DETECTOR_ACTIVE":
            parts.append("LIE DETECTOR active — price suppressed while volume kinetics exploding")
        if gamma_flip:
            parts.append("gamma flip confirmed above VWAP")
        if fractal_match and fractal_match != "None":
            parts.append(f"{fractal_match} fractal echo active")
        if vpin > 0.65:
            parts.append(f"order toxicity elevated ({round(vpin * 100)}% VPIN)")
        if regime == "ALPHA_EXPANSION":
            parts.append("regime in Alpha Expansion")
        elif regime == "MACRO_COLLAPSE":
            parts.append("macro collapse pressure detected")
        if not parts:
            parts.append(f"composite score {round(score)}")
        return ". ".join(parts).capitalize() + "."

    def analyze(self, symbol: str) -> dict:
        """
        Main Oracle entry point. Returns full Driver/Navigator payload.
        All data is live from SqueezeOS engines — no mock data.
        """
        ts = datetime.now().isoformat()
        logger.info(f"[Oracle] Analyzing {symbol}...")

        # 1. Live quote
        quote = self._cached(f"quote_{symbol}", lambda: self._get_quote(symbol), ttl=30)
        price = quote.get("price", 0)
        volume = quote.get("volume", 0)

        if price == 0:
            logger.warning(f"[Oracle] No price data for {symbol} — SHIELD")
            return {
                "symbol": symbol, "timestamp": ts,
                "directive": "SHIELD", "confidence": 0, "price": 0,
                "reason": "No live price data. Market may be closed or Tradier unavailable.",
                "sweet_spot": False, "regime": "SHIELD",
            }

        sweet_spot = SWEET_SPOT_MIN <= price <= SWEET_SPOT_MAX

        # 2. Parallel engine calls
        gamma_walls = self._cached(f"walls_{symbol}", lambda: self._get_gamma_walls(symbol, price))
        regime = self._cached(f"regime_{symbol}", lambda: self._get_regime(symbol))
        fractal = self._cached(f"fractal_{symbol}", lambda: self._get_fractal_signal(symbol, price))
        mmle = self._cached(f"mmle_{symbol}", lambda: self._get_mmle_signal(symbol))
        gflow = self._cached(f"gflow_{symbol}", lambda: self._get_gamma_flow(symbol))
        prop_ema = self._cached(f"prop_ema_{symbol}", lambda: self._get_proprietary_ema(symbol))

        # 3. Composite scoring
        score = 0
        score += fractal.get("fractal_score", 0) * 0.30
        score += mmle.get("vpin", 0) * 40  # VPIN 0–1 → 0–40 pts
        score += gflow.get("gamma_score", 0) * 0.30
        if gflow.get("gamma_flip"):
            score += 15
        if regime == "ALPHA_EXPANSION":
            score += 10
        elif regime == "MACRO_COLLAPSE":
            score -= 15
        if mmle.get("axis_collapse"):
            score -= 20
        # Engine 1, 3, 4 proprietary signal contribution
        e1_contrib = prop_ema.get("engine_1", {}).get("score_contrib", 0)
        e3_contrib = prop_ema.get("engine_3", {}).get("score_contrib", 0)
        e4_contrib = prop_ema.get("engine_4", {}).get("score_contrib", 0)
        score += e1_contrib * 0.5  # weight: up to ±12.5 pts (E1 — macro price stretch)
        score += e3_contrib * 0.5  # weight: up to ±10 pts  (E3 — dark-pool volume kinetics)
        score += e4_contrib * 0.5  # weight: up to ±12.5 pts (E4 — price ribbon harmonics)
        # Triple Lock bonus — all three proprietary engines agree at three dimensions
        if prop_ema.get("triple_lock_bull"):
            score += 10
        elif prop_ema.get("triple_lock_bear"):
            score -= 10
        score = max(0, min(100, score))

        # 4. Directive
        vpin = mmle.get("vpin", 0)
        gamma_flip = gflow.get("gamma_flip", False)
        directive = self._score_to_directive(score, regime, gamma_flip, vpin)
        
        # [!!!] HARMONIC CONVERGENCE OVERRIDE [!!!]
        if fractal.get("lifecycle") == "HARMONIC_CONVERGENCE":
            directive = "BUY"
            score = 100.0
            regime = "ALPHA_EXPANSION"  # Force through CEO regime gates

        # 5. Price targets
        mults = REGIME_MULTIPLIERS.get(regime, REGIME_MULTIPLIERS["NEUTRAL"])
        tp1 = round(price * mults["tp1"], 2) if mults["tp1"] else None
        tp2 = round(price * mults["tp2"], 2) if mults["tp2"] else None
        stop = round(price * mults["stop"], 2) if mults["stop"] else None

        # Override for SELL: flip TP/stop
        if directive == "SELL":
            tp1 = round(price * REGIME_MULTIPLIERS["MACRO_COLLAPSE"]["tp1"], 2)
            tp2 = round(price * REGIME_MULTIPLIERS["MACRO_COLLAPSE"]["tp2"], 2)
            stop = round(price * REGIME_MULTIPLIERS["MACRO_COLLAPSE"]["stop"], 2)

        # 6. Fractal target
        target_pct = fractal.get("target_pct", 0)
        fractal_target = round(price * (1 + target_pct), 2) if target_pct else None

        # 7. Build reason
        reason = self._build_reason(
            directive,
            fractal.get("fractal_match", "None"),
            gamma_flip, vpin, regime, score,
            prop_consensus=prop_ema.get("consensus", "NEUTRAL"),
        )
        
        if fractal.get("lifecycle") == "HARMONIC_CONVERGENCE":
            reason = f"[!!!] HARMONIC CONVERGENCE DETECTED [!!!] {reason}"

        payload = {
            "symbol":           symbol,
            "timestamp":        ts,
            "directive":        directive,
            "confidence":       round(score),
            "price":            price,
            "volume":           volume,
            "tp1":              tp1,
            "tp2":              tp2,
            "stop":             stop,
            "fractal_target":   fractal_target,
            "reason":           reason,
            "sweet_spot":       sweet_spot,
            "regime":           regime,
            "gamma_flip":       gamma_flip,
            "gamma_wall_above": gamma_walls.get("wall_above"),
            "gamma_wall_below": gamma_walls.get("wall_below"),
            "vpin":             round(vpin, 3),
            "charm":            round(mmle.get("charm", 0), 4),
            "vanna":            round(mmle.get("vanna", 0), 4),
            "axis_collapse":    mmle.get("axis_collapse", False),
            "fractal_match":    fractal.get("fractal_match", "None"),
            "fractal_score":    round(fractal.get("fractal_score", 0)),
            # Per-engine internal parameters are stripped at this boundary;
            # only signal taxonomy + consensus flags are returned to agents.
            "proprietary_ema":  {
                "consensus":         prop_ema.get("consensus", "NEUTRAL"),
                "triple_lock_bull":  prop_ema.get("triple_lock_bull", False),
                "triple_lock_bear":  prop_ema.get("triple_lock_bear", False),
                "lie_detector":      prop_ema.get("lie_detector_active", False),
                "engine_1":          _redact_engine(prop_ema.get("engine_1", {})),
                "engine_3":          _redact_engine(prop_ema.get("engine_3", {})),
                "engine_4":          _redact_engine(prop_ema.get("engine_4", {})),
            },
            "triple_lock": prop_ema.get("triple_lock_bull") or prop_ema.get("triple_lock_bear"),
        }

        logger.info(f"[Oracle] {symbol} → {directive} | Score: {round(score)} | {reason}")
        return payload


# ── Multi-symbol batch ──
def run_oracle_batch(symbols: list, services: dict) -> dict:
    engine = OracleEngine(services)
    results = {}
    for sym in symbols:
        try:
            results[sym] = engine.analyze(sym)
        except Exception as e:
            logger.error(f"[Oracle] Batch error for {sym}: {e}")
            results[sym] = {
                "symbol": sym, "directive": "SHIELD", "confidence": 0,
                "reason": f"Engine error: {e}", "timestamp": datetime.now().isoformat()
            }
    return results


# Emergency fallback only — the live scan universe (state.quotes.keys()) drives the real list.
# These 3 are always included even when the scanner hasn't warmed up yet.
ORACLE_SYMBOLS = ["IWM", "GME", "AMC"]


# ── Oracle batch background cache ────────────────────────────────────────────
# run_oracle_batch() analyzes the full live scan universe (hundreds-to-thousands
# of tickers post Law-2 discovery). Running it synchronously per HTTP request on
# /api/oracle blew past callers' timeouts (e.g. the Robinhood executor's 20s
# read timeout) on every single poll. Same fix as /api/beastmode: a background
# thread refreshes this cache on an interval and the route returns it instantly.
_ORACLE_BATCH_REFRESH_S = int(os.environ.get("ORACLE_BATCH_REFRESH_S", "60"))
_oracle_cache      = {"results": {}, "ts": 0, "universe_size": 0}
_oracle_last_good  = {"results": {}, "ts": 0, "universe_size": 0}  # never wiped
_oracle_lock = threading.Lock()
_oracle_thread_started = False


def _oracle_batch_refresh_loop():
    logger.info("[Oracle] Background batch refresh thread active (every %ss)", _ORACLE_BATCH_REFRESH_S)
    time.sleep(8)  # let services init
    while True:
        try:
            from core.legacy import get_service  # deferred — legacy.py imports this module at top level
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            live_universe = list(state.quotes.keys()) if state.quotes else None
            batch_symbols = live_universe if live_universe else ORACLE_SYMBOLS
            results = run_oracle_batch(batch_symbols, services)
            with _oracle_lock:
                _oracle_cache["results"]      = results
                _oracle_cache["universe_size"] = len(batch_symbols)
                _oracle_cache["ts"]            = time.time()
                if results:
                    _oracle_last_good["results"]      = results
                    _oracle_last_good["universe_size"] = len(batch_symbols)
                    _oracle_last_good["ts"]            = time.time()
            logger.info(f"[Oracle] batch cache refreshed — {len(results)} symbols")
        except Exception as e:
            logger.error(f"[Oracle] batch refresh error: {e}")
        time.sleep(_ORACLE_BATCH_REFRESH_S)


def start_oracle_batch_scanner():
    global _oracle_thread_started
    if _oracle_thread_started:
        return
    _oracle_thread_started = True
    threading.Thread(target=_oracle_batch_refresh_loop, daemon=True, name="SML-Oracle-Batch-Scanner").start()


def get_oracle_batch_cache() -> dict:
    """Cached oracle batch results (refreshed by background thread). Falls back to last-good on empty."""
    with _oracle_lock:
        results       = dict(_oracle_cache["results"])
        ts            = _oracle_cache["ts"]
        universe_size = _oracle_cache["universe_size"]
        stale = False
        if not results and _oracle_last_good["results"]:
            results       = dict(_oracle_last_good["results"])
            ts            = _oracle_last_good["ts"]
            universe_size = _oracle_last_good["universe_size"]
            stale = True
    return {"results": results, "ts": ts, "universe_size": universe_size, "stale": stale}
