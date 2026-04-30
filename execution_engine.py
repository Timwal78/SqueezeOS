"""
SQUEEZE OS v4.5 — Shadow Trading & BYOK Execution Engine
════════════════════════════════════════════════════════
High-precision order management tethered to user API keys.
Supports "Shadow" (simulated) and "Live" execution modes.
"""
import os
import json
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
from threading import Lock
from delta_neutrality import DeltaNeutralityEngine
try:
    from BEAST.gex.sml_gex_engine import GEXEngine
    from BEAST.hedger.autonomous_hedger import AutonomousHedger, HedgerConfig
except ImportError:
    # BEAST module not deployed — stub out for graceful degradation
    GEXEngine = None
    AutonomousHedger = None
    class HedgerConfig:
        def __init__(self, **kw): pass

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, schwab_api, rmre_bridge, performance_tracker=None, discord_alerts=None):
        self.schwab = schwab_api
        self.rmre = rmre_bridge
        self.tracker = performance_tracker
        self.discord = discord_alerts
        self.lock = Lock()
        
        self.live_mode = False # Default to Shadow Mode for safety
        self.max_order_value = 500.0
        self.schwab_account_hash = None # Cached on-demand
        
        # --- AUTOPILOT GUARDRAILS ---
        self.max_autopilot_trades = 3
        self.autopilot_cooldown = 900 # 15 mins
        self.last_autopilot_entry = 0
        
        self.trade_log_path = 'trade_log.json'
        self.active_trades: Dict[str, Dict] = {}
        self.load_trades()
        
        # --- RISK UPGRADE: ATR-based Dynamic SL ---
        self.atr_multiplier = 1.5 # Standard institutional trail
        self.meme_atr_multiplier = 2.5 # Extra room for AMC/GME
        
        # Phase 2: Risk Management
        self.delta_engine = DeltaNeutralityEngine(self, rmre_bridge)
        
        # BEAST Integration: GEX Engine & Autonomous Hedger
        self.gex_cache: Dict[str, Dict] = {}
        self.last_gex_update = 0
        try:
            if AutonomousHedger is not None:
                self.beast_hedger = AutonomousHedger(HedgerConfig(dry_run=True))
            else:
                self.beast_hedger = None
        except Exception as e:
            logger.warning(f"[BEAST] Hedger init failed (will continue without): {e}")
            self.beast_hedger = None

    def load_trades(self):
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.active_trades = data.get('active', {})
                    elif isinstance(data, list):
                        # Convert list format to dict format for v4.5+ consistency
                        self.active_trades = {t.get('id', f"tr_{i}"): t for i, t in enumerate(data)}
                    
                    # Cleanup: Ensure all loaded trades are dictionaries
                    self.active_trades = {k: v for k, v in self.active_trades.items() if isinstance(v, dict)}
                    logger.info(f"[EXECUTION] Loaded {len(self.active_trades)} active trades.")
            except Exception as e:
                logger.error(f"[EXECUTION] Load error: {e}")
                self.active_trades = {}

    def get_active_trades(self) -> List[Dict]:
        """Returns list of all open positions with guaranteed JSON serialization."""
        with self.lock:
            try:
                final = []
                for tid, t in self.active_trades.items():
                    # Create a clean copy of the trade to prevent serialization issues
                    # with potentially non-primitive objects (locks, class instances, etc.)
                    clean_trade = {
                        "id": str(t.get('id', tid)),
                        "symbol": str(t.get('symbol', 'UNKNOWN')),
                        "side": str(t.get('side', 'BUY')),
                        "qty": int(t.get('qty', 0)),
                        "entry_price": float(t.get('entry_price', 0.0)),
                        "current_price": float(t.get('current_price', 0.0)),
                        "sl": float(t.get('sl', 0.0)),
                        "tp": float(t.get('tp', 0.0)),
                        "status": str(t.get('status', 'OPEN')),
                        "opened_at": float(t.get('opened_at', time.time())),
                        "regime": str(t.get('regime', 'UNKNOWN')),
                        "net_pressure": float(t.get('net_pressure', 0.0)),
                        "hurst": float(t.get('hurst', 0.5)),
                        "validation_reason": str(t.get('validation_reason', '')),
                        "is_hedge": bool(t.get('is_hedge', False)),
                        "pnl": float(t.get('pnl', 0.0)),
                        "pnl_pct": float(t.get('pnl_pct', 0.0))
                    }
                    final.append(clean_trade)
                    
                # Sort by opened_at descending
                return sorted(final, key=lambda x: x.get('opened_at', 0.0), reverse=True)
            except Exception as e:
                logger.error(f"[EXECUTION] get_active_trades error: {e}")
                return []

    def save_trades(self):
        with self.lock:
            try:
                # Load existing log to maintain history
                history = []
                if os.path.exists(self.trade_log_path):
                    with open(self.trade_log_path, 'r') as f:
                        old_data = json.load(f)
                        history = old_data.get('history', [])
                
                data = {
                    'active': self.active_trades,
                    'history': history,
                    'last_updated': time.time()
                }
                with open(self.trade_log_path, 'w') as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"[EXECUTION] Save error: {e}")

    def calculate_atr(self, symbol: str, period: int = 14) -> float:
        """
        Calculates the Average True Range (ATR) using minute-level aggregates.
        """
        if not self.tracker or not self.tracker.data_manager:
            return 0.0
            
        dm = self.tracker.data_manager
        if not dm.polygon or not dm.polygon.available:
            return 0.0
            
        try:
            # Fetch last 30 minutes of 1m data
            aggs = dm.polygon.get_aggregates(symbol, 1, 'minute', limit=period + 5)
            if not aggs or len(aggs) < period:
                return 0.0
                
            # Sort by timestamp (asc) for ATR calculation
            df = pd.DataFrame(aggs).sort_values('timestamp')
            
            # TR = max(H-L, |H-Cp|, |L-Cp|)
            df['prev_close'] = df['close'].shift(1)
            df['tr'] = np.maximum(df['high'] - df['low'], 
                       np.maximum(abs(df['high'] - df['prev_close']), 
                                  abs(df['low'] - df['prev_close'])))
            
            # Simple Moving Average of TR for ATR
            atr = df['tr'].tail(period).mean()
            return float(atr)
        except Exception as e:
            logger.error(f"[RISK] ATR Calculation Error for {symbol}: {e}")
            return 0.0

    def should_execute(self, symbol: str, side: str, is_live: bool = False) -> Dict[str, Any]:
        """
        Institutional Filter: Hurst-Regime Validation.
        Enforces entry ONLY in trending regimes with high hurst conviction.
        """
        if not self.rmre:
            return {"allow": True, "reason": "RMRE Offline - Neutral Entry"}
            
        try:
            regime = self.rmre.compute_regime(symbol)
            hurst = regime.get('hurst_val', 0.5)
            label = regime.get('regime_label', 'UNKNOWN')
            
            # Law 1: Hurst Filtering
            # Shadow Mode: > 0.55
            # LIVE Mode: > 0.60 (Institutional Tier Only)
            threshold = 0.62 if is_live else 0.55
            is_trending = hurst > threshold
            
            # Law 2: Regime Filtering
            # Entry allowed in EXECUTION (Trending) or CONFLICT (Early Squeeze Setup)
            allow_regime = label in ('EXECUTION', 'CONFLICT')
            
            if is_trending and allow_regime:
                return {"allow": True, "reason": f"VALIDATED: {label} Regime | Hurst: {hurst:.2f}"}
            
            # Rejection Logic
            if not is_trending:
                return {"allow": False, "reason": f"FILTERED: Lack of Hurst Conviction ({hurst:.2f} < {threshold})"}
            if not allow_regime:
                return {"allow": False, "reason": f"FILTERED: Invalid Regime State ({label})"}
                
            return {"allow": False, "reason": "FILTERED: Risk/Regime Mismatch"}
        except Exception as e:
            logger.error(f"[EXECUTION] Filtering Error: {e}")
            return {"allow": True, "reason": "Bypass Error - Safety Default"}

    def get_gamma_walls(self, symbol: str) -> Dict[str, Any]:
        """
        Institutional Gamma Wall Detection via BEAST GEX Engine.
        Returns call_wall, put_wall, and zero_gamma_level.
        """
        now = time.time()
        if symbol in self.gex_cache and (now - self.last_gex_update) < 3600:
            return self.gex_cache[symbol]
            
        if GEXEngine is None:
            return {}
        try:
            engine = GEXEngine(symbol.upper(), max_expiries=3)
            snap = engine.compute()
            
            result = {
                "call_wall": float(snap.call_wall) if snap.call_wall is not None else None,
                "put_wall": float(snap.put_wall) if snap.put_wall is not None else None,
                "zero_gamma": float(snap.zero_gamma_level) if snap.zero_gamma_level is not None else None,
                "regime": snap.gex_regime,
                "total_gex": float(snap.total_gex),
                "updated_at": now
            }
            self.gex_cache[symbol] = result
            self.last_gex_update = now
            return result
        except Exception as e:
            logger.error(f"[GEX] Error for {symbol}: {e}")
            return {}

    def execute_shadow_trade(self, symbol: str, side: str, quantity: int, price: float):
        """
        Executes a 'Shadow' trade with realistic slippage and automated risk ranges.
        """
        if self.live_mode:
            return self.execute_live_trade(symbol, side, quantity, price)

        # 0. Apply Institutional Filtering
        validation = self.should_execute(symbol, side)
        if not validation['allow']:
            msg = f"[SHADOW] Trade Filtered: {symbol} - {validation['reason']}"
            logger.warning(msg)
            return {"status": "FILTERED", "reason": validation['reason']}

        logger.info(f"[SHADOW] Executing {side} {quantity} {symbol} @ {price} | {validation['reason']}")
        
        # 1. Apply Institutional Slippage (1-2 ticks)
        slippage = 0.01 if side == 'BUY' else -0.01
        entry_price = price + slippage
        
        # 2. Extract Risk Ranges from RMRE
        ranges = {}
        regime_label = 'UNKNOWN'
        net_pressure = 0
        hurst_val = 0.5
        
        if self.rmre and hasattr(self.rmre, 'compute_regime'):
            try:
                regime = self.rmre.compute_regime(symbol)
                ranges = regime.get('risk_ranges', {})
                regime_label = regime.get('regime_label', 'UNKNOWN')
                net_pressure = regime.get('net_pressure', 0)
                hurst_val = regime.get('hurst_val', 0.5)
            except Exception as e:
                logger.warning(f"[SHADOW] RMRE compute error: {e}")
        
        # Automated TP/SL Logic: ATR-Based Dynamic Risk
        atr = self.calculate_atr(symbol)
        multiplier = self.meme_atr_multiplier if symbol in ('AMC', 'GME') else self.atr_multiplier
        
        if atr > 0:
            # Dynamic SL based on ATR
            sl = entry_price - (atr * multiplier) if side == 'BUY' else entry_price + (atr * multiplier)
            # TP targeted at 2x SL distance (Risk/Reward 1:2)
            tp = entry_price + (atr * multiplier * 2.0) if side == 'BUY' else entry_price - (atr * multiplier * 2.0)
            risk_type = "ATR_DYNAMIC"
        else:
            # Fallback to RMRE ranges or 5% default
            it_range = ranges.get('it', {})
            sl = float(it_range.get('low', entry_price * 0.95))
            tp = float(it_range.get('high', entry_price * 1.05))
            risk_type = "RMRE_STATIC"
        
        # 3. Regime-Aware Risk Tuning
        if regime_label == 'CONFLICT':
            # Tighter stops in conflict (Squeeze watch)
            dist = abs(entry_price - sl)
            sl = entry_price - (dist * 0.7) if side == 'BUY' else entry_price + (dist * 0.7)
        elif regime_label == 'EXECUTION':
            # Let runners breathe in execution
            dist = abs(entry_price - tp)
            tp = entry_price + (dist * 1.25) if side == 'BUY' else entry_price - (dist * 1.25)

        trade_id = f"SHADOW_{symbol}_{int(time.time())}"
        
        trade = {
            'id': trade_id,
            'symbol': symbol,
            'side': side,
            'qty': quantity,
            'entry_price': entry_price,
            'current_price': entry_price,
            'sl': sl,
            'tp': tp,
            'status': 'OPEN',
            'opened_at': time.time(),
            'regime': regime_label,
            'net_pressure': net_pressure,
            'hurst': hurst_val,
            'validation_reason': validation['reason']
        }
        
        with self.lock:
            self.active_trades[trade_id] = trade
        
        self.save_trades()
        
        # Expert Precision: Fire real-time notification
        if self.discord:
            self.discord.fire_beast_trade_alert(trade)
            
        return trade

    def execute_live_trade(self, symbol: str, side: str, quantity: int, price: float):
        """
        Executes a REAL order on Schwab or Alpaca.
        """
        total_value = quantity * price
        if total_value > self.max_order_value:
            msg = f"🛑 RISK REJECTION: Order value ${total_value:.2f} exceeds limit ${self.max_order_value}"
            logger.error(msg)
            return {"status": "REJECTED", "reason": msg}

        validation = self.should_execute(symbol, side, is_live=True)
        if not validation['allow']:
            logger.warning(f"🛑 LIVE Filtered: {symbol} - {validation['reason']}")
            return {"status": "FILTERED", "reason": validation['reason']}

        logger.info(f"🚀 LIVE EXECUTION: {side} {quantity} {symbol} @ {price}")

        res = {"status": "error", "message": "No broker available"}
        
        if price < 50 and hasattr(self.tracker, 'data_manager') and self.tracker.data_manager.alpaca.available:
            res = self.tracker.data_manager.alpaca.place_order(symbol, quantity, side)
        elif self.schwab and self.schwab.access_token:
            if not self.schwab_account_hash:
                accounts = self.schwab.get_account_numbers()
                if accounts:
                    self.schwab_account_hash = accounts[0].get('hashValue')
            
            if self.schwab_account_hash:
                payload = {
                    "orderType": "MARKET",
                    "session": "NORMAL",
                    "duration": "DAY",
                    "orderStrategyType": "SINGLE",
                    "orderLegCollection": [{
                        "instruction": side.upper(),
                        "quantity": int(quantity),
                        "instrument": {"symbol": symbol, "assetType": "EQUITY"}
                    }]
                }
                # Check for place_order method on schwab_api instance
                if hasattr(self.schwab, 'place_order'):
                    res = self.schwab.place_order(self.schwab_account_hash, payload)

        if res.get('status') == 'success':
            trade_id = f"LIVE_{res.get('order_id') or symbol}_{int(time.time())}"
            trade = {
                'id': trade_id,
                'symbol': symbol,
                'side': side,
                'qty': quantity,
                'entry_price': price,
                'current_price': price,
                'sl': price * 0.95 if side == 'BUY' else price * 1.05,
                'tp': price * 1.15 if side == 'BUY' else price * 0.85,
                'status': 'OPEN',
                'opened_at': time.time(),
                'mode': 'LIVE',
                'order_id': res.get('order_id')
            }
            with self.lock:
                self.active_trades[trade_id] = trade
            self.save_trades()
            
            if self.discord:
                self.discord.fire_beast_trade_alert(trade)
            
            return trade
        
        return res

    def execute_hjb_hedge(self, quotes: Dict[str, Dict]):
        """
        Automated HJB Delta Neutralization.
        Synchronizes shadow SPY positions to offset portfolio-wide beta stress.
        """
        if not self.delta_engine:
            return
            
        instruction = self.delta_engine.get_hjb_hedge_instruction(quotes)
        if not instruction:
            # Check if we have an existing hedge that needs clearing
            # If net delta is now near zero, we should close existing SPY hedges
            # (Simplified for v1: only add/adjust)
            return

        # Find existing SPY hedge
        existing_hedge_id = None
        for tid, trade in self.active_trades.items():
            if trade['symbol'] == 'SPY' and trade.get('is_hedge'):
                existing_hedge_id = tid
                break
        
        # If instruction matches existing side/qty (approx), do nothing
        if existing_hedge_id:
            existing = self.active_trades[existing_hedge_id]
            if existing['side'] == instruction['side'] and abs(existing['qty'] - instruction['qty']) < 5:
                return # Already hedged sufficiently
            
            # If side changed or qty differs significantly, close and flip
            logger.info(f"[HEDGE] Adjusting Delta Offset. Closing {existing_hedge_id}")
            self.close_trade(existing_hedge_id)

        # Execute new hedge
        spy_quote = quotes.get('SPY', {})
        price = spy_quote.get('price')
        if price is None:
            logger.warning(f"[HEDGE] SPY price unavailable in quotes, cannot execute hedge")
            return
        logger.info(f"[HEDGE] {instruction['reason']} | Order: {instruction['side']} {instruction['qty']} SPY @ {price}")

        # Bypass normal filtering for hedges
        trade_id = f"HEDGE_SPY_{int(time.time())}"
        trade = {
            'id': trade_id,
            'symbol': 'SPY',
            'side': instruction['side'],
            'qty': instruction['qty'],
            'entry_price': price,
            'current_price': price,
            'sl': 0.0, # Hedges don't have standard SL/TP
            'tp': 0.0,
            'status': 'OPEN',
            'opened_at': time.time(),
            'is_hedge': True,
            'reason': instruction['reason']
        }

        with self.lock:
            self.active_trades[trade_id] = trade
        self.save_trades()

    def update_live_prices(self, quotes: Dict[str, Dict]):
        """Updates active trades with latest market data and checks for exits."""
        with self.lock:
            changed = False
            to_close = []
            
            # Periodically check HJB Delta Neutrality (approx every price loop)
            self.execute_hjb_hedge(quotes)
            
            # BEAST: Autonomous Hedging based on Portfolio Notional
            if self.beast_hedger and getattr(self.beast_hedger, 'available', False):
                total_notional = sum(t['current_price'] * t['qty'] for t in self.active_trades.values())
                hedge_shares = self.beast_hedger.manage_delta(total_notional, quotes)
                if hedge_shares != 0:
                    logger.info(f"[BEAST] Delta Stress Detected. Suggested Hedge: {hedge_shares} shares")
                # In production, we would trigger self.execute_live_trade here if autopilot enabled
            
            # Update Delta Stress History for Performance Analytics
            if self.tracker and self.delta_engine:
                delta_data = self.delta_engine.calculate_basket_delta(quotes)
                self.tracker.update_delta_stress(delta_data.get('total_delta_stress', 0.0))
            
            for tid, trade in self.active_trades.items():
                sym = trade['symbol']
                if sym in quotes:
                    price = float(quotes[sym].get('price', trade['current_price']))
                    trade['current_price'] = price
                    
                    # 4. Trailing SL Logic (Only in EXECUTION regime)
                    if trade.get('regime') == 'EXECUTION':
                        atr = self.calculate_atr(sym)
                        multiplier = self.meme_atr_multiplier if sym in ('AMC', 'GME') else self.atr_multiplier
                        
                        if atr > 0:
                            if trade['side'] == 'BUY':
                                new_sl = price - (atr * multiplier)
                                if new_sl > trade.get('sl', 0):
                                    trade['sl'] = new_sl
                            else:
                                new_sl = price + (atr * multiplier)
                                if new_sl < trade.get('sl', price * 2):
                                    trade['sl'] = new_sl
                        else:
                            # Fallback to proxy if ATR fails
                            if trade['side'] == 'BUY':
                                new_sl = price * 0.98
                                if new_sl > trade.get('sl', 0):
                                    trade['sl'] = new_sl
                            else:
                                new_sl = price * 1.02
                                if new_sl < trade.get('sl', price * 2):
                                    trade['sl'] = new_sl

                    # Check SL
                    if trade['side'] == 'BUY' and price <= trade['sl']:
                        trade['exit_reason'] = 'STOP_LOSS'
                        to_close.append(tid)
                    elif trade['side'] == 'SELL' and price >= trade['sl']:
                        trade['exit_reason'] = 'STOP_LOSS'
                        to_close.append(tid)
                    
                    # Check TP
                    elif trade['side'] == 'BUY' and price >= trade['tp']:
                        trade['exit_reason'] = 'TAKE_PROFIT'
                        to_close.append(tid)
                    elif trade['side'] == 'SELL' and price <= trade['tp']:
                        trade['exit_reason'] = 'TAKE_PROFIT'
                        to_close.append(tid)
                    
                    changed = True
            
            for tid in to_close:
                self.close_trade(tid)
                
            if changed:
                self.save_trades()

    def get_trade_history(self) -> List[Dict]:
        """Returns last 100 closed trades."""
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    return data.get('history', [])
            except Exception as e:
                logger.warning(f"[EXECUTION] Failed to read trade history: {e}")
                return []
        return []

    def close_trade(self, trade_id: str):
        if trade_id not in self.active_trades:
            return None
        
        trade = self.active_trades.pop(trade_id)
        trade['status'] = 'CLOSED'
        trade['closed_at'] = time.time()
        trade['pnl'] = (trade['current_price'] - trade['entry_price']) * trade['qty']
        if trade['side'] == 'SELL':
            trade['pnl'] *= -1
            
        # Add to history
        try:
            history = []
            if os.path.exists(self.trade_log_path):
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        history = data.get('history', [])
                    elif isinstance(data, list):
                        history = data
            
            history.insert(0, trade)
            data_to_save = {
                'active': self.active_trades,
                'history': history[:100],
                'last_updated': time.time()
            }
            with open(self.trade_log_path, 'w') as f:
                json.dump(data_to_save, f, indent=4)
        except Exception as e:
            logger.error(f"[EXECUTION] Close log error: {e}")
        
        # Add to performance tracker
        if self.tracker:
            self.tracker.add_trade_result(trade['pnl'], is_hedge=trade.get('is_hedge', False))
            
        logger.info(f"[EXECUTION] Closed {trade_id} | PnL: ${trade['pnl']:.2f}")
        return trade

class SignalEmitter:
    """Standardized BYOK Signal Emitter for Monetization/API consumption."""
    def __init__(self, engine, analyzer):
        self.engine = engine
        self.analyzer = analyzer

    def emit_package(self, symbol, squeeze_score=0.0, regime_data=None):
        """
        Final data fusion: Squeeze + Gamma + Regime.
        """
        profile = self.engine.get_ticker_profile(symbol) or {}
        
        # Institutional grading logic
        status = "BULLISH EMISSION" if squeeze_score > 60 else "MONITORING"
        
        # Hurst-Regime Filtering (Roadmap Phase 1)
        hurst_val = regime_data.get('hurst_val', 0.5) if regime_data else 0.5
        regime_label = regime_data.get('regime_label', 'UNKNOWN') if regime_data else 'UNKNOWN'
        
        # Determine Convergence & Conviction
        conviction = "HIGH"
        if hurst_val > 0.58:
            status = f"TRENDING {status}"
            conviction = "INSTITUTIONAL"
        elif hurst_val < 0.42:
            status = f"SCALP {status}"
            conviction = "MEAN-REVERTING"
            
        return {
            "symbol": symbol,
            "ts": time.time(),
            "institutional_intel": {
                "inventory_z": profile.get('inventory_z', 0),
                "hjb_rate": profile.get('hjb_hedge_rate', 0),
                "regime": profile.get('profile_shape', 'neutral'),
                "hurst_val": hurst_val,
                "regime_label": regime_label
            },
            "convergence": {
                "beast_score": round(squeeze_score, 1),
                "status": status,
                "conviction": conviction
            },
            "moass_watch": profile.get('inventory_z', 0) > 2.5,
            "verified": squeeze_score > 75 and hurst_val > 0.55
        }
